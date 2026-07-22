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
from medagent.db.models import BindingSite, Project, Target, UploadedFile
from medagent.services.file_ingestion import parse_pdb_summary, path_from_storage_uri, safe_filename
from medagent.services.ids import new_id
from medagent.services.pdbqt_validation import is_valid_vina_receptor_pdbqt


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
        return receptor_path, []

    obabel = tool_status["obabel"].get("path")
    if not obabel:
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
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired:
        temp_path.unlink(missing_ok=True)
        return None, ["receptor_pdbqt_preparation_timeout"]
    except OSError:
        temp_path.unlink(missing_ok=True)
        return None, ["receptor_pdbqt_preparation_failed"]

    try:
        if completed.returncode != 0:
            return None, ["receptor_pdbqt_preparation_failed"]
        if not is_valid_vina_receptor_pdbqt(temp_path):
            return None, ["receptor_pdbqt_preparation_invalid_rigid_output"]
        temp_path.replace(output_path)
        return output_path, []
    finally:
        temp_path.unlink(missing_ok=True)


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
