import hashlib
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from sqlalchemy.orm import Session

from medagent.core.config import Settings
from medagent.db.models import (
    BindingSite,
    Project,
    ScientificArtifact,
    Target,
    UploadedFile,
)
from medagent.services.file_ingestion import parse_pdb_summary, path_from_storage_uri, safe_filename
from medagent.services.ids import new_id
from medagent.services.pdbqt_validation import is_valid_vina_receptor_pdbqt
from medagent.services.autogrow4_resources import eligible_autogrow4_source_count
from medagent.services.scientific_execution import (
    CapabilitySnapshot,
    EvidenceKind,
    EvidenceLevel,
    ScientificResult,
    artifact_snapshot,
)
from medagent.services.scientific_persistence import persist_scientific_result
from medagent.services.structure_workflow import get_project_structure, structure_source_file


@dataclass
class ReceptorPreparationResult:
    binding_site: BindingSite
    warnings: list[str] = field(default_factory=list)
    tool_status: dict[str, Any] = field(default_factory=dict)


def prepare_project_structure_receptor(
    db: Session,
    settings: Settings,
    project: Project,
    structure_id: str,
) -> dict[str, Any]:
    structure, source_file = structure_source_file(db, settings, project, structure_id)
    source_path = path_from_storage_uri(settings, source_file.storage_path)
    output_dir = (
        Path(settings.storage_local_root)
        / project.project_id
        / "structures"
        / structure.structure_id
        / "prepared"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    receptor_path = output_dir / "receptor.pdb"
    if source_path.resolve() != receptor_path.resolve():
        shutil.copy2(source_path, receptor_path)

    tool_status = receptor_preparation_tool_status()
    prepared_path, warnings = _prepare_receptor_for_vina(receptor_path, output_dir, tool_status)
    digest = _sha256_file(prepared_path) if prepared_path is not None else None
    manifest = _persist_structure_preparation_manifest(
        db,
        project,
        structure.structure_id,
        receptor_path,
        prepared_path,
        tool_status,
        warnings,
    )
    structure.prepared_receptor_file = _local_uri(prepared_path) if prepared_path else None
    structure.prepared_receptor_sha256 = digest
    structure.preparation_json = {
        "adapter_mode": "project_structure_receptor_preparation",
        "source_file_id": source_file.file_id,
        "source_sha256": (source_file.metadata_json or {}).get("sha256"),
        "warnings": warnings,
        "tool_status": tool_status,
        "manifest_id": manifest.manifest_id,
    }
    selected = _selected_structure_site(db, project, structure.structure_id)
    structure.status = "ready" if prepared_path is not None and selected is not None else "prepared"
    for site in db.query(BindingSite).filter_by(
        project_id=project.project_id, structure_id=structure.structure_id
    ):
        site.prepared_receptor_file = structure.prepared_receptor_file
        site.preparation_json = {
            **(site.preparation_json or {}),
            "receptor_preparation": structure.preparation_json,
        }
    db.commit()
    db.refresh(structure)
    return {
        "structure_id": structure.structure_id,
        "status": structure.status,
        "prepared_receptor_file": structure.prepared_receptor_file,
        "prepared_receptor_sha256": structure.prepared_receptor_sha256,
        "warnings": warnings,
    }


def select_project_binding_site(
    db: Session,
    settings: Settings,
    project: Project,
    binding_site_id: str,
) -> BindingSite:
    site = (
        db.query(BindingSite)
        .filter_by(project_id=project.project_id, binding_site_id=binding_site_id)
        .one_or_none()
    )
    if site is None:
        raise ValueError("binding_site_id does not belong to this project.")
    if not project.active_structure_id or site.structure_id != project.active_structure_id:
        raise ValueError("binding_site_id was not predicted from the active project structure.")
    grid = site.grid_box or {}
    if not _is_vector3(grid.get("center")) or not _is_vector3(grid.get("size")):
        raise ValueError("binding_site_id does not contain a complete docking grid.")
    pocket_path = _local_path(grid.get("pocket_file"))
    if pocket_path is None or not pocket_path.is_file():
        raise ValueError("binding_site_id does not contain a valid pocket PDB artifact.")
    project.active_binding_site_id = site.binding_site_id
    structure = get_project_structure(db, project, project.active_structure_id)
    if structure is not None and structure.prepared_receptor_file:
        structure.status = "ready"
    db.commit()
    db.refresh(site)
    return site


def project_structure_readiness(
    db: Session,
    settings: Settings,
    project: Project,
) -> dict[str, Any]:
    reasons: list[str] = []
    if not project.active_structure_id:
        return _empty_readiness(["active_structure_required"])
    structure = get_project_structure(db, project, project.active_structure_id)
    if structure is None:
        return _empty_readiness(["active_structure_not_found"])
    source_file = (
        db.query(UploadedFile)
        .filter_by(project_id=project.project_id, file_id=structure.source_file_id)
        .one_or_none()
    )
    source_metadata = source_file.metadata_json or {} if source_file is not None else {}
    source_path = (
        path_from_storage_uri(settings, source_file.storage_path) if source_file is not None else None
    )
    expected_source_hash = source_metadata.get("sha256")
    source_ready = bool(
        source_path
        and source_path.is_file()
        and isinstance(expected_source_hash, str)
        and expected_source_hash
        and _sha256_file(source_path) == expected_source_hash
    )
    if source_path is None or not source_path.is_file():
        reasons.append("source_receptor_missing")
    elif not expected_source_hash:
        reasons.append("source_receptor_hash_missing")
    elif not source_ready:
        reasons.append("source_receptor_hash_mismatch")

    prepared_path = _local_path(structure.prepared_receptor_file)
    prepared_ready = bool(
        prepared_path
        and prepared_path.is_file()
        and structure.prepared_receptor_sha256
        and _sha256_file(prepared_path) == structure.prepared_receptor_sha256
    )
    if not prepared_ready:
        reasons.append("prepared_receptor_required")

    site = _selected_structure_site(db, project, structure.structure_id)
    if site is None:
        reasons.append("binding_site_selection_required")
    grid = site.grid_box if site is not None else {}
    grid_ready = bool(_is_vector3(grid.get("center")) and _is_vector3(grid.get("size")))
    if site is not None and not grid_ready:
        reasons.append("binding_site_grid_required")
    pocket_path = _local_path(grid.get("pocket_file")) if site is not None else None
    pocket_artifact = (
        db.query(ScientificArtifact).filter_by(artifact_id=site.artifact_id).one_or_none()
        if site is not None and site.artifact_id
        else None
    )
    pocket_exists = bool(pocket_path and pocket_path.is_file())
    pocket_ready = bool(
        pocket_exists
        and pocket_artifact is not None
        and pocket_artifact.sha256
        and _sha256_file(pocket_path) == pocket_artifact.sha256
    )
    if site is not None and not pocket_exists:
        reasons.append("pocket_pdb_required")
    elif site is not None and pocket_artifact is None:
        reasons.append("pocket_pdb_hash_missing")
    elif site is not None and not pocket_ready:
        reasons.append("pocket_pdb_hash_mismatch")

    source_compound_count = eligible_autogrow4_source_count(db, project)
    targetdiff_ready = source_ready and pocket_ready
    docking_ready = source_ready and prepared_ready and grid_ready
    autogrow_ready = docking_ready and source_compound_count > 0
    return {
        "ready": source_ready and prepared_ready and pocket_ready and grid_ready,
        "structure_id": structure.structure_id,
        "binding_site_id": site.binding_site_id if site is not None else None,
        "source_receptor": {
            "file_id": source_file.file_id if source_file is not None else None,
            "sha256": source_metadata.get("sha256"),
            "size_bytes": source_metadata.get("size_bytes"),
        },
        "prepared_receptor_pdbqt": (
            {
                "uri": structure.prepared_receptor_file,
                "sha256": structure.prepared_receptor_sha256,
            }
            if prepared_ready
            else None
        ),
        "pocket_pdb": (
            {"uri": grid.get("pocket_file"), "sha256": pocket_artifact.sha256}
            if pocket_ready and pocket_path is not None
            else None
        ),
        "grid": {"center": grid.get("center"), "size": grid.get("size")} if grid_ready else None,
        "tools": {
            "targetdiff": {"ready": targetdiff_ready},
            "autogrow4": {
                "ready": autogrow_ready,
                "source_compound_count": source_compound_count,
                "reason_codes": []
                if autogrow_ready
                else ["receptor_grid_and_source_compounds_required"],
            },
            "vina": {"ready": docking_ready},
            "gnina": {"ready": docking_ready},
        },
        "reason_codes": reasons,
    }


def prepare_project_receptor(
    db: Session,
    settings: Settings,
    project: Project,
    source_file_id: str | None = None,
    receptor_file: str | None = None,
    binding_site_id: str | None = None,
    pdb_id: str | None = None,
    grid_center: list[float] | None = None,
    grid_size: list[float] | None = None,
    key_residues: list[str] | None = None,
    prepare_for_vina: bool = True,
) -> ReceptorPreparationResult:
    if not project.target_id:
        raise ValueError("Project target_id is required before preparing a receptor.")
    if db.query(Target).filter_by(target_id=project.target_id).one_or_none() is None:
        raise ValueError("Project target_id does not match a known target.")
    if not _is_vector3(grid_center) or not _is_vector3(grid_size):
        raise ValueError("grid_center and grid_size must both contain exactly 3 numbers.")

    source_path, source_file = _resolve_source_receptor(
        db,
        settings,
        project,
        source_file_id=source_file_id,
        receptor_file=receptor_file,
    )
    site = _get_or_create_binding_site(
        db,
        project,
        binding_site_id=binding_site_id,
        pdb_id=pdb_id or Path(source_path).stem.upper(),
    )
    receptor_path = _copy_receptor_asset(settings, project.project_id, site.binding_site_id, source_path)
    warnings: list[str] = []
    prepared_path: Path | None = None
    tool_status = receptor_preparation_tool_status()
    if prepare_for_vina:
        prepared_path, vina_warnings = _prepare_receptor_for_vina(
            receptor_path,
            receptor_path.parent,
            tool_status,
        )
        warnings.extend(vina_warnings)

    pdb_summary = _summarize_receptor(receptor_path)
    labels = _preparation_labels(receptor_path, prepared_path, warnings)
    status = "prepared" if not warnings else "prepared_with_warnings"
    if prepare_for_vina and prepared_path is None:
        status = "prepared_with_warnings"

    site.project_id = project.project_id
    site.target_id = project.target_id
    site.pdb_id = pdb_id or Path(source_path).stem.upper()
    site.source_file_id = source_file.file_id if source_file is not None else None
    site.receptor_file = _local_uri(receptor_path)
    site.prepared_receptor_file = _local_uri(prepared_path) if prepared_path else None
    site.preparation_status = status
    site.key_residues = key_residues or []
    site.grid_box = {
        "center": [float(value) for value in grid_center or []],
        "size": [float(value) for value in grid_size or []],
        "source_file_id": source_file.file_id if source_file is not None else None,
        "source_filename": source_file.filename if source_file is not None else Path(source_path).name,
        "receptor_file": site.receptor_file,
        "prepared_receptor_file": site.prepared_receptor_file,
        "parser": "receptor_preparation",
        "pdb_summary": pdb_summary,
    }
    site.preparation_json = {
        "adapter_mode": "project_receptor_preparation",
        "prepare_for_vina": prepare_for_vina,
        "labels": labels,
        "warnings": warnings,
        "tool_status": tool_status,
    }
    db.commit()
    db.refresh(site)
    return ReceptorPreparationResult(binding_site=site, warnings=warnings, tool_status=tool_status)


def list_project_binding_sites(db: Session, project: Project) -> list[BindingSite]:
    project_sites = (
        db.query(BindingSite)
        .filter_by(project_id=project.project_id)
        .order_by(BindingSite.created_at.asc(), BindingSite.id.asc())
        .all()
    )
    target_sites = (
        db.query(BindingSite)
        .filter(BindingSite.project_id.is_(None), BindingSite.target_id == project.target_id)
        .order_by(BindingSite.created_at.asc(), BindingSite.id.asc())
        .all()
        if project.target_id
        else []
    )
    by_id: dict[str, BindingSite] = {}
    for site in project_sites + target_sites:
        by_id.setdefault(site.binding_site_id, site)
    return list(by_id.values())


def get_project_binding_site(
    db: Session,
    project: Project,
    binding_site_id: str,
) -> BindingSite | None:
    site = db.query(BindingSite).filter_by(binding_site_id=binding_site_id).one_or_none()
    if site is None:
        return None
    if site.project_id and site.project_id != project.project_id:
        return None
    if not site.project_id and site.target_id != project.target_id:
        return None
    return site


def project_docking_config(
    db: Session,
    project: Project,
    binding_site_id: str | None = None,
    path_resolver: Callable[[str | None], str | None] | None = None,
) -> dict[str, Any]:
    if binding_site_id:
        site = get_project_binding_site(db, project, binding_site_id)
        if (
            site is not None
            and project.active_structure_id
            and site.structure_id != project.active_structure_id
        ):
            site = None
    elif project.active_structure_id:
        site = None
    else:
        sites = list_project_binding_sites(db, project)
        site = _first_site_with_docking_config(sites)
    if site is None:
        return {}

    grid_box = site.grid_box or {}
    raw_receptor_reference = site.receptor_file or grid_box.get("receptor_file")
    prepared_receptor_reference = (
        site.prepared_receptor_file
        or grid_box.get("prepared_receptor_file")
    )
    receptor_reference = prepared_receptor_reference or raw_receptor_reference
    resolver = path_resolver or resolve_receptor_path
    return {
        "binding_site_id": site.binding_site_id,
        "protein_file": resolver(receptor_reference),
        "raw_receptor_file": resolver(raw_receptor_reference),
        "prepared_receptor_file": resolver(prepared_receptor_reference),
        "grid_center": grid_box.get("center") or grid_box.get("grid_center"),
        "grid_size": grid_box.get("size") or grid_box.get("grid_size"),
        "key_residues": site.key_residues or [],
    }


def _first_site_with_docking_config(sites: list[BindingSite]) -> BindingSite | None:
    fallback: BindingSite | None = None
    for site in sites:
        if fallback is None:
            fallback = site
        grid_box = site.grid_box or {}
        has_receptor = bool(
            site.prepared_receptor_file
            or site.receptor_file
            or grid_box.get("prepared_receptor_file")
            or grid_box.get("receptor_file")
        )
        has_grid = bool(grid_box.get("center") or grid_box.get("grid_center")) and bool(
            grid_box.get("size") or grid_box.get("grid_size")
        )
        if has_receptor and has_grid:
            return site
    return fallback


def receptor_preparation_tool_status() -> dict[str, Any]:
    return {
        "obabel": _executable_status("obabel"),
        "mk_prepare_receptor.py": _executable_status("mk_prepare_receptor.py"),
        "prepare_receptor4.py": _executable_status("prepare_receptor4.py"),
    }


def binding_site_to_payload(site: BindingSite) -> dict[str, Any]:
    preparation_json = site.preparation_json or {}
    grid_box = site.grid_box or {}
    return {
        "binding_site_id": site.binding_site_id,
        "structure_id": site.structure_id,
        "project_id": site.project_id,
        "target_id": site.target_id,
        "pdb_id": site.pdb_id,
        "site_name": grid_box.get("site_name"),
        "reference_ligand": grid_box.get("reference_ligand"),
        "source_url": grid_box.get("source_url"),
        "source_file_id": site.source_file_id,
        "receptor_file": site.receptor_file,
        "prepared_receptor_file": site.prepared_receptor_file,
        "preparation_status": site.preparation_status,
        "key_residues": site.key_residues or [],
        "grid_box": site.grid_box or {},
        "labels": preparation_json.get("labels", []),
        "warnings": preparation_json.get("warnings", []),
        "tool_status": preparation_json.get("tool_status", {}),
    }


def resolve_receptor_path(receptor_reference: str | None) -> str | None:
    if not receptor_reference:
        return None
    if receptor_reference.startswith("local://"):
        return receptor_reference.removeprefix("local://")
    if receptor_reference.startswith(("http://", "https://")):
        cached_path = _resolve_remote_receptor_path(receptor_reference)
        return str(cached_path) if cached_path is not None else receptor_reference
    return receptor_reference


def _resolve_remote_receptor_path(receptor_reference: str) -> Path | None:
    pdb_id = _extract_rcsb_pdb_id(receptor_reference)
    if not pdb_id:
        return None
    cache_dir = Path(".local") / "receptors" / "rcsb"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{pdb_id}.pdb"
    if cache_path.exists() and cache_path.stat().st_size > 0:
        return cache_path

    download_url = f"https://files.rcsb.org/download/{pdb_id}.pdb"
    try:
        with urlopen(download_url, timeout=30) as response:
            payload = response.read()
    except (HTTPError, URLError, TimeoutError, OSError):
        return None
    if not payload or b"ATOM" not in payload and b"HETATM" not in payload:
        return None
    cache_path.write_bytes(payload)
    return cache_path


def _extract_rcsb_pdb_id(receptor_reference: str) -> str | None:
    cleaned = receptor_reference.strip().rstrip("/")
    if "rcsb.org/structure/" in cleaned:
        pdb_id = cleaned.rsplit("/", 1)[-1]
    elif "files.rcsb.org/download/" in cleaned:
        pdb_id = Path(cleaned.rsplit("/", 1)[-1]).stem
    else:
        return None
    pdb_id = pdb_id.upper()
    if len(pdb_id) == 4 and pdb_id.isalnum():
        return pdb_id
    return None


def _resolve_source_receptor(
    db: Session,
    settings: Settings,
    project: Project,
    source_file_id: str | None,
    receptor_file: str | None,
) -> tuple[Path, UploadedFile | None]:
    if source_file_id:
        uploaded_file = (
            db.query(UploadedFile)
            .filter_by(project_id=project.project_id, file_id=source_file_id)
            .one_or_none()
        )
        if uploaded_file is None:
            raise ValueError("source_file_id does not belong to this project.")
        source_path = path_from_storage_uri(settings, uploaded_file.storage_path)
        if not source_path.exists():
            raise ValueError("Uploaded receptor file does not exist on disk.")
        return source_path, uploaded_file

    if receptor_file:
        source_path = Path(resolve_receptor_path(receptor_file) or receptor_file)
        if not source_path.exists():
            raise ValueError("receptor_file does not exist on disk.")
        return source_path, None

    raise ValueError("Either source_file_id or receptor_file is required.")


def _get_or_create_binding_site(
    db: Session,
    project: Project,
    binding_site_id: str | None,
    pdb_id: str,
) -> BindingSite:
    if binding_site_id:
        site = db.query(BindingSite).filter_by(binding_site_id=binding_site_id).one_or_none()
        if site is None:
            raise ValueError("binding_site_id was not found.")
        if site.project_id and site.project_id != project.project_id:
            raise ValueError("binding_site_id does not belong to this project.")
        return site

    site = BindingSite(
        binding_site_id=new_id("SITE"),
        project_id=project.project_id,
        target_id=project.target_id or "",
        pdb_id=pdb_id,
        key_residues=[],
        grid_box={},
        preparation_json={},
    )
    db.add(site)
    db.flush()
    return site


def _copy_receptor_asset(
    settings: Settings,
    project_id: str,
    binding_site_id: str,
    source_path: Path,
) -> Path:
    target_dir = Path(settings.storage_local_root) / project_id / "receptors" / binding_site_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / safe_filename(source_path.name)
    if source_path.resolve() != target_path.resolve():
        shutil.copy2(source_path, target_path)
    return target_path


def _prepare_receptor_for_vina(
    receptor_path: Path,
    output_dir: Path,
    tool_status: dict[str, Any],
) -> tuple[Path | None, list[str]]:
    if is_valid_vina_receptor_pdbqt(receptor_path):
        tool_status["execution"] = {
            "adapter_mode": "existing_pdbqt",
            "command": [],
            "input_file": str(receptor_path),
            "output_file": str(receptor_path),
            "exit_code": 0,
        }
        return receptor_path, []

    obabel = tool_status["obabel"].get("path")
    if not obabel:
        tool_status["execution"] = {
            "adapter_mode": "unavailable",
            "command": [],
            "input_file": str(receptor_path),
            "output_file": None,
            "exit_code": None,
        }
        return None, ["receptor_pdbqt_preparation_tool_not_installed"]

    output_path = output_dir / f"{receptor_path.stem}.pdbqt"
    temp_handle = tempfile.NamedTemporaryFile(
        prefix=f".{receptor_path.stem}.",
        suffix=".pdbqt",
        dir=output_dir,
        delete=False,
    )
    temp_path = Path(temp_handle.name)
    temp_handle.close()
    temp_path.unlink(missing_ok=True)
    command = [
        str(obabel),
        f"-i{receptor_path.suffix.lstrip('.')}",
        str(receptor_path),
        "-opdbqt",
        "-O",
        str(temp_path),
        "-xr",
    ]
    execution = {
        "adapter_mode": "openbabel_rigid_receptor",
        "command": command,
        "input_file": str(receptor_path),
        "output_file": str(output_path),
        "exit_code": None,
        "stdout": None,
        "stderr": None,
    }
    tool_status["execution"] = execution
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired:
        execution["stderr"] = "Open Babel receptor preparation timed out."
        temp_path.unlink(missing_ok=True)
        return None, ["receptor_pdbqt_preparation_timeout"]
    except OSError:
        execution["stderr"] = "Open Babel receptor preparation could not be started."
        temp_path.unlink(missing_ok=True)
        return None, ["receptor_pdbqt_preparation_failed"]

    execution.update(
        {
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    )
    try:
        if completed.returncode != 0:
            return None, ["receptor_pdbqt_preparation_failed"]
        if not is_valid_vina_receptor_pdbqt(temp_path):
            return None, ["receptor_pdbqt_preparation_invalid_rigid_output"]
        temp_path.replace(output_path)
        return output_path, []
    finally:
        temp_path.unlink(missing_ok=True)


def _persist_structure_preparation_manifest(
    db: Session,
    project: Project,
    structure_id: str,
    receptor_path: Path,
    prepared_path: Path | None,
    tool_status: dict[str, Any],
    warnings: list[str],
):
    execution = dict(tool_status.get("execution") or {})
    obabel_status = dict(tool_status.get("obabel") or {})
    snapshot = CapabilitySnapshot.create(
        tools={"receptor_preparation": tool_status},
        runtime={"adapter_mode": execution.get("adapter_mode")},
    )
    if prepared_path is None:
        result = ScientificResult.unavailable(
            stage="receptor_preparation",
            tool_name="openbabel",
            status="blocked",
            warnings=warnings,
        )
    else:
        result = ScientificResult(
            stage="receptor_preparation",
            status="succeeded",
            evidence_level=EvidenceLevel.L2,
            evidence_kind=EvidenceKind.COMPUTATIONAL,
            execution_mode=str(execution.get("adapter_mode") or "receptor_preparation"),
            tool_name="openbabel",
            tool_version=obabel_status.get("version"),
            warnings=warnings,
            parameters={"rigid_receptor": True},
        )
    result.input_artifacts = artifact_snapshot({"source_receptor_pdb": receptor_path})
    result.output_artifacts = artifact_snapshot(
        {"prepared_receptor_pdbqt": prepared_path}
    )
    result.provenance = execution
    return persist_scientific_result(
        db,
        result,
        snapshot=snapshot,
        request={
            "structure_id": structure_id,
            "source_receptor_sha256": _sha256_file(receptor_path),
        },
        project_id=project.project_id,
    )


def _summarize_receptor(receptor_path: Path) -> dict[str, Any]:
    if receptor_path.suffix.lower() not in {".pdb", ".pdbqt"}:
        return {"parser": "unsupported_receptor_summary", "filename": receptor_path.name}
    return parse_pdb_summary(receptor_path.read_text(encoding="utf-8", errors="ignore"))


def _preparation_labels(
    receptor_path: Path,
    prepared_path: Path | None,
    warnings: list[str],
) -> list[str]:
    labels = ["receptor_registered", "binding_site_grid_defined"]
    if receptor_path.suffix.lower() == ".pdbqt" or prepared_path is not None:
        labels.append("vina_receptor_ready")
    else:
        labels.append("vina_receptor_pending")
    if warnings:
        labels.append("receptor_preparation_warning")
    return labels


def _executable_status(command: str) -> dict[str, Any]:
    path = shutil.which(command)
    status: dict[str, Any] = {"available": path is not None, "path": path, "version": None}
    if command != "obabel" or path is None:
        return status
    try:
        process = subprocess.Popen(
            [path, "-V"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        version_output, _ = process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        return status
    except OSError:
        return status
    version_output = version_output.strip()
    status["version"] = version_output.splitlines()[0] if version_output else None
    return status


def _is_vector3(values: list[float] | None) -> bool:
    return values is not None and len(values) == 3


def _local_uri(path: Path | None) -> str | None:
    if path is None:
        return None
    return f"local://{path}"


def _local_path(uri: str | None) -> Path | None:
    if not uri:
        return None
    if uri.startswith("local://"):
        return Path(uri.removeprefix("local://"))
    return Path(uri)


def _sha256_file(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _selected_structure_site(
    db: Session, project: Project, structure_id: str
) -> BindingSite | None:
    if not project.active_binding_site_id:
        return None
    return (
        db.query(BindingSite)
        .filter_by(
            project_id=project.project_id,
            structure_id=structure_id,
            binding_site_id=project.active_binding_site_id,
        )
        .one_or_none()
    )


def _empty_readiness(reason_codes: list[str]) -> dict[str, Any]:
    return {
        "ready": False,
        "structure_id": None,
        "binding_site_id": None,
        "source_receptor": None,
        "prepared_receptor_pdbqt": None,
        "pocket_pdb": None,
        "grid": None,
        "tools": {
            name: {"ready": False}
            for name in ("targetdiff", "autogrow4", "vina", "gnina")
        },
        "reason_codes": reason_codes,
    }
