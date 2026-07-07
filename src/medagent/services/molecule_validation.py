import re
from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from medagent.db.models import Molecule, MoleculeProperty, Project
from medagent.services.molecule_import import is_lightly_valid_smiles


ATOMIC_WEIGHTS = {
    "B": 10.81,
    "C": 12.011,
    "N": 14.007,
    "O": 15.999,
    "F": 18.998,
    "P": 30.974,
    "S": 32.06,
    "Cl": 35.45,
    "Br": 79.904,
    "I": 126.904,
}

HBA_ELEMENTS = {"N", "O", "S", "F", "Cl", "Br", "I"}


@dataclass
class ValidationSummary:
    validated_count: int = 0
    invalid_count: int = 0
    property_count: int = 0
    invalid_molecule_ids: list[str] = field(default_factory=list)
    validated_molecule_ids: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "validated_count": self.validated_count,
            "invalid_count": self.invalid_count,
            "property_count": self.property_count,
            "validated_molecule_ids": self.validated_molecule_ids,
            "invalid_molecule_ids": self.invalid_molecule_ids,
        }


@dataclass
class ValidationResult:
    valid: bool
    labels: list[str]
    reason: str | None = None
    descriptors: dict | None = None


def validate_project_molecules(db: Session, project: Project) -> dict:
    molecules = db.query(Molecule).filter_by(project_id=project.project_id).order_by(Molecule.id.asc()).all()
    summary = ValidationSummary()

    for molecule in molecules:
        result = validate_smiles_lightweight(molecule.smiles)
        if result.valid:
            molecule.status = "structure_validated"
            molecule.labels = merge_labels(molecule.labels, result.labels)
            upsert_molecule_property(db, molecule, result.descriptors or {})
            summary.validated_count += 1
            summary.property_count += 1
            summary.validated_molecule_ids.append(molecule.molecule_id)
        else:
            molecule.status = "invalid_structure"
            molecule.labels = merge_labels(molecule.labels, result.labels)
            summary.invalid_count += 1
            summary.invalid_molecule_ids.append(molecule.molecule_id)

    db.commit()
    return summary.as_dict()


def validate_smiles_lightweight(smiles: str) -> ValidationResult:
    if not is_lightly_valid_smiles(smiles):
        return ValidationResult(False, ["invalid_smiles"], "basic_smiles_character_check_failed")
    if not paired_parentheses(smiles):
        return ValidationResult(False, ["invalid_smiles", "unbalanced_parentheses"], "unbalanced_parentheses")
    if not paired_brackets(smiles):
        return ValidationResult(False, ["invalid_smiles", "unbalanced_brackets"], "unbalanced_brackets")
    if not paired_ring_digits(smiles):
        return ValidationResult(False, ["invalid_smiles", "unpaired_ring_digit"], "unpaired_ring_digit")

    descriptors = estimate_descriptors(smiles)
    if descriptors["heavy_atom_count"] == 0:
        return ValidationResult(False, ["invalid_smiles", "unsupported_atom_tokens"], "unsupported_atom_tokens")

    return ValidationResult(
        True,
        ["light_validation_passed", "needs_rdkit_validation"],
        descriptors=descriptors,
    )


def upsert_molecule_property(db: Session, molecule: Molecule, descriptors: dict) -> None:
    existing = db.query(MoleculeProperty).filter_by(molecule_id=molecule.molecule_id).one_or_none()
    metadata = {
        "validator": "lightweight_smiles_validator",
        "heavy_atom_count": descriptors["heavy_atom_count"],
        "element_counts": descriptors["element_counts"],
        "validation_run_count": 1,
    }

    if existing is None:
        db.add(
            MoleculeProperty(
                molecule_id=molecule.molecule_id,
                mw=descriptors["mw"],
                logp=None,
                tpsa=None,
                hbd=descriptors["hbd"],
                hba=descriptors["hba"],
                sa_score=None,
                tool_metadata=metadata,
            )
        )
        return

    old_metadata = existing.tool_metadata or {}
    metadata["validation_run_count"] = int(old_metadata.get("validation_run_count", 0)) + 1
    existing.mw = descriptors["mw"]
    existing.hbd = descriptors["hbd"]
    existing.hba = descriptors["hba"]
    existing.tool_metadata = metadata


def estimate_descriptors(smiles: str) -> dict:
    elements = parse_elements(smiles)
    counts = Counter(elements)
    mw = round(sum(ATOMIC_WEIGHTS.get(element, 0.0) for element in elements), 3)
    return {
        "mw": mw,
        "hbd": counts.get("N", 0) + counts.get("O", 0),
        "hba": sum(counts.get(element, 0) for element in HBA_ELEMENTS),
        "heavy_atom_count": len(elements),
        "element_counts": dict(sorted(counts.items())),
    }


def parse_elements(smiles: str) -> list[str]:
    elements = []
    for match in re.finditer(r"Cl|Br|[BCNOFPSI]|[cnosp]", smiles):
        token = match.group(0)
        elements.append(token.capitalize())
    return elements


def paired_parentheses(smiles: str) -> bool:
    depth = 0
    for character in smiles:
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        if depth < 0:
            return False
    return depth == 0


def paired_brackets(smiles: str) -> bool:
    depth = 0
    for character in smiles:
        if character == "[":
            depth += 1
        elif character == "]":
            depth -= 1
        if depth < 0:
            return False
    return depth == 0


def paired_ring_digits(smiles: str) -> bool:
    digits = re.findall(r"(?<!%)\d", smiles)
    two_digit_rings = re.findall(r"%\d{2}", smiles)
    counts = Counter(digits + two_digit_rings)
    return all(count % 2 == 0 for count in counts.values())


def merge_labels(existing: list[str] | None, new_labels: list[str]) -> list[str]:
    merged = []
    for label in [*(existing or []), *new_labels]:
        if label not in merged:
            merged.append(label)
    return merged
