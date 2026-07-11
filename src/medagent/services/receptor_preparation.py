import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from medagent.core.config import Settings
from medagent.db.models import BindingSite, Project, Target, UploadedFile
from medagent.services.file_ingestion import parse_pdb_summary, path_from_storage_uri, safe_filename
from medagent.services.ids import new_id


@dataclass
class ReceptorPreparationResult:
    binding_site: BindingSite
    warnings: list[str] = field(default_factory=list)
    tool_status: dict[str, Any] = field(default_factory=dict)


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
    return (
        db.query(BindingSite)
        .filter(
            (BindingSite.project_id == project.project_id)
            | ((BindingSite.project_id.is_(None)) & (BindingSite.target_id == project.target_id))
        )
        .order_by(BindingSite.created_at.asc(), BindingSite.id.asc())
        .all()
    )


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


def receptor_preparation_tool_status() -> dict[str, Any]:
    return {
        "obabel": _executable_status("obabel"),
        "mk_prepare_receptor.py": _executable_status("mk_prepare_receptor.py"),
        "prepare_receptor4.py": _executable_status("prepare_receptor4.py"),
    }


def binding_site_to_payload(site: BindingSite) -> dict[str, Any]:
    preparation_json = site.preparation_json or {}
    return {
        "binding_site_id": site.binding_site_id,
        "project_id": site.project_id,
        "target_id": site.target_id,
        "pdb_id": site.pdb_id,
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
    return receptor_reference


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
    if receptor_path.suffix.lower() == ".pdbqt":
        return receptor_path, []

    obabel = tool_status["obabel"].get("path")
    if not obabel:
        return None, ["receptor_pdbqt_preparation_tool_not_installed"]

    output_path = output_dir / f"{receptor_path.stem}.pdbqt"
    command = [str(obabel), f"-i{receptor_path.suffix.lstrip('.')}", str(receptor_path), "-opdbqt", "-O", str(output_path)]
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None, ["receptor_pdbqt_preparation_timeout"]
    except OSError:
        return None, ["receptor_pdbqt_preparation_failed"]

    if completed.returncode == 0 and output_path.exists():
        return output_path, []
    _ = time.perf_counter() - started
    return None, ["receptor_pdbqt_preparation_failed"]


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
    return {"available": path is not None, "path": path}


def _is_vector3(values: list[float] | None) -> bool:
    return values is not None and len(values) == 3


def _local_uri(path: Path | None) -> str | None:
    if path is None:
        return None
    return f"local://{path}"
