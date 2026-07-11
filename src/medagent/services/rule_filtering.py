from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from medagent.db.models import Molecule, MoleculeProperty, Project, RuleFilterResult
from medagent.services.ids import new_id
from medagent.services.molecule_validation import merge_labels
from medagent.services.rdkit_adapter import find_rdkit_filter_matches


RULE_SET = "basic_drug_likeness_v1"


@dataclass
class RuleFilterSummary:
    evaluated_count: int = 0
    passed_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    result_ids: list[str] = field(default_factory=list)
    passed_molecule_ids: list[str] = field(default_factory=list)
    failed_molecule_ids: list[str] = field(default_factory=list)
    skipped_molecule_ids: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "rule_set": RULE_SET,
            "evaluated_count": self.evaluated_count,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "skipped_count": self.skipped_count,
            "result_ids": self.result_ids,
            "passed_molecule_ids": self.passed_molecule_ids,
            "failed_molecule_ids": self.failed_molecule_ids,
            "skipped_molecule_ids": self.skipped_molecule_ids,
        }


@dataclass
class RuleEvaluation:
    decision: str
    failed_rules: list[str]
    warnings: list[str]
    labels: list[str]
    properties_snapshot: dict[str, Any]
    raw_output: dict[str, Any]


def filter_project_molecules(db: Session, project: Project) -> dict:
    molecules = (
        db.query(Molecule)
        .filter_by(project_id=project.project_id)
        .order_by(Molecule.id.asc())
        .all()
    )
    summary = RuleFilterSummary()

    for molecule in molecules:
        properties = db.query(MoleculeProperty).filter_by(molecule_id=molecule.molecule_id).one_or_none()
        evaluation = evaluate_molecule_rules(molecule, properties)
        result = upsert_rule_filter_result(db, project, molecule, evaluation)
        summary.result_ids.append(result.filter_result_id)

        if evaluation.decision == "passed":
            molecule.status = "passed_filter"
            molecule.labels = merge_labels(molecule.labels, evaluation.labels)
            summary.evaluated_count += 1
            summary.passed_count += 1
            summary.passed_molecule_ids.append(molecule.molecule_id)
        elif evaluation.decision == "failed":
            molecule.status = "failed_filter"
            molecule.labels = merge_labels(molecule.labels, evaluation.labels + evaluation.failed_rules)
            summary.evaluated_count += 1
            summary.failed_count += 1
            summary.failed_molecule_ids.append(molecule.molecule_id)
        else:
            molecule.labels = merge_labels(molecule.labels, evaluation.labels)
            summary.skipped_count += 1
            summary.skipped_molecule_ids.append(molecule.molecule_id)

    db.commit()
    return summary.as_dict()


def evaluate_molecule_rules(
    molecule: Molecule,
    properties: MoleculeProperty | None,
) -> RuleEvaluation:
    if molecule.status == "invalid_structure":
        return RuleEvaluation(
            decision="skipped_invalid_structure",
            failed_rules=[],
            warnings=["structure_validation_failed"],
            labels=["rule_filter_skipped"],
            properties_snapshot={},
            raw_output={"reason": "invalid_structure"},
        )

    if properties is None:
        return RuleEvaluation(
            decision="needs_properties",
            failed_rules=[],
            warnings=["missing_molecule_properties"],
            labels=["rule_filter_needs_properties"],
            properties_snapshot={},
            raw_output={"reason": "missing_molecule_properties"},
        )

    metadata = properties.tool_metadata or {}
    snapshot = {
        "mw": properties.mw,
        "logp": properties.logp,
        "tpsa": properties.tpsa,
        "hbd": properties.hbd,
        "hba": properties.hba,
        "rotatable_bond_count": metadata.get("rotatable_bond_count"),
        "heavy_atom_count": metadata.get("heavy_atom_count"),
        "validator": metadata.get("validator"),
    }
    failed_rules: list[str] = []
    warnings: list[str] = []

    _check_max(snapshot, "mw", 500, "lipinski_mw_gt_500", failed_rules, warnings)
    _check_max(snapshot, "logp", 5, "lipinski_logp_gt_5", failed_rules, warnings)
    _check_max(snapshot, "hbd", 5, "lipinski_hbd_gt_5", failed_rules, warnings)
    _check_max(snapshot, "hba", 10, "lipinski_hba_gt_10", failed_rules, warnings)
    _check_max(snapshot, "tpsa", 140, "veber_tpsa_gt_140", failed_rules, warnings)
    _check_max(
        snapshot,
        "rotatable_bond_count",
        10,
        "veber_rotatable_bonds_gt_10",
        failed_rules,
        warnings,
    )

    catalog_available, catalog_matches = find_rdkit_filter_matches(molecule.smiles)
    if not catalog_available:
        warnings.append("rdkit_filter_catalog_unavailable")
    for match in catalog_matches:
        failed_rules.append(f"rdkit_alert:{match.description}")

    labels = ["rule_filter_evaluated"]
    if warnings:
        labels.append("rule_filter_incomplete")
    if failed_rules:
        labels.append("rule_filter_failed")
    else:
        labels.append("rule_filter_passed")

    return RuleEvaluation(
        decision="failed" if failed_rules else "passed",
        failed_rules=failed_rules,
        warnings=warnings,
        labels=labels,
        properties_snapshot=snapshot,
        raw_output={
            "rule_set": RULE_SET,
            "catalog_available": catalog_available,
            "catalog_matches": [
                {"catalog": match.catalog, "description": match.description}
                for match in catalog_matches
            ],
        },
    )


def upsert_rule_filter_result(
    db: Session,
    project: Project,
    molecule: Molecule,
    evaluation: RuleEvaluation,
) -> RuleFilterResult:
    result = (
        db.query(RuleFilterResult)
        .filter_by(molecule_id=molecule.molecule_id, rule_set=RULE_SET)
        .one_or_none()
    )
    if result is None:
        result = RuleFilterResult(
            filter_result_id=new_id("FILTER"),
            project_id=project.project_id,
            molecule_id=molecule.molecule_id,
            rule_set=RULE_SET,
        )
        db.add(result)

    result.decision = evaluation.decision
    result.failed_rules = evaluation.failed_rules
    result.warnings = evaluation.warnings
    result.labels = evaluation.labels
    result.properties_snapshot = evaluation.properties_snapshot
    result.raw_output = evaluation.raw_output
    return result


def _check_max(
    snapshot: dict[str, Any],
    key: str,
    maximum: float,
    failed_rule: str,
    failed_rules: list[str],
    warnings: list[str],
) -> None:
    value = snapshot.get(key)
    if value is None:
        warnings.append(f"missing_{key}")
        return
    if float(value) > maximum:
        failed_rules.append(failed_rule)
