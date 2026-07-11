import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from medagent.db.models import Molecule, Project, SeedLigand
from medagent.services.ids import new_id


SMILES_ALLOWED_PATTERN = re.compile(r"^[A-Za-z0-9@+\-\[\]\(\)=#$\\/%.:]+$")


@dataclass
class MoleculeImportSummary:
    imported_count: int = 0
    duplicate_count: int = 0
    invalid_count: int = 0
    imported_molecule_ids: list[str] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "imported_count": self.imported_count,
            "duplicate_count": self.duplicate_count,
            "invalid_count": self.invalid_count,
            "imported_molecule_ids": self.imported_molecule_ids,
            "skipped": self.skipped,
        }


def import_seed_ligands_as_molecules(db: Session, project: Project) -> dict:
    seed_ligands = (
        db.query(SeedLigand)
        .filter_by(project_id=project.project_id)
        .order_by(SeedLigand.id.asc())
        .all()
    )
    existing_smiles = {
        normalize_smiles(row[0])
        for row in db.query(Molecule.smiles).filter_by(project_id=project.project_id).all()
    }
    seen_in_batch: set[str] = set()
    summary = MoleculeImportSummary()

    for seed_ligand in seed_ligands:
        normalized_smiles = normalize_smiles(seed_ligand.smiles)
        if not is_lightly_valid_smiles(normalized_smiles):
            summary.invalid_count += 1
            summary.skipped.append(
                {
                    "ligand_id": seed_ligand.ligand_id,
                    "reason": "invalid_smiles",
                    "smiles": seed_ligand.smiles,
                }
            )
            continue

        if normalized_smiles in existing_smiles or normalized_smiles in seen_in_batch:
            summary.duplicate_count += 1
            summary.skipped.append(
                {
                    "ligand_id": seed_ligand.ligand_id,
                    "reason": "duplicate_smiles",
                    "smiles": normalized_smiles,
                }
            )
            continue

        molecule = Molecule(
            molecule_id=new_id("MOL"),
            project_id=project.project_id,
            smiles=normalized_smiles,
            inchi_key=None,
            scaffold=None,
            source_agent="seed_ligand_import",
            status="imported_from_seed",
            labels=["seed_ligand", "needs_structure_validation"],
        )
        db.add(molecule)
        db.flush()

        seen_in_batch.add(normalized_smiles)
        summary.imported_count += 1
        summary.imported_molecule_ids.append(molecule.molecule_id)

    db.commit()
    return summary.as_dict()


def normalize_smiles(smiles: str | None) -> str:
    return (smiles or "").strip()


def is_lightly_valid_smiles(smiles: str) -> bool:
    if not smiles:
        return False
    if any(character.isspace() for character in smiles):
        return False
    if "_" in smiles:
        return False
    if not SMILES_ALLOWED_PATTERN.match(smiles):
        return False
    return any(character.isalpha() for character in smiles)
