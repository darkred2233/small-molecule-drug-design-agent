import shutil
from pathlib import Path
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Query, Session

from medagent.core.config import Settings
from medagent.db.models import (
    ADMETResult,
    AgentRun,
    AdvisorSuggestion,
    BindingSite,
    ConformerResult,
    ConversationMessage,
    Critique,
    DecisionCard,
    DockingResult,
    EvidenceLink,
    Molecule,
    MoleculeProperty,
    OptimizationConstraint,
    Project,
    RagChunk,
    RagDocument,
    Ranking,
    ReasoningTrace,
    CampaignRun,
    ProjectResource,
    ProjectRound,
    RoundReport,
    RuleFilterResult,
    SeedLigand,
    SynthesisRoute,
    UploadedFile,
)


def delete_project_data(db: Session, project: Project) -> dict[str, int]:
    project_id = project.project_id
    counts: dict[str, int] = {}

    molecule_ids = _scalar_list(
        db.query(Molecule.molecule_id).filter(Molecule.project_id == project_id)
    )
    document_ids = _scalar_list(
        db.query(RagDocument.document_id).filter(RagDocument.project_id == project_id)
    )
    chunk_ids = (
        _scalar_list(db.query(RagChunk.chunk_id).filter(RagChunk.document_id.in_(document_ids)))
        if document_ids
        else []
    )

    evidence_filters = []
    if molecule_ids:
        evidence_filters.append(EvidenceLink.molecule_id.in_(molecule_ids))
    if chunk_ids:
        evidence_filters.append(EvidenceLink.chunk_id.in_(chunk_ids))
    if evidence_filters:
        counts["evidence_links"] = _delete(
            db.query(EvidenceLink).filter(or_(*evidence_filters))
        )

    if molecule_ids:
        counts["decision_cards"] = _delete(
            db.query(DecisionCard).filter(
                or_(
                    DecisionCard.project_id == project_id,
                    DecisionCard.molecule_id.in_(molecule_ids),
                )
            )
        )
        counts["reasoning_traces"] = _delete(
            db.query(ReasoningTrace).filter(
                or_(
                    ReasoningTrace.project_id == project_id,
                    ReasoningTrace.molecule_id.in_(molecule_ids),
                )
            )
        )
        counts["rankings"] = _delete(
            db.query(Ranking).filter(
                or_(Ranking.project_id == project_id, Ranking.molecule_id.in_(molecule_ids))
            )
        )
        counts["rule_filter_results"] = _delete(
            db.query(RuleFilterResult).filter(
                or_(
                    RuleFilterResult.project_id == project_id,
                    RuleFilterResult.molecule_id.in_(molecule_ids),
                )
            )
        )
        counts["critiques"] = _delete(
            db.query(Critique).filter(Critique.molecule_id.in_(molecule_ids))
        )
        counts["molecule_properties"] = _delete(
            db.query(MoleculeProperty).filter(MoleculeProperty.molecule_id.in_(molecule_ids))
        )
        counts["conformer_results"] = _delete(
            db.query(ConformerResult).filter(ConformerResult.molecule_id.in_(molecule_ids))
        )
        counts["docking_results"] = _delete(
            db.query(DockingResult).filter(DockingResult.molecule_id.in_(molecule_ids))
        )
        counts["admet_results"] = _delete(
            db.query(ADMETResult).filter(ADMETResult.molecule_id.in_(molecule_ids))
        )
        counts["synthesis_routes"] = _delete(
            db.query(SynthesisRoute).filter(SynthesisRoute.molecule_id.in_(molecule_ids))
        )
    else:
        counts["decision_cards"] = _delete(
            db.query(DecisionCard).filter(DecisionCard.project_id == project_id)
        )
        counts["reasoning_traces"] = _delete(
            db.query(ReasoningTrace).filter(ReasoningTrace.project_id == project_id)
        )
        counts["rankings"] = _delete(db.query(Ranking).filter(Ranking.project_id == project_id))
        counts["rule_filter_results"] = _delete(
            db.query(RuleFilterResult).filter(RuleFilterResult.project_id == project_id)
        )

    if document_ids:
        counts["rag_chunks"] = _delete(
            db.query(RagChunk).filter(RagChunk.document_id.in_(document_ids))
        )
        counts["rag_documents"] = _delete(
            db.query(RagDocument).filter(RagDocument.document_id.in_(document_ids))
        )

    counts["uploaded_files"] = _delete(
        db.query(UploadedFile).filter(UploadedFile.project_id == project_id)
    )
    counts["conversation_messages"] = _delete(
        db.query(ConversationMessage).filter(ConversationMessage.project_id == project_id)
    )
    counts["optimization_constraints"] = _delete(
        db.query(OptimizationConstraint).filter(OptimizationConstraint.project_id == project_id)
    )
    counts["agent_runs"] = _delete(
        db.query(AgentRun).filter(AgentRun.project_id == project_id)
    )
    counts["advisor_suggestions"] = _delete(
        db.query(AdvisorSuggestion).filter(AdvisorSuggestion.project_id == project_id)
    )
    counts["round_reports"] = _delete(
        db.query(RoundReport).filter(RoundReport.project_id == project_id)
    )
    counts["campaign_runs"] = _delete(
        db.query(CampaignRun).filter(CampaignRun.project_id == project_id)
    )
    counts["project_resources"] = _delete(
        db.query(ProjectResource).filter(ProjectResource.project_id == project_id)
    )
    if molecule_ids:
        counts["molecules"] = _delete(
            db.query(Molecule).filter(Molecule.molecule_id.in_(molecule_ids))
        )

    round_query = db.query(ProjectRound).filter(ProjectRound.project_id == project_id)
    round_query.update({ProjectRound.parent_round_id: None}, synchronize_session=False)
    counts["project_rounds"] = _delete(round_query)
    counts["binding_sites"] = _delete(
        db.query(BindingSite).filter(BindingSite.project_id == project_id)
    )
    counts["seed_ligands"] = _delete(
        db.query(SeedLigand).filter(SeedLigand.project_id == project_id)
    )
    db.delete(project)
    counts["projects"] = 1
    return counts


def cleanup_project_artifacts(settings: Settings, project_id: str) -> list[str]:
    warnings: list[str] = []
    targets = [
        (Path(settings.storage_local_root) / project_id, Path(settings.storage_local_root)),
        (Path(".local") / "reports" / _safe_path_part(project_id), Path(".local") / "reports"),
    ]

    for target, root in targets:
        warning = _remove_project_directory(target, root)
        if warning:
            warnings.append(warning)

    return warnings


def _delete(query: Query[Any]) -> int:
    return int(query.delete(synchronize_session=False) or 0)


def _scalar_list(query: Query[Any]) -> list[str]:
    return [row[0] for row in query.all()]


def _remove_project_directory(target: Path, root: Path) -> str | None:
    root_resolved = root.resolve()
    target_resolved = target.resolve()

    try:
        target_resolved.relative_to(root_resolved)
    except ValueError:
        return f"Skipped artifact cleanup outside root: {target_resolved}"

    if target_resolved == root_resolved:
        return f"Skipped artifact cleanup for root directory: {target_resolved}"

    if not target_resolved.exists():
        return None

    try:
        shutil.rmtree(target_resolved)
    except OSError as exc:
        return f"Failed to remove {target_resolved}: {exc}"
    return None


def _safe_path_part(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in "._-" else "_" for char in value)
    return safe.strip("._") or "project"
