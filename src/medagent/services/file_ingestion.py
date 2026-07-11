import csv
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from sqlalchemy.orm import Session

from medagent.core.config import Settings
from medagent.db.models import BindingSite, Project, SeedLigand, Target, UploadedFile
from medagent.services.ids import new_id


@dataclass
class ParsedLigand:
    smiles: str
    name: str | None = None
    activity_value: float | None = None
    activity_unit: str | None = None


@dataclass
class ParseOutcome:
    status: str
    metadata: dict = field(default_factory=dict)
    seed_ligand_count: int = 0
    error_message: str | None = None


def save_upload_file(
    settings: Settings,
    project_id: str,
    file_id: str,
    filename: str,
    stream: BinaryIO,
) -> Path:
    safe_name = safe_filename(filename)
    target_dir = Path(settings.storage_local_root) / project_id / file_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / safe_name
    with target_path.open("wb") as output:
        shutil.copyfileobj(stream, output)
    return target_path


def parse_pending_project_files(db: Session, settings: Settings, project: Project) -> dict:
    files = (
        db.query(UploadedFile)
        .filter(
            UploadedFile.project_id == project.project_id,
            UploadedFile.parse_status.in_(["uploaded", "failed"]),
        )
        .order_by(UploadedFile.created_at.asc())
        .all()
    )
    parsed_files = 0
    failed_files = 0
    seed_ligands_created = 0
    details = []

    for uploaded_file in files:
        outcome = parse_uploaded_file(db, settings, project, uploaded_file)
        if outcome.status == "parsed":
            parsed_files += 1
        else:
            failed_files += 1
        seed_ligands_created += outcome.seed_ligand_count
        details.append(
            {
                "file_id": uploaded_file.file_id,
                "filename": uploaded_file.filename,
                "status": outcome.status,
                "seed_ligand_count": outcome.seed_ligand_count,
                "error_message": outcome.error_message,
            }
        )

    db.commit()
    return {
        "parsed_files": parsed_files,
        "failed_files": failed_files,
        "seed_ligands_created": seed_ligands_created,
        "details": details,
    }


def parse_single_file(db: Session, settings: Settings, project: Project, uploaded_file: UploadedFile) -> dict:
    outcome = parse_uploaded_file(db, settings, project, uploaded_file)
    db.commit()
    return {
        "file_id": uploaded_file.file_id,
        "filename": uploaded_file.filename,
        "status": outcome.status,
        "seed_ligand_count": outcome.seed_ligand_count,
        "error_message": outcome.error_message,
        "metadata": outcome.metadata,
    }


def parse_uploaded_file(
    db: Session,
    settings: Settings,
    project: Project,
    uploaded_file: UploadedFile,
) -> ParseOutcome:
    path = path_from_storage_uri(settings, uploaded_file.storage_path)
    delete_previous_parse_records(db, uploaded_file.file_id)

    try:
        outcome = parse_file_content(db, project, uploaded_file, path)
    except Exception as exc:
        uploaded_file.parse_status = "failed"
        uploaded_file.metadata_json = {
            **(uploaded_file.metadata_json or {}),
            "error_message": str(exc),
            "record_count": 0,
            "seed_ligand_count": 0,
        }
        return ParseOutcome(status="failed", metadata=uploaded_file.metadata_json, error_message=str(exc))

    uploaded_file.parse_status = outcome.status
    uploaded_file.metadata_json = {
        **(uploaded_file.metadata_json or {}),
        **outcome.metadata,
        "record_count": outcome.metadata.get("record_count", outcome.seed_ligand_count),
        "seed_ligand_count": outcome.seed_ligand_count,
        "error_message": outcome.error_message,
    }
    return outcome


def parse_file_content(
    db: Session,
    project: Project,
    uploaded_file: UploadedFile,
    path: Path,
) -> ParseOutcome:
    suffix = path.suffix.lower()
    if suffix in {".smi", ".smiles"}:
        ligands = parse_smiles_text(path.read_text(encoding="utf-8", errors="ignore"))
        count = create_seed_ligands(db, project, uploaded_file, ligands)
        return ParseOutcome(
            status="parsed",
            seed_ligand_count=count,
            metadata={"parser": "smiles_text", "record_count": len(ligands)},
        )

    if suffix in {".txt", ".md", ".markdown", ".pdf", ".html", ".htm", ".docx"}:
        return ParseOutcome(
            status="parsed",
            metadata={"parser": "rag_text", "record_count": 0, "rag_eligible": True},
        )

    if suffix == ".csv":
        ligands = parse_csv_ligands(path.read_text(encoding="utf-8-sig", errors="ignore"))
        count = create_seed_ligands(db, project, uploaded_file, ligands)
        return ParseOutcome(
            status="parsed",
            seed_ligand_count=count,
            metadata={"parser": "csv_ligands", "record_count": len(ligands)},
        )

    if suffix == ".sdf":
        ligands = parse_sdf_ligands(path.read_text(encoding="utf-8", errors="ignore"))
        count = create_seed_ligands(db, project, uploaded_file, ligands)
        return ParseOutcome(
            status="parsed",
            seed_ligand_count=count,
            metadata={"parser": "sdf_ligands", "record_count": len(ligands)},
        )

    if suffix == ".pdb":
        pdb_summary = parse_pdb_summary(path.read_text(encoding="utf-8", errors="ignore"))
        binding_site_created = create_binding_site_if_possible(db, project, uploaded_file, pdb_summary)
        return ParseOutcome(
            status="parsed",
            metadata={
                "parser": "pdb_summary",
                "record_count": 1,
                "pdb": pdb_summary,
                "binding_site_created": binding_site_created,
            },
        )

    return ParseOutcome(
        status="failed",
        metadata={"parser": "unsupported", "record_count": 0},
        error_message=f"Unsupported file type: {suffix or 'unknown'}",
    )


def parse_smiles_text(text: str) -> list[ParsedLigand]:
    ligands = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        smiles = parts[0]
        name = " ".join(parts[1:]) if len(parts) > 1 else None
        ligands.append(ParsedLigand(smiles=smiles, name=name))
    return ligands


def parse_csv_ligands(text: str) -> list[ParsedLigand]:
    rows = csv.DictReader(text.splitlines())
    ligands = []
    for row in rows:
        smiles = first_present(row, ["smiles", "SMILES", "canonical_smiles", "CanonicalSMILES"])
        if not smiles:
            continue
        activity_value = parse_float(first_present(row, ["activity_value", "activity", "IC50", "Ki", "Kd"]))
        ligands.append(
            ParsedLigand(
                smiles=smiles,
                name=first_present(row, ["name", "Name", "compound", "compound_id"]),
                activity_value=activity_value,
                activity_unit=first_present(row, ["activity_unit", "unit", "Unit"]),
            )
        )
    return ligands


def parse_sdf_ligands(text: str) -> list[ParsedLigand]:
    ligands = []
    for record in text.split("$$$$"):
        lines = [line.rstrip() for line in record.splitlines()]
        if not any(line.strip() for line in lines):
            continue
        name = next((line.strip() for line in lines if line.strip()), None)
        properties = parse_sdf_properties(lines)
        smiles = (
            properties.get("SMILES")
            or properties.get("smiles")
            or properties.get("CanonicalSMILES")
            or properties.get("canonical_smiles")
        )
        if smiles:
            ligands.append(ParsedLigand(smiles=smiles, name=name))
    return ligands


def parse_sdf_properties(lines: list[str]) -> dict[str, str]:
    properties = {}
    index = 0
    while index < len(lines):
        match = re.match(r">\s+<([^>]+)>", lines[index])
        if match and index + 1 < len(lines):
            properties[match.group(1)] = lines[index + 1].strip()
            index += 2
            continue
        index += 1
    return properties


def parse_pdb_summary(text: str) -> dict:
    atom_count = 0
    residues = set()
    chain_ids = set()
    titles = []

    for line in text.splitlines():
        if line.startswith("TITLE"):
            titles.append(line[10:].strip())
        if line.startswith(("ATOM", "HETATM")):
            atom_count += 1
            chain_id = line[21:22].strip()
            residue_name = line[17:20].strip()
            residue_number = line[22:26].strip()
            if chain_id:
                chain_ids.add(chain_id)
            if residue_name and residue_number:
                residues.add(f"{chain_id}:{residue_name}{residue_number}")

    return {
        "title": " ".join(titles) or None,
        "atom_count": atom_count,
        "residue_count": len(residues),
        "chain_ids": sorted(chain_ids),
    }


def create_seed_ligands(
    db: Session,
    project: Project,
    uploaded_file: UploadedFile,
    ligands: list[ParsedLigand],
) -> int:
    for ligand in ligands:
        db.add(
            SeedLigand(
                ligand_id=new_id("LIG"),
                project_id=project.project_id,
                target_id=project.target_id,
                name=ligand.name,
                smiles=ligand.smiles,
                activity_value=ligand.activity_value,
                activity_unit=ligand.activity_unit,
                source=uploaded_file.file_id,
            )
        )
    return len(ligands)


def create_binding_site_if_possible(
    db: Session,
    project: Project,
    uploaded_file: UploadedFile,
    pdb_summary: dict,
) -> bool:
    if not project.target_id:
        return False
    target_exists = db.query(Target).filter_by(target_id=project.target_id).one_or_none()
    if target_exists is None:
        return False

    existing_site = next(
        (
            site
            for site in db.query(BindingSite).filter_by(target_id=project.target_id).all()
            if (site.grid_box or {}).get("source_file_id") == uploaded_file.file_id
        ),
        None,
    )
    if existing_site is None:
        existing_site = BindingSite(
            binding_site_id=new_id("SITE"),
            project_id=project.project_id,
            target_id=project.target_id,
            pdb_id=Path(uploaded_file.filename).stem.upper(),
            source_file_id=uploaded_file.file_id,
            receptor_file=uploaded_file.storage_path,
            prepared_receptor_file=None,
            preparation_status="uploaded",
            key_residues=[],
            grid_box={},
            preparation_json={},
        )
        db.add(existing_site)

    previous_grid_box = existing_site.grid_box or {}
    previous_preparation = existing_site.preparation_json or {}
    existing_site.project_id = project.project_id
    existing_site.pdb_id = Path(uploaded_file.filename).stem.upper()
    existing_site.source_file_id = uploaded_file.file_id
    if not existing_site.receptor_file:
        existing_site.receptor_file = uploaded_file.storage_path
    if not previous_grid_box.get("center") or not previous_grid_box.get("size"):
        existing_site.preparation_status = "uploaded"
        existing_site.preparation_json = {
            "adapter_mode": "pdb_summary_ingestion",
            "labels": ["receptor_uploaded", "binding_site_grid_pending"],
            "warnings": ["binding_site_grid_not_defined"],
        }
    else:
        existing_site.preparation_json = {
            **previous_preparation,
            "pdb_summary_refreshed": True,
        }
    existing_site.grid_box = {
        **previous_grid_box,
        "source_file_id": uploaded_file.file_id,
        "source_filename": uploaded_file.filename,
        "receptor_file": existing_site.receptor_file,
        "parser": previous_grid_box.get("parser", "pdb_summary"),
        "pdb_summary": pdb_summary,
    }
    return True


def delete_previous_parse_records(db: Session, file_id: str) -> None:
    db.query(SeedLigand).filter_by(source=file_id).delete()


def path_from_storage_uri(settings: Settings, storage_path: str) -> Path:
    if storage_path.startswith("local://"):
        return Path(storage_path.removeprefix("local://"))
    return Path(settings.storage_local_root) / storage_path


def safe_filename(filename: str) -> str:
    name = Path(filename or "uploaded-file").name
    return re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+", "_", name)


def first_present(row: dict[str, str], keys: list[str]) -> str | None:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None
