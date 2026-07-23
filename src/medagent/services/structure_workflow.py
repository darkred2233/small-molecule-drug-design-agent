from __future__ import annotations

import hashlib
import json
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sqlalchemy.orm import Session

from medagent.core.config import Settings
from medagent.db.models import Project, ProjectStructure, Target, UploadedFile
from medagent.services.file_ingestion import parse_pdb_summary, path_from_storage_uri
from medagent.services.ids import new_id


PDB_ID_PATTERN = re.compile(r"^[0-9][A-Za-z0-9]{3}$")
MAX_STRUCTURE_BYTES = 100 * 1024 * 1024


def import_rcsb_structure(
    db: Session,
    settings: Settings,
    project: Project,
    pdb_id: str,
    assembly_id: str | None = None,
) -> ProjectStructure:
    _require_target(db, project)
    if assembly_id is not None:
        raise ValueError("Biological assembly import is not supported yet; omit assembly_id.")
    normalized_id = _normalize_pdb_id(pdb_id)
    existing = _find_structure(db, project.project_id, "rcsb_pdb", normalized_id)
    if existing is not None:
        return _commit_activation(db, project, existing)

    metadata_url = f"https://data.rcsb.org/rest/v1/core/entry/{normalized_id}"
    download_url = f"https://files.rcsb.org/download/{normalized_id}.pdb"
    metadata = _download_json(metadata_url)
    payload, response_metadata = _download_bytes(download_url)
    summary = _validate_pdb_payload(payload)

    structure_id = new_id("STR")
    file_id = new_id("FILE")
    target_path = (
        Path(settings.storage_local_root)
        / project.project_id
        / "structures"
        / structure_id
        / "original"
        / f"{normalized_id}.pdb"
    )
    _atomic_write(target_path, payload)
    digest = hashlib.sha256(payload).hexdigest()
    structure_metadata = {
        "pdb_summary": summary,
        "experimental_method": _first(metadata.get("exptl"), "method"),
        "resolution": _first(metadata.get("rcsb_entry_info", {}).get("resolution_combined")),
        "release_date": metadata.get("rcsb_accession_info", {}).get("initial_release_date"),
        "title": metadata.get("struct", {}).get("title"),
        "collected_at": datetime.now(UTC).isoformat(),
        "response": response_metadata,
        "structure_prediction_fallback": False,
    }
    uploaded = UploadedFile(
        file_id=file_id,
        project_id=project.project_id,
        filename=target_path.name,
        file_type="chemical/x-pdb",
        storage_path=f"local://{target_path}",
        parse_status="parsed",
        metadata_json={
            "storage_backend": "local",
            "source": "rcsb_pdb",
            "source_url": download_url,
            "sha256": digest,
            "size_bytes": len(payload),
            **structure_metadata,
        },
    )
    structure = ProjectStructure(
        structure_id=structure_id,
        project_id=project.project_id,
        target_id=project.target_id or "",
        source="rcsb_pdb",
        source_identifier=normalized_id,
        source_url=download_url,
        assembly_id=assembly_id,
        source_file_id=file_id,
        status="validated",
        metadata_json=structure_metadata,
    )
    db.add_all([uploaded, structure])
    return _commit_activation(db, project, structure)


def register_uploaded_structure(
    db: Session,
    settings: Settings,
    project: Project,
    source_file_id: str,
) -> ProjectStructure:
    _require_target(db, project)
    uploaded = (
        db.query(UploadedFile)
        .filter_by(project_id=project.project_id, file_id=source_file_id)
        .one_or_none()
    )
    if uploaded is None:
        raise ValueError("source_file_id does not belong to this project.")
    source_path = path_from_storage_uri(settings, uploaded.storage_path)
    if source_path.suffix.lower() != ".pdb":
        raise ValueError("Project structures currently require a .pdb file.")
    if not source_path.is_file():
        raise ValueError("Uploaded receptor file does not exist on disk.")
    if source_path.stat().st_size > MAX_STRUCTURE_BYTES:
        raise ValueError("Uploaded structure exceeded the maximum allowed size.")
    payload = source_path.read_bytes()
    summary = _validate_pdb_payload(payload)
    digest = hashlib.sha256(payload).hexdigest()
    existing = _find_structure(db, project.project_id, "upload", source_file_id)
    if existing is None:
        structure_id = new_id("STR")
        snapshot_file_id = new_id("FILE")
        target_path = (
            Path(settings.storage_local_root)
            / project.project_id
            / "structures"
            / structure_id
            / "original"
            / source_path.name
        )
        _atomic_write(target_path, payload)
        snapshot = UploadedFile(
            file_id=snapshot_file_id,
            project_id=project.project_id,
            filename=target_path.name,
            file_type="chemical/x-pdb",
            storage_path=f"local://{target_path}",
            parse_status="parsed",
            metadata_json={
                "storage_backend": "local",
                "source": "upload_snapshot",
                "original_source_file_id": source_file_id,
                "sha256": digest,
                "size_bytes": len(payload),
                "pdb_summary": summary,
            },
        )
        existing = ProjectStructure(
            structure_id=structure_id,
            project_id=project.project_id,
            target_id=project.target_id or "",
            source="upload",
            source_identifier=source_file_id,
            source_url=None,
            source_file_id=snapshot_file_id,
            status="validated",
            metadata_json={
                "pdb_summary": summary,
                "collected_at": datetime.now(UTC).isoformat(),
                "structure_prediction_fallback": False,
            },
        )
        db.add_all([snapshot, existing])
    uploaded.parse_status = "parsed"
    uploaded.metadata_json = {
        **(uploaded.metadata_json or {}),
        "source": "upload",
        "sha256": digest,
        "size_bytes": len(payload),
        "pdb_summary": summary,
    }
    return _commit_activation(db, project, existing)


def list_project_structures(db: Session, project: Project) -> list[ProjectStructure]:
    return (
        db.query(ProjectStructure)
        .filter_by(project_id=project.project_id)
        .order_by(ProjectStructure.created_at.asc(), ProjectStructure.id.asc())
        .all()
    )


def get_project_structure(
    db: Session, project: Project, structure_id: str
) -> ProjectStructure | None:
    return (
        db.query(ProjectStructure)
        .filter_by(project_id=project.project_id, structure_id=structure_id)
        .one_or_none()
    )


def activate_project_structure(
    db: Session, project: Project, structure_id: str
) -> ProjectStructure:
    structure = get_project_structure(db, project, structure_id)
    if structure is None:
        raise ValueError("structure_id does not belong to this project.")
    return _commit_activation(db, project, structure)


def structure_source_file(
    db: Session, settings: Settings, project: Project, structure_id: str
) -> tuple[ProjectStructure, UploadedFile]:
    structure = get_project_structure(db, project, structure_id)
    if structure is None:
        raise ValueError("structure_id does not belong to this project.")
    uploaded = (
        db.query(UploadedFile)
        .filter_by(project_id=project.project_id, file_id=structure.source_file_id)
        .one_or_none()
    )
    if uploaded is None:
        raise ValueError("Structure source artifact is missing.")
    source_path = path_from_storage_uri(settings, uploaded.storage_path)
    expected_hash = (uploaded.metadata_json or {}).get("sha256")
    if not source_path.is_file():
        raise ValueError("Structure source artifact is missing from storage.")
    if not expected_hash or _sha256_file(source_path) != expected_hash:
        raise ValueError("Structure source artifact SHA-256 does not match its registered value.")
    return structure, uploaded


def structure_to_payload(
    db: Session, project: Project, structure: ProjectStructure
) -> dict[str, Any]:
    uploaded = db.query(UploadedFile).filter_by(file_id=structure.source_file_id).one()
    file_metadata = uploaded.metadata_json or {}
    return {
        "structure_id": structure.structure_id,
        "project_id": structure.project_id,
        "target_id": structure.target_id,
        "source": structure.source,
        "source_identifier": structure.source_identifier,
        "source_url": structure.source_url,
        "assembly_id": structure.assembly_id,
        "source_file_id": structure.source_file_id,
        "status": structure.status,
        "sha256": str(file_metadata.get("sha256") or ""),
        "size_bytes": int(file_metadata.get("size_bytes") or 0),
        "metadata": structure.metadata_json or {},
        "is_active": project.active_structure_id == structure.structure_id,
    }


def _require_target(db: Session, project: Project) -> None:
    target = db.query(Target).filter_by(target_id=project.target_id).one_or_none()
    if not project.target_id or target is None:
        raise ValueError("Project target_id must reference a known target.")


def _normalize_pdb_id(pdb_id: str) -> str:
    normalized = pdb_id.strip().upper()
    if not PDB_ID_PATTERN.fullmatch(normalized):
        raise ValueError("pdb_id must be a canonical four-character RCSB PDB identifier.")
    return normalized


def _find_structure(
    db: Session, project_id: str, source: str, source_identifier: str
) -> ProjectStructure | None:
    return (
        db.query(ProjectStructure)
        .filter_by(project_id=project_id, source=source, source_identifier=source_identifier)
        .one_or_none()
    )


def _commit_activation(
    db: Session, project: Project, structure: ProjectStructure
) -> ProjectStructure:
    project.active_structure_id = structure.structure_id
    project.active_binding_site_id = None
    db.add(project)
    db.commit()
    db.refresh(structure)
    return structure


def _download_json(url: str) -> dict[str, Any]:
    payload, _ = _download_bytes(url, accept="application/json")
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError("RCSB metadata response was not valid JSON.") from exc
    if not isinstance(value, dict):
        raise ValueError("RCSB metadata response had an invalid shape.")
    return value


def _download_bytes(url: str, accept: str = "chemical/x-pdb") -> tuple[bytes, dict[str, Any]]:
    request = Request(url, headers={"Accept": accept, "User-Agent": "medagent/0.1"})
    try:
        with urlopen(request, timeout=30) as response:
            headers = response.headers
            chunks: list[bytes] = []
            total_size = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > MAX_STRUCTURE_BYTES:
                    raise ValueError("RCSB structure exceeded the maximum allowed size.")
                chunks.append(chunk)
            payload = b"".join(chunks)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise ValueError(f"RCSB download failed: {exc}") from exc
    return payload, {
        "content_type": headers.get("Content-Type"),
        "etag": headers.get("ETag"),
        "last_modified": headers.get("Last-Modified"),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_pdb_payload(payload: bytes) -> dict[str, Any]:
    if not payload:
        raise ValueError("Structure file is empty.")
    text = payload.decode("utf-8", errors="ignore")
    if not any(line.startswith("ATOM") for line in text.splitlines()):
        raise ValueError("Structure does not contain protein ATOM records.")
    summary = parse_pdb_summary(text)
    if not summary.get("atom_count"):
        raise ValueError("Structure does not contain parseable atoms.")
    return summary


def _atomic_write(target_path: Path, payload: bytes) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target_path.parent, delete=False) as handle:
        handle.write(payload)
        temporary_path = Path(handle.name)
    temporary_path.replace(target_path)


def _first(value: Any, key: str | None = None) -> Any:
    if not isinstance(value, list) or not value:
        return None
    first = value[0]
    if key is not None and isinstance(first, dict):
        return first.get(key)
    return first
