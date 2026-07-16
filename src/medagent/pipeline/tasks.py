"""
Prefect task definitions for pipeline orchestration.

This module wraps each Agent operation as a Prefect task with:
- Automatic retry on transient failures
- Checkpoint saving for recovery
- Batch processing support
- Task-level logging
"""

from typing import Any

from sqlalchemy.orm import Session

from medagent.configs.settings import Settings
from medagent.db.models import Project


# Task definitions - these would be decorated with @task when Prefect is enabled
# For now, they are plain functions that can be called directly


def knowledge_ingestion_task(
    db: Session,
    settings: Settings,
    project: Project,
) -> dict[str, Any]:
    """
    Knowledge Ingestion Agent task.

    Parses uploaded files and builds RAG index.
    Retry: 2 times with exponential backoff.
    """
    from medagent.services.file_ingestion import parse_pending_project_files
    from medagent.services.rag import build_project_rag_index

    file_ingestion = parse_pending_project_files(db, settings, project)
    rag_index = build_project_rag_index(
        db,
        settings,
        project,
        include_builtin_target=True,
        include_uploads=True,
        rebuild=True,
    )
    return {
        "file_ingestion": file_ingestion,
        "rag_index": rag_index,
    }


def molecule_import_task(
    db: Session,
    project: Project,
) -> dict[str, Any]:
    """
    Molecule Import Agent task.

    Imports seed ligands as candidate molecules.
    Retry: 1 time.
    """
    from medagent.services.molecule_import import import_seed_ligands_as_molecules

    return import_seed_ligands_as_molecules(db, project)


def molecule_generation_task(
    db: Session,
    project: Project,
    generation_size: int = 3,
    strategies: list[str] | None = None,
    strategy_counts: dict[str, int] | None = None,
    constraints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Generator Agent task.

    Generates candidate molecules using specified strategies.
    Retry: 1 time.
    """
    from medagent.services.molecule_generation import generate_project_molecules

    if strategies is None:
        strategies = ["crem"]
    if constraints is None:
        constraints = {}

    try:
        return generate_project_molecules(
            db,
            project,
            generation_size=generation_size,
            strategies=strategies,
            strategy_counts=strategy_counts,
            constraints=constraints,
            include_target_library_seeds=True,
        )
    except ValueError as exc:
        if str(exc) != "generation_requires_at_least_one_seed_ligand":
            raise
        return {
            "skipped": True,
            "reason": "generation_requires_at_least_one_seed_ligand",
            "molecule_count": 0,
            "warnings": [str(exc)],
        }


def molecule_validation_task(
    db: Session,
    project: Project,
) -> dict[str, Any]:
    """
    Validation Agent task.

    Validates molecule structures and calculates basic properties.
    Retry: 1 time.
    """
    from medagent.services.molecule_validation import validate_project_molecules

    return validate_project_molecules(db, project)


def rule_filtering_task(
    db: Session,
    project: Project,
) -> dict[str, Any]:
    """
    Filter Agent task.

    Applies rule-based filtering (PAINS, Brenk, property thresholds).
    Retry: 1 time.
    """
    from medagent.services.rule_filtering import filter_project_molecules

    return filter_project_molecules(db, project)


def candidate_assessment_task(
    db: Session,
    project: Project,
    max_molecules: int = 50,
    top_n: int | None = None,
    assessment_mode: str = "external",
    external_top_n: int = 10,
) -> dict[str, Any]:
    """
    Candidate Assessment Agent task.

    Runs docking, ADMET prediction, and synthesis assessment.
    Retry: 2 times with exponential backoff.
    """
    from medagent.services.candidate_assessment import run_project_candidate_assessment

    return run_project_candidate_assessment(
        db,
        project,
        max_molecules=max_molecules,
        top_n=top_n,
        assessment_mode=assessment_mode,
        external_top_n=external_top_n,
    )


def self_refutation_task(
    db: Session,
    settings: Settings,
    project: Project,
    max_molecules: int = 50,
) -> dict[str, Any]:
    """
    Self-Refutation Agent task.

    Generates heuristic critiques by default and uses the configured LLM only
    when self_refutation_use_llm is enabled.
    Retry: 2 times.
    """
    from medagent.services.self_refutation import generate_project_critiques

    return generate_project_critiques(
        db,
        project,
        settings=settings,
        max_molecules=max_molecules,
    )


def ranking_task(
    db: Session,
    project: Project,
    max_molecules: int = 50,
    top_n: int = 50,
) -> dict[str, Any]:
    """
    Ranker Agent task.

    Generates comprehensive rankings based on all evidence.
    Retry: 1 time.
    """
    from medagent.services.candidate_ranking import generate_project_rankings

    result = generate_project_rankings(db, project, max_molecules=max_molecules, top_n=top_n)
    return result.as_dict()


def advisor_task(
    db: Session,
    project: Project,
) -> dict[str, Any]:
    """
    Advisor Agent task.

    Generates optimization suggestions for next round.
    Retry: 1 time.
    """
    from medagent.services.advisor import generate_project_advice

    return generate_project_advice(db, project)


def decision_cards_task(
    db: Session,
    project: Project,
) -> dict[str, Any]:
    """
    Decision Card Agent task.

    Generates user-facing decision cards from reasoning traces.
    Retry: 1 time.
    """
    from medagent.services.decision_cards import generate_project_decision_cards

    return generate_project_decision_cards(db, project)


def report_generation_task(
    db: Session,
    project: Project,
) -> dict[str, Any]:
    """
    Report Agent task.

    Generates final project report with all evidence chains.
    Retry: 1 time.
    """
    from medagent.reporting.project_report import build_project_report

    return build_project_report(db, project)


# Batch processing utilities


def batch_molecule_task(
    db: Session,
    project: Project,
    molecule_ids: list[str],
    operation: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Process a batch of molecules with the specified operation.

    This allows parallel processing of large molecule sets.

    Args:
        db: Database session
        project: Project object
        molecule_ids: List of molecule IDs to process
        operation: Operation to perform (validate/filter/delete/reassess)
        **kwargs: Additional operation-specific arguments

    Returns:
        Dictionary with operation results
    """
    from medagent.db.models import Molecule, MoleculeProperty
    from medagent.services.candidate_assessment import run_project_candidate_assessment
    from medagent.services.molecule_validation import (
        merge_labels,
        update_molecule_structure_fields,
        upsert_molecule_property,
        validate_smiles,
    )
    from medagent.services.rule_filtering import (
        evaluate_molecule_rules,
        upsert_rule_filter_result,
    )

    allowed_operations = {"validate", "filter", "delete", "reassess"}
    if operation not in allowed_operations:
        raise ValueError(f"Unknown operation: {operation}")

    results = {
        "operation": operation,
        "total": len(molecule_ids),
        "succeeded": 0,
        "failed": 0,
        "errors": [],
    }

    molecules = (
        db.query(Molecule)
        .filter(
            Molecule.project_id == project.project_id,
            Molecule.molecule_id.in_(molecule_ids),
        )
        .all()
    )
    molecule_by_id = {molecule.molecule_id: molecule for molecule in molecules}

    if operation == "reassess":
        existing_ids = [
            molecule_id
            for molecule_id in molecule_ids
            if molecule_id in molecule_by_id
        ]
        for molecule_id in molecule_ids:
            if molecule_id not in molecule_by_id:
                results["failed"] += 1
                results["errors"].append(
                    {"molecule_id": molecule_id, "error": "molecule_not_found"}
                )

        if existing_ids:
            assessment = run_project_candidate_assessment(
                db,
                project,
                molecule_ids=existing_ids,
                max_molecules=len(existing_ids),
                top_n=kwargs.get("top_n", len(existing_ids)),
                assessment_mode=kwargs.get("assessment_mode", "fast"),
                external_top_n=kwargs.get("external_top_n", min(10, len(existing_ids))),
            )
            results["succeeded"] += len(existing_ids)
            results["assessment"] = assessment
        return results

    for molecule_id in molecule_ids:
        try:
            molecule = molecule_by_id.get(molecule_id)
            if molecule is None:
                raise ValueError("molecule_not_found")

            if operation == "validate":
                validation = validate_smiles(molecule.smiles)
                molecule.labels = merge_labels(molecule.labels, validation.labels)
                if validation.valid:
                    molecule.status = "structure_validated"
                    descriptors = validation.descriptors or {}
                    update_molecule_structure_fields(molecule, descriptors)
                    upsert_molecule_property(db, molecule, descriptors)
                else:
                    molecule.status = "invalid_structure"
            elif operation == "filter":
                properties = (
                    db.query(MoleculeProperty)
                    .filter_by(molecule_id=molecule.molecule_id)
                    .one_or_none()
                )
                evaluation = evaluate_molecule_rules(molecule, properties, project)
                upsert_rule_filter_result(db, project, molecule, evaluation)
                if evaluation.decision in {"passed", "passed_with_warnings"}:
                    molecule.status = "passed_filter"
                    molecule.labels = merge_labels(molecule.labels, evaluation.labels)
                elif evaluation.decision == "failed":
                    molecule.status = "failed_filter"
                    molecule.labels = merge_labels(
                        molecule.labels,
                        evaluation.labels + evaluation.failed_rules,
                    )
                else:
                    molecule.labels = merge_labels(molecule.labels, evaluation.labels)
            elif operation == "delete":
                db.delete(molecule)

            results["succeeded"] += 1
        except Exception as exc:
            results["failed"] += 1
            results["errors"].append({"molecule_id": molecule_id, "error": str(exc)})

    db.commit()

    return results


# Task configuration for Prefect integration

TASK_CONFIGS = {
    "knowledge_ingestion_agent": {
        "retries": 2,
        "retry_delay_seconds": 30,
        "timeout_seconds": 600,
    },
    "molecule_import_agent": {
        "retries": 1,
        "retry_delay_seconds": 10,
        "timeout_seconds": 120,
    },
    "generator_agent": {
        "retries": 1,
        "retry_delay_seconds": 30,
        "timeout_seconds": 600,
    },
    "validation_agent": {
        "retries": 1,
        "retry_delay_seconds": 10,
        "timeout_seconds": 300,
    },
    "filter_agent": {
        "retries": 1,
        "retry_delay_seconds": 10,
        "timeout_seconds": 300,
    },
    "candidate_assessment_agent": {
        "retries": 2,
        "retry_delay_seconds": 60,
        "timeout_seconds": 3600,  # 1 hour for docking/ADMET
    },
    "self_refutation_agent": {
        "retries": 2,
        "retry_delay_seconds": 30,
        "timeout_seconds": 600,
    },
    "ranker_agent": {
        "retries": 1,
        "retry_delay_seconds": 10,
        "timeout_seconds": 300,
    },
    "advisor_agent": {
        "retries": 1,
        "retry_delay_seconds": 10,
        "timeout_seconds": 300,
    },
    "decision_card_agent": {
        "retries": 1,
        "retry_delay_seconds": 10,
        "timeout_seconds": 300,
    },
    "report_agent": {
        "retries": 1,
        "retry_delay_seconds": 10,
        "timeout_seconds": 300,
    },
}


# Task registry for dynamic invocation

TASK_REGISTRY = {
    "knowledge_ingestion_agent": knowledge_ingestion_task,
    "molecule_import_agent": molecule_import_task,
    "generator_agent": molecule_generation_task,
    "validation_agent": molecule_validation_task,
    "filter_agent": rule_filtering_task,
    "candidate_assessment_agent": candidate_assessment_task,
    "self_refutation_agent": self_refutation_task,
    "ranker_agent": ranking_task,
    "advisor_agent": advisor_task,
    "decision_card_agent": decision_cards_task,
    "report_agent": report_generation_task,
}
