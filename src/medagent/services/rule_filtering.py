from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from medagent.db.models import Molecule, MoleculeProperty, Project, RuleFilterResult
from medagent.services.ids import new_id
from medagent.services.molecule_validation import merge_labels
from medagent.services.rdkit_adapter import find_rdkit_filter_matches


RULE_SET = "target_aware_drug_likeness_v2"
DRUG_LIKENESS_MAXIMA = {
    "mw": (500, "lipinski_mw_gt_500"),
    "logp": (5, "lipinski_logp_gt_5"),
    "hbd": (5, "lipinski_hbd_gt_5"),
    "hba": (10, "lipinski_hba_gt_10"),
    "tpsa": (140, "veber_tpsa_gt_140"),
    "rotatable_bond_count": (10, "veber_rotatable_bonds_gt_10"),
}
PAINS_CATALOGS = {"PAINS_A", "PAINS_B", "PAINS_C"}
BRENK_CATALOG = "BRENK"
CUMULATIVE_DRUG_LIKENESS_RULE = "drug_likeness_violation_count_ge_3"
TARGET_AWARE_WARNING_ALERTS = {
    "TGT-HDAC": {
        "Aliphatic_long_chain",
        "hydroxamic_acid",
        "Oxygen-nitrogen_single_bond",
        "disulphide",
        "isolated_alkene",
        "Michael_acceptor_1",
        "indol_3yl_alk(461)",
    }
}


@dataclass
class RuleFilterSummary:
    evaluated_count: int = 0
    passed_count: int = 0
    failed_count: int = 0
    warning_count: int = 0
    skipped_count: int = 0
    result_ids: list[str] = field(default_factory=list)
    passed_molecule_ids: list[str] = field(default_factory=list)
    failed_molecule_ids: list[str] = field(default_factory=list)
    warning_molecule_ids: list[str] = field(default_factory=list)
    skipped_molecule_ids: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "rule_set": RULE_SET,
            "evaluated_count": self.evaluated_count,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "warning_count": self.warning_count,
            "skipped_count": self.skipped_count,
            "result_ids": self.result_ids,
            "passed_molecule_ids": self.passed_molecule_ids,
            "failed_molecule_ids": self.failed_molecule_ids,
            "warning_molecule_ids": self.warning_molecule_ids,
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
        evaluation = evaluate_molecule_rules(molecule, properties, project)
        result = upsert_rule_filter_result(db, project, molecule, evaluation)
        summary.result_ids.append(result.filter_result_id)

        if evaluation.decision in {"passed", "passed_with_warnings"}:
            molecule.status = "passed_filter"
            molecule.labels = merge_labels(molecule.labels, evaluation.labels)
            summary.evaluated_count += 1
            summary.passed_count += 1
            summary.passed_molecule_ids.append(molecule.molecule_id)
            if evaluation.decision == "passed_with_warnings":
                summary.warning_count += 1
                summary.warning_molecule_ids.append(molecule.molecule_id)
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
    project: Project | None = None,
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

    target_id = project.target_id if project is not None else None
    _check_max(snapshot, "mw", 500, 500, "lipinski_mw_gt_500", failed_rules, warnings)
    _check_max(snapshot, "logp", 5, 5, "lipinski_logp_gt_5", failed_rules, warnings)
    _check_max(snapshot, "hbd", 5, 5, "lipinski_hbd_gt_5", failed_rules, warnings)
    _check_max(snapshot, "hba", 10, 10, "lipinski_hba_gt_10", failed_rules, warnings)
    _check_max(snapshot, "tpsa", 140, 140, "veber_tpsa_gt_140", failed_rules, warnings)
    _check_max(
        snapshot,
        "rotatable_bond_count",
        10,
        10,
        "veber_rotatable_bonds_gt_10",
        failed_rules,
        warnings,
    )
    drug_likeness_violations = _drug_likeness_violations(snapshot)
    if len(drug_likeness_violations) >= 3 and CUMULATIVE_DRUG_LIKENESS_RULE not in failed_rules:
        failed_rules.append(CUMULATIVE_DRUG_LIKENESS_RULE)

    catalog_available, catalog_matches = find_rdkit_filter_matches(molecule.smiles)
    if not catalog_available:
        warnings.append("rdkit_filter_catalog_unavailable")
    for match in catalog_matches:
        _classify_rdkit_alert(target_id, match.catalog, match.description, failed_rules, warnings)

    labels = ["rule_filter_evaluated"]
    if warnings:
        labels.append("rule_filter_warning")
    if failed_rules:
        labels.append("rule_filter_failed")
    elif warnings:
        labels.append("rule_filter_passed_with_warnings")
    else:
        labels.append("rule_filter_passed")

    decision = "failed" if failed_rules else "passed_with_warnings" if warnings else "passed"
    return RuleEvaluation(
        decision=decision,
        failed_rules=failed_rules,
        warnings=warnings,
        labels=labels,
        properties_snapshot=snapshot,
        raw_output={
            "rule_set": RULE_SET,
            "target_id": target_id,
            "catalog_available": catalog_available,
            "drug_likeness_violation_count": len(drug_likeness_violations),
            "drug_likeness_violations": drug_likeness_violations,
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
    hard_maximum: float,
    failed_rule: str,
    failed_rules: list[str],
    warnings: list[str],
) -> None:
    value = snapshot.get(key)
    if value is None:
        warnings.append(f"missing_{key}")
        return
    if float(value) > hard_maximum:
        failed_rules.append(failed_rule)
    elif float(value) > maximum:
        warnings.append(f"warning:{failed_rule}")


def _classify_rdkit_alert(
    target_id: str | None,
    catalog: str,
    description: str,
    failed_rules: list[str],
    warnings: list[str],
) -> None:
    alert = f"rdkit_alert:{catalog}:{description}"
    if catalog in PAINS_CATALOGS:
        failed_rules.append(alert)
        return
    if catalog == BRENK_CATALOG and _is_target_allowed_alert(target_id, description):
        warnings.append(f"target_allowed_{alert}")
        return
    if catalog == BRENK_CATALOG:
        failed_rules.append(alert)
        return
    warnings.append(f"warning:{alert}")


def _is_target_allowed_alert(target_id: str | None, description: str) -> bool:
    allowed = TARGET_AWARE_WARNING_ALERTS.get(target_id or "", set())
    return any(token in description for token in allowed)


def _drug_likeness_violations(snapshot: dict[str, Any]) -> list[str]:
    violations: list[str] = []
    for key, (maximum, rule_name) in DRUG_LIKENESS_MAXIMA.items():
        value = snapshot.get(key)
        if value is None:
            continue
        if float(value) > maximum:
            violations.append(rule_name)
    return violations
