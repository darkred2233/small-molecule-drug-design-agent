"""Local P2Rank runtime probe and project-scoped pocket prediction service."""

from __future__ import annotations

import csv
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from medagent.core.config import Settings
from medagent.db.models import BindingSite, Project, Target, TargetResourceLink, UploadedFile
from medagent.services.file_ingestion import path_from_storage_uri, safe_filename
from medagent.services.ids import new_id
from medagent.services.structure_workflow import register_uploaded_structure, structure_source_file
from medagent.services.scientific_execution import (
    CapabilitySnapshot,
    EvidenceKind,
    EvidenceLevel,
    ScientificResult,
    artifact_snapshot,
)
from medagent.services.scientific_persistence import persist_scientific_result
from medagent.services.tool_config import (
    configured_paths_exist,
    get_tool_runtime_config,
    resolve_configured_path,
)


P2RANK_VERSION_PATTERN = re.compile(r"P2Rank\s+([0-9][^\s]*)")
GRID_PADDING_ANGSTROM = 4.0
GRID_MIN_SIZE_ANGSTROM = 16.0
GRID_MAX_SIZE_ANGSTROM = 30.0


@dataclass
class P2RankProjectResult:
    status: str
    warnings: list[str] = field(default_factory=list)
    binding_sites: list[BindingSite] = field(default_factory=list)
    manifest_id: str | None = None
    output_directory: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "warnings": self.warnings,
            "binding_site_ids": [site.binding_site_id for site in self.binding_sites],
            "manifest_id": self.manifest_id,
            "output_directory": self.output_directory,
            "input_status": "predicted_not_experimentally_validated",
        }


@dataclass(frozen=True)
class P2RankPocket:
    name: str
    rank: int
    score: float
    probability: float | None
    center: list[float]
    residue_ids: list[str]


def p2rank_tool_status() -> dict[str, Any]:
    """Report the installed P2Rank runtime without treating a missing runtime as usable."""
    config = get_tool_runtime_config("p2rank", default_timeout_seconds=600)
    files_ready, missing_paths = configured_paths_exist(config)
    java = resolve_configured_path(config.python_executable)
    launcher = resolve_configured_path(config.command)
    working_directory = resolve_configured_path(config.working_directory)
    status: dict[str, Any] = {
        "available": False,
        "runtime_available": False,
        "java_executable": str(java) if java and java.is_file() else None,
        "launcher": str(launcher) if launcher and launcher.is_file() else None,
        "working_directory": str(working_directory) if working_directory and working_directory.is_dir() else None,
        "missing_paths": missing_paths,
        "warning": None,
        "version": None,
        **config.as_status(),
    }
    if (
        not files_ready
        or java is None
        or not java.is_file()
        or launcher is None
        or not launcher.is_file()
        or working_directory is None
        or not working_directory.is_dir()
    ):
        status["warning"] = "p2rank_required_files_missing"
        return status

    try:
        probe = subprocess.run(
            _p2rank_command(launcher, ["help"]),
            capture_output=True,
            text=True,
            cwd=working_directory,
            env=_p2rank_environment(java),
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        status["warning"] = "p2rank_runtime_probe_failed"
        return status

    output = "\n".join(part for part in (probe.stdout, probe.stderr) if part)
    version_match = P2RANK_VERSION_PATTERN.search(output)
    # P2Rank 2.5.1 exits with 1 for its usage screen.  Its banner and command
    # list are therefore the supported probe contract, not the exit code alone.
    probe_succeeded = bool(version_match and "predict" in output and "usage" in output.lower())
    status["runtime_available"] = probe_succeeded
    status["available"] = probe_succeeded
    status["version"] = version_match.group(1) if version_match else None
    status["version_output"] = output[:1000]
    if not probe_succeeded:
        status["warning"] = "p2rank_runtime_probe_failed"
    return status


def run_project_p2rank(
    db: Session,
    settings: Settings,
    project: Project,
    source_file_id: str | None = None,
    structure_id: str | None = None,
) -> P2RankProjectResult:
    """Predict all pockets for one project-owned PDB and persist real artifacts."""
    if not project.target_id or db.query(Target).filter_by(target_id=project.target_id).one_or_none() is None:
        raise ValueError("Project target_id does not match a known target.")
    structure = None
    if structure_id:
        structure, source_file = structure_source_file(db, settings, project, structure_id)
        source_file_id = source_file.file_id
    elif source_file_id:
        structure = register_uploaded_structure(
            db,
            settings,
            project,
            source_file_id,
        )
        structure, source_file = structure_source_file(
            db, settings, project, structure.structure_id
        )
        source_file_id = source_file.file_id
    else:
        raise ValueError("Either structure_id or source_file_id is required.")
    if source_file is None:
        raise ValueError("source_file_id does not belong to this project.")
    source_path = path_from_storage_uri(settings, source_file.storage_path)
    if not source_path.is_file():
        raise ValueError("Uploaded receptor file does not exist on disk.")
    if source_path.suffix.lower() != ".pdb":
        raise ValueError("P2Rank currently requires a project-owned .pdb receptor file.")

    status = p2rank_tool_status()
    snapshot = CapabilitySnapshot.create(
        tools={"p2rank": status},
        runtime={"java_executable": status.get("java_executable")},
    )
    request = {"source_file_id": source_file_id, "source_filename": source_file.filename}
    if not status.get("available"):
        scientific_result = ScientificResult.unavailable(
            stage="pocket_prediction",
            tool_name="p2rank",
            status="blocked",
            warnings=[str(status.get("warning") or "p2rank_runtime_blocked")],
        )
        manifest = persist_scientific_result(
            db,
            scientific_result,
            snapshot=snapshot,
            request=request,
            project_id=project.project_id,
        )
        return P2RankProjectResult(
            status="runtime_blocked",
            warnings=scientific_result.warnings,
            manifest_id=manifest.manifest_id,
        )

    run_id = new_id("P2R")
    run_directory = Path(settings.storage_local_root) / project.project_id / "p2rank_runs" / run_id
    output_directory = run_directory / "output"
    run_directory.mkdir(parents=True, exist_ok=False)
    input_path = run_directory / f"input_{safe_filename(source_path.name)}"
    shutil.copy2(source_path, input_path)
    java = Path(str(status["java_executable"]))
    launcher = Path(str(status["launcher"]))
    working_directory = Path(str(status["working_directory"]))
    command = _p2rank_command(
        launcher,
        [
            "predict",
            "-f",
            str(input_path),
            "-o",
            str(output_directory),
            "-visualizations",
            "0",
            "-threads",
            "1",
        ],
    )
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            cwd=working_directory,
            env=_p2rank_environment(java),
            timeout=int(status.get("configured_timeout_seconds") or 600),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return _persist_failure(
            db, snapshot, request, project, input_path, run_directory, command,
            "p2rank_execution_timeout", str(exc), None,
        )
    except OSError as exc:
        return _persist_failure(
            db, snapshot, request, project, input_path, run_directory, command,
            "p2rank_execution_failed", str(exc), None,
        )

    if completed.returncode != 0:
        return _persist_failure(
            db, snapshot, request, project, input_path, run_directory, command,
            "p2rank_execution_failed", completed.stderr, completed.returncode, completed.stdout,
        )

    predictions_csv = _single_output(output_directory, "*_predictions.csv")
    residues_csv = _single_output(output_directory, "*_residues.csv")
    if predictions_csv is None:
        return _persist_failure(
            db, snapshot, request, project, input_path, run_directory, command,
            "p2rank_predictions_missing", completed.stderr, completed.returncode, completed.stdout,
        )
    try:
        pockets = _read_predictions(predictions_csv)
        if not pockets:
            return _persist_failure(
                db, snapshot, request, project, input_path, run_directory, command,
                "p2rank_no_pockets_predicted", completed.stderr, completed.returncode, completed.stdout,
            )
        binding_sites, pocket_paths = _create_binding_sites(
            db,
            project,
            source_file,
            input_path,
            pockets,
            run_directory,
            str(status.get("version") or "unknown"),
            structure_id=structure.structure_id if structure is not None else None,
        )
    except (OSError, ValueError, csv.Error) as exc:
        return _persist_failure(
            db, snapshot, request, project, input_path, run_directory, command,
            "p2rank_output_parse_failed", str(exc), completed.returncode, completed.stdout,
        )

    output_paths: dict[str, Path] = {"predictions_csv": predictions_csv}
    if residues_csv is not None:
        output_paths["residues_csv"] = residues_csv
    for role, path in _known_run_files(output_directory).items():
        output_paths.setdefault(role, path)
    for site, pocket_path in zip(binding_sites, pocket_paths, strict=True):
        output_paths[f"pocket_{site.binding_site_id}"] = pocket_path
    output_artifacts = artifact_snapshot(output_paths)

    scientific_result = ScientificResult(
        stage="pocket_prediction",
        status="succeeded",
        evidence_level=EvidenceLevel.L2,
        evidence_kind=EvidenceKind.COMPUTATIONAL,
        execution_mode="p2rank_local",
        tool_name="p2rank",
        tool_version=status.get("version"),
        warnings=["predicted_not_experimentally_validated"],
        parameters={
            "grid_derivation": "p2rank_residue_bounds_v1",
            "grid_padding_angstrom": GRID_PADDING_ANGSTROM,
            "grid_min_size_angstrom": GRID_MIN_SIZE_ANGSTROM,
            "grid_max_size_angstrom": GRID_MAX_SIZE_ANGSTROM,
            "visualizations": False,
            "threads": 1,
        },
        input_artifacts=artifact_snapshot({"receptor_pdb": input_path}),
        output_artifacts=output_artifacts,
        provenance={
            "command": command,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "exit_code": completed.returncode,
        },
        payload={
            "structure_id": structure.structure_id if structure is not None else None,
            "binding_sites": [
                {
                    "binding_site_id": site.binding_site_id,
                    "structure_id": site.structure_id,
                    "center": (site.grid_box or {}).get("center"),
                    "size": (site.grid_box or {}).get("size"),
                    "key_residues": site.key_residues or [],
                    "pocket_artifact": output_artifacts.get(
                        f"pocket_{site.binding_site_id}", {}
                    ),
                    "grid_derivation": (site.grid_box or {}).get("derivation"),
                }
                for site in binding_sites
            ],
        },
    )
    manifest = persist_scientific_result(
        db,
        scientific_result,
        snapshot=snapshot,
        request=request,
        project_id=project.project_id,
    )
    _link_project_artifacts(db, project, scientific_result, binding_sites)
    if structure is not None:
        structure.status = "pocket_predicted"
        structure.metadata_json = {
            **(structure.metadata_json or {}),
            "latest_p2rank_manifest_id": manifest.manifest_id,
            "binding_site_ids": [site.binding_site_id for site in binding_sites],
        }
    return P2RankProjectResult(
        status="succeeded",
        warnings=scientific_result.warnings,
        binding_sites=binding_sites,
        manifest_id=manifest.manifest_id,
        output_directory=str(output_directory),
    )


def _p2rank_command(launcher: Path, arguments: list[str]) -> list[str]:
    return [str(launcher), *arguments]


def _p2rank_environment(java: Path) -> dict[str, str]:
    environment = dict(os.environ)
    environment["JAVA_HOME"] = str(java.parent.parent)
    return environment


def _single_output(output_directory: Path, pattern: str) -> Path | None:
    matches = sorted(output_directory.glob(pattern)) if output_directory.is_dir() else []
    return matches[0] if len(matches) == 1 else None


def _read_predictions(predictions_csv: Path) -> list[P2RankPocket]:
    with predictions_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, skipinitialspace=True)
        pockets: list[P2RankPocket] = []
        for raw_row in reader:
            row = {(key or "").strip(): (value or "").strip() for key, value in raw_row.items()}
            try:
                rank = int(row["rank"])
                center = [float(row["center_x"]), float(row["center_y"]), float(row["center_z"])]
                score = float(row["score"])
            except (KeyError, ValueError) as exc:
                raise ValueError("P2Rank predictions CSV has an invalid pocket row.") from exc
            pockets.append(
                P2RankPocket(
                    name=row.get("name") or f"pocket{rank}",
                    rank=rank,
                    score=score,
                    probability=_optional_float(row.get("probability")),
                    center=center,
                    residue_ids=[item for item in row.get("residue_ids", "").split() if item],
                )
            )
    return sorted(pockets, key=lambda pocket: pocket.rank)


def _create_binding_sites(
    db: Session,
    project: Project,
    source_file: UploadedFile,
    receptor_path: Path,
    pockets: list[P2RankPocket],
    run_directory: Path,
    tool_version: str,
    structure_id: str | None = None,
) -> tuple[list[BindingSite], list[Path]]:
    atoms_by_residue = _pdb_atoms_by_residue(receptor_path)
    prepared_sites: list[tuple[P2RankPocket, Path, list[str], list[float], list[float]]] = []
    for pocket in pockets:
        residue_ids = list(pocket.residue_ids)
        lines = [line for residue_id in residue_ids for line in atoms_by_residue.get(residue_id, [])]
        if not lines:
            raise ValueError(f"P2Rank pocket {pocket.rank} has no matching receptor residues.")
        pocket_path = run_directory / f"pocket_{pocket.rank}.pdb"
        pocket_path.write_text("".join(lines) + "END\n", encoding="utf-8")
        center, size = _grid_from_pocket_atoms(lines)
        residues = _residue_labels(residue_ids, atoms_by_residue)
        prepared_sites.append((pocket, pocket_path, residues, center, size))

    binding_sites: list[BindingSite] = []
    pocket_paths: list[Path] = []
    for pocket, pocket_path, residues, center, size in prepared_sites:
        binding_site_id = new_id("SITE")
        site = BindingSite(
            binding_site_id=binding_site_id,
            project_id=project.project_id,
            target_id=project.target_id or "",
            pdb_id=Path(source_file.filename).stem.upper(),
            source_file_id=source_file.file_id,
            structure_id=structure_id,
            receptor_file=f"local://{receptor_path}",
            prepared_receptor_file=None,
            preparation_status="pocket_predicted",
            key_residues=residues,
            pocket_residues_json=residues,
            pocket_method=f"p2rank_{tool_version}",
            validation_status="predicted_not_experimentally_validated",
            grid_box={
                "center": center,
                "size": size,
                "pocket_file": f"local://{pocket_path}",
                "p2rank_center": pocket.center,
                "p2rank_rank": pocket.rank,
                "p2rank_score": pocket.score,
                "p2rank_probability": pocket.probability,
                "padding_angstrom": GRID_PADDING_ANGSTROM,
                "min_size_angstrom": GRID_MIN_SIZE_ANGSTROM,
                "max_size_angstrom": GRID_MAX_SIZE_ANGSTROM,
                "derivation": "p2rank_residue_bounds_v1",
            },
            preparation_json={
                "adapter_mode": "p2rank_local",
                "labels": ["pocket_predicted", "predicted_not_experimentally_validated"],
                "warnings": ["predicted_not_experimentally_validated"],
                "p2rank": {
                    "name": pocket.name,
                    "rank": pocket.rank,
                    "score": pocket.score,
                    "probability": pocket.probability,
                    "center": pocket.center,
                    "residue_ids": pocket.residue_ids,
                },
            },
        )
        db.add(site)
        binding_sites.append(site)
        pocket_paths.append(pocket_path)
    db.flush()
    return binding_sites, pocket_paths


def _pdb_atoms_by_residue(receptor_path: Path) -> dict[str, list[str]]:
    atoms_by_residue: dict[str, list[str]] = {}
    for line in receptor_path.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True):
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        chain = line[21:22].strip() or "_"
        residue_number = line[22:27].strip()
        if residue_number:
            atoms_by_residue.setdefault(f"{chain}_{residue_number}", []).append(line)
    return atoms_by_residue


def _residue_labels(residue_ids: list[str], atoms_by_residue: dict[str, list[str]]) -> list[str]:
    labels: list[str] = []
    for residue_id in residue_ids:
        atoms = atoms_by_residue.get(residue_id) or []
        residue_name = atoms[0][17:20].strip() if atoms else ""
        chain, _, number = residue_id.partition("_")
        labels.append(f"{chain}:{residue_name}{number}" if residue_name else residue_id)
    return labels


def _grid_from_pocket_atoms(lines: list[str]) -> tuple[list[float], list[float]]:
    coordinates: list[tuple[float, float, float]] = []
    for line in lines:
        try:
            coordinates.append((float(line[30:38]), float(line[38:46]), float(line[46:54])))
        except ValueError:
            continue
    if not coordinates:
        raise ValueError("Pocket PDB has no parseable atom coordinates.")
    minima = [min(point[index] for point in coordinates) for index in range(3)]
    maxima = [max(point[index] for point in coordinates) for index in range(3)]
    center = [round((minimum + maximum) / 2, 4) for minimum, maximum in zip(minima, maxima, strict=True)]
    size = [
        round(max(GRID_MIN_SIZE_ANGSTROM, min(GRID_MAX_SIZE_ANGSTROM, maximum - minimum + 2 * GRID_PADDING_ANGSTROM)), 4)
        for minimum, maximum in zip(minima, maxima, strict=True)
    ]
    return center, size


def _known_run_files(output_directory: Path) -> dict[str, Path]:
    known = {"run_log": output_directory / "run.log", "parameters": output_directory / "params.txt"}
    return {role: path for role, path in known.items() if path.is_file()}


def _link_project_artifacts(
    db: Session,
    project: Project,
    scientific_result: ScientificResult,
    binding_sites: list[BindingSite],
) -> None:
    sites_by_artifact_role = {f"pocket_{site.binding_site_id}": site for site in binding_sites}
    for artifact_role, artifact in scientific_result.output_artifacts.items():
        artifact_id = artifact.get("artifact_id")
        if not artifact_id:
            continue
        site = sites_by_artifact_role.get(artifact_role)
        role = (
            f"p2rank_pocket_{site.binding_site_id}"
            if site
            else f"p2rank_{artifact_role}"
        )
        link = db.query(TargetResourceLink).filter_by(
            target_id=project.target_id, artifact_id=artifact_id, role=role
        ).one_or_none()
        if link is None:
            db.add(
                TargetResourceLink(
                    target_id=project.target_id or "",
                    artifact_id=artifact_id,
                    role=role,
                    binding_site_id=site.binding_site_id if site else None,
                )
            )
        if site is not None:
            site.artifact_id = artifact_id
    for artifact_role, artifact in scientific_result.input_artifacts.items():
        artifact_id = artifact.get("artifact_id")
        if artifact_id and db.query(TargetResourceLink).filter_by(
            target_id=project.target_id, artifact_id=artifact_id, role=f"p2rank_{artifact_role}"
        ).one_or_none() is None:
            db.add(
                TargetResourceLink(
                    target_id=project.target_id or "",
                    artifact_id=artifact_id,
                    role=f"p2rank_{artifact_role}",
                )
            )
    db.flush()


def _persist_failure(
    db: Session,
    snapshot: CapabilitySnapshot,
    request: dict[str, Any],
    project: Project,
    input_path: Path,
    run_directory: Path,
    command: list[str],
    warning: str,
    stderr: str | None,
    exit_code: int | None,
    stdout: str | None = None,
) -> P2RankProjectResult:
    scientific_result = ScientificResult.unavailable(
        stage="pocket_prediction", tool_name="p2rank", status="failed", warnings=[warning]
    )
    scientific_result.input_artifacts = artifact_snapshot({"receptor_pdb": input_path})
    scientific_result.output_artifacts = artifact_snapshot(_known_run_files(run_directory / "output"))
    scientific_result.provenance = {
        "command": command,
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
    }
    manifest = persist_scientific_result(
        db,
        scientific_result,
        snapshot=snapshot,
        request=request,
        project_id=project.project_id,
    )
    return P2RankProjectResult(status="failed", warnings=[warning], manifest_id=manifest.manifest_id)


def _optional_float(value: str | None) -> float | None:
    try:
        return float(value) if value else None
    except ValueError:
        return None
