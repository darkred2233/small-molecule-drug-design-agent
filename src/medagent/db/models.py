from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    target_id: Mapped[str | None] = mapped_column(String(80), index=True)
    objective: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="created")
    constraints_json: Mapped[dict] = mapped_column(JSON, default=dict)

    messages: Mapped[list["ConversationMessage"]] = relationship(back_populates="project")
    constraints: Mapped[list["OptimizationConstraint"]] = relationship(back_populates="project")
    agent_runs: Mapped[list["AgentRun"]] = relationship(back_populates="project")


class Target(TimestampMixin, Base):
    __tablename__ = "targets"

    id: Mapped[int] = mapped_column(primary_key=True)
    target_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)
    uniprot_id: Mapped[str | None] = mapped_column(String(80))
    species: Mapped[str | None] = mapped_column(String(120))
    pdb_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    pocket_summary: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)

    drugs: Mapped[list["TargetDrugLibrary"]] = relationship(back_populates="target")


class TargetDrugLibrary(TimestampMixin, Base):
    __tablename__ = "target_drug_library"
    __table_args__ = (UniqueConstraint("target_id", "drug_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    target_id: Mapped[str] = mapped_column(ForeignKey("targets.target_id"), index=True)
    drug_name: Mapped[str] = mapped_column(String(160))
    drug_status: Mapped[str | None] = mapped_column(String(80))
    mechanism: Mapped[str | None] = mapped_column(String(240))
    indication: Mapped[str | None] = mapped_column(String(240))
    smiles: Mapped[str | None] = mapped_column(Text)
    canonical_smiles: Mapped[str | None] = mapped_column(Text)
    isomeric_smiles: Mapped[str | None] = mapped_column(Text)
    inchi_key: Mapped[str | None] = mapped_column(String(120), index=True)
    pubchem_cid: Mapped[int | None] = mapped_column(Integer)
    evidence_source: Mapped[str | None] = mapped_column(String(240))
    external_refs: Mapped[dict] = mapped_column(JSON, default=dict)

    target: Mapped["Target"] = relationship(back_populates="drugs")


class BindingSite(TimestampMixin, Base):
    __tablename__ = "binding_sites"

    id: Mapped[int] = mapped_column(primary_key=True)
    binding_site_id: Mapped[str] = mapped_column(String(80), unique=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.project_id"), index=True)
    target_id: Mapped[str] = mapped_column(ForeignKey("targets.target_id"), index=True)
    pdb_id: Mapped[str | None] = mapped_column(String(40))
    source_file_id: Mapped[str | None] = mapped_column(String(80), index=True)
    receptor_file: Mapped[str | None] = mapped_column(Text)
    prepared_receptor_file: Mapped[str | None] = mapped_column(Text)
    preparation_status: Mapped[str] = mapped_column(String(80), default="uploaded")
    key_residues: Mapped[list[str]] = mapped_column(JSON, default=list)
    grid_box: Mapped[dict] = mapped_column(JSON, default=dict)
    preparation_json: Mapped[dict] = mapped_column(JSON, default=dict)


class SeedLigand(TimestampMixin, Base):
    __tablename__ = "seed_ligands"

    id: Mapped[int] = mapped_column(primary_key=True)
    ligand_id: Mapped[str] = mapped_column(String(80), unique=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.project_id"), index=True)
    target_id: Mapped[str | None] = mapped_column(ForeignKey("targets.target_id"), index=True)
    name: Mapped[str | None] = mapped_column(String(160))
    smiles: Mapped[str] = mapped_column(Text)
    activity_value: Mapped[float | None] = mapped_column(Float)
    activity_unit: Mapped[str | None] = mapped_column(String(40))
    activity_type: Mapped[str | None] = mapped_column(String(40))
    source: Mapped[str | None] = mapped_column(String(240))


class UploadedFile(TimestampMixin, Base):
    __tablename__ = "uploaded_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[str] = mapped_column(String(80), unique=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    filename: Mapped[str] = mapped_column(String(300))
    file_type: Mapped[str] = mapped_column(String(80))
    storage_path: Mapped[str] = mapped_column(Text)
    parse_status: Mapped[str] = mapped_column(String(80), default="uploaded")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


class ConversationMessage(TimestampMixin, Base):
    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[str] = mapped_column(String(80), unique=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    role: Mapped[str] = mapped_column(String(40))
    content: Mapped[str] = mapped_column(Text)
    intent: Mapped[str | None] = mapped_column(String(80))
    extracted_payload: Mapped[dict] = mapped_column(JSON, default=dict)

    project: Mapped["Project"] = relationship(back_populates="messages")


class OptimizationConstraint(TimestampMixin, Base):
    __tablename__ = "optimization_constraints"

    id: Mapped[int] = mapped_column(primary_key=True)
    constraint_id: Mapped[str] = mapped_column(String(80), unique=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    label: Mapped[str] = mapped_column(String(80))
    field: Mapped[str | None] = mapped_column(String(120))
    operator: Mapped[str | None] = mapped_column(String(40))
    value: Mapped[str | None] = mapped_column(String(240))
    priority: Mapped[int] = mapped_column(Integer, default=50)
    source_message_id: Mapped[str | None] = mapped_column(String(80))

    project: Mapped["Project"] = relationship(back_populates="constraints")


class Molecule(TimestampMixin, Base):
    __tablename__ = "molecules"

    id: Mapped[int] = mapped_column(primary_key=True)
    molecule_id: Mapped[str] = mapped_column(String(80), unique=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    round_id: Mapped[str | None] = mapped_column(ForeignKey("project_rounds.round_id"), index=True)
    campaign_run_id: Mapped[str | None] = mapped_column(String(80), index=True)
    smiles: Mapped[str] = mapped_column(Text)
    inchi_key: Mapped[str | None] = mapped_column(String(120), index=True)
    scaffold: Mapped[str | None] = mapped_column(String(160), index=True)
    source_agent: Mapped[str | None] = mapped_column(String(120))
    generation_method: Mapped[str | None] = mapped_column(String(80), index=True)
    parent_molecule_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    provenance_json: Mapped[dict] = mapped_column(JSON, default=dict)
    generation_metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(80), default="generated")
    labels: Mapped[list[str]] = mapped_column(JSON, default=list)


class MoleculeProperty(TimestampMixin, Base):
    __tablename__ = "molecule_properties"

    id: Mapped[int] = mapped_column(primary_key=True)
    molecule_id: Mapped[str] = mapped_column(ForeignKey("molecules.molecule_id"), index=True)
    mw: Mapped[float | None] = mapped_column(Float)
    logp: Mapped[float | None] = mapped_column(Float)
    tpsa: Mapped[float | None] = mapped_column(Float)
    hbd: Mapped[int | None] = mapped_column(Integer)
    hba: Mapped[int | None] = mapped_column(Integer)
    sa_score: Mapped[float | None] = mapped_column(Float)
    tool_metadata: Mapped[dict] = mapped_column(JSON, default=dict)


class RuleFilterResult(TimestampMixin, Base):
    __tablename__ = "rule_filter_results"
    __table_args__ = (UniqueConstraint("molecule_id", "rule_set"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    filter_result_id: Mapped[str] = mapped_column(String(80), unique=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    molecule_id: Mapped[str] = mapped_column(ForeignKey("molecules.molecule_id"), index=True)
    round_id: Mapped[str | None] = mapped_column(ForeignKey("project_rounds.round_id"), index=True)
    rule_set: Mapped[str] = mapped_column(String(80), default="basic_drug_likeness_v1")
    decision: Mapped[str] = mapped_column(String(80))
    failed_rules: Mapped[list[str]] = mapped_column(JSON, default=list)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    labels: Mapped[list[str]] = mapped_column(JSON, default=list)
    properties_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    raw_output: Mapped[dict] = mapped_column(JSON, default=dict)


class ConformerResult(TimestampMixin, Base):
    __tablename__ = "conformer_results"
    __table_args__ = (UniqueConstraint("molecule_id", "round_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    molecule_id: Mapped[str] = mapped_column(ForeignKey("molecules.molecule_id"), index=True)
    round_id: Mapped[str | None] = mapped_column(ForeignKey("project_rounds.round_id"), index=True)
    conformer_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    conformer_count: Mapped[int | None] = mapped_column(Integer)
    lowest_energy: Mapped[float | None] = mapped_column(Float)
    strain_energy: Mapped[float | None] = mapped_column(Float)
    rmsd_between_conformers: Mapped[float | None] = mapped_column(Float)
    chiral_centers: Mapped[int | None] = mapped_column(Integer)
    undefined_stereo_centers: Mapped[int | None] = mapped_column(Integer)
    labels: Mapped[list[str]] = mapped_column(JSON, default=list)
    conformer_file: Mapped[str | None] = mapped_column(Text)
    raw_output: Mapped[dict] = mapped_column(JSON, default=dict)


class DockingResult(TimestampMixin, Base):
    __tablename__ = "docking_results"
    __table_args__ = (UniqueConstraint("molecule_id", "round_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    molecule_id: Mapped[str] = mapped_column(ForeignKey("molecules.molecule_id"), index=True)
    round_id: Mapped[str | None] = mapped_column(ForeignKey("project_rounds.round_id"), index=True)
    tool_run_id: Mapped[str | None] = mapped_column(String(80))
    vina_score: Mapped[float | None] = mapped_column(Float)
    cnn_score: Mapped[float | None] = mapped_column(Float)
    diffdock_confidence: Mapped[float | None] = mapped_column(Float)
    key_hbond_count: Mapped[int | None] = mapped_column(Integer)
    clash_count: Mapped[int | None] = mapped_column(Integer)
    pose_file: Mapped[str | None] = mapped_column(Text)
    labels: Mapped[list[str]] = mapped_column(JSON, default=list)
    raw_output: Mapped[dict] = mapped_column(JSON, default=dict)


class ADMETResult(TimestampMixin, Base):
    __tablename__ = "admet_results"
    __table_args__ = (UniqueConstraint("molecule_id", "round_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    molecule_id: Mapped[str] = mapped_column(ForeignKey("molecules.molecule_id"), index=True)
    round_id: Mapped[str | None] = mapped_column(ForeignKey("project_rounds.round_id"), index=True)
    hERG_probability: Mapped[float | None] = mapped_column(Float)
    hERG_risk: Mapped[str | None] = mapped_column(String(80))
    Ames_probability: Mapped[float | None] = mapped_column(Float)
    Ames_risk: Mapped[str | None] = mapped_column(String(80))
    solubility: Mapped[str | None] = mapped_column(String(80))
    permeability: Mapped[str | None] = mapped_column(String(80))
    admet_risk_score: Mapped[float | None] = mapped_column(Float)
    labels: Mapped[list[str]] = mapped_column(JSON, default=list)
    raw_output: Mapped[dict] = mapped_column(JSON, default=dict)


class SynthesisRoute(TimestampMixin, Base):
    __tablename__ = "synthesis_routes"
    __table_args__ = (UniqueConstraint("molecule_id", "round_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    molecule_id: Mapped[str] = mapped_column(ForeignKey("molecules.molecule_id"), index=True)
    round_id: Mapped[str | None] = mapped_column(ForeignKey("project_rounds.round_id"), index=True)
    route_found: Mapped[bool] = mapped_column(Boolean, default=False)
    route_steps: Mapped[int | None] = mapped_column(Integer)
    route_confidence: Mapped[float | None] = mapped_column(Float)
    buyable_building_blocks: Mapped[int | None] = mapped_column(Integer)
    labels: Mapped[list[str]] = mapped_column(JSON, default=list)
    route_json: Mapped[dict] = mapped_column(JSON, default=dict)


class RagDocument(TimestampMixin, Base):
    __tablename__ = "rag_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[str] = mapped_column(String(80), unique=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.project_id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    source: Mapped[str | None] = mapped_column(Text)
    document_type: Mapped[str] = mapped_column(String(80))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


class RagChunk(TimestampMixin, Base):
    __tablename__ = "rag_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    chunk_id: Mapped[str] = mapped_column(String(80), unique=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("rag_documents.document_id"), index=True)
    page_number: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(240))
    content: Mapped[str] = mapped_column(Text)
    embedding_model: Mapped[str | None] = mapped_column(String(120))
    embedding_ref: Mapped[str | None] = mapped_column(String(240))
    embedding_json: Mapped[list[float]] = mapped_column(JSON, default=list)
    token_count: Mapped[int | None] = mapped_column(Integer)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


class EvidenceLink(TimestampMixin, Base):
    __tablename__ = "evidence_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    evidence_id: Mapped[str] = mapped_column(String(80), unique=True)
    molecule_id: Mapped[str | None] = mapped_column(ForeignKey("molecules.molecule_id"), index=True)
    chunk_id: Mapped[str] = mapped_column(ForeignKey("rag_chunks.chunk_id"), index=True)
    claim_type: Mapped[str] = mapped_column(String(120))
    confidence: Mapped[float | None] = mapped_column(Float)
    rationale: Mapped[str | None] = mapped_column(Text)


class AgentRun(TimestampMixin, Base):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_run_id: Mapped[str] = mapped_column(String(80), unique=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.project_id"), index=True)
    round_id: Mapped[str | None] = mapped_column(ForeignKey("project_rounds.round_id"), index=True)
    agent_name: Mapped[str] = mapped_column(String(120), index=True)
    model_name: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(80), default="queued")
    input_json: Mapped[dict] = mapped_column(JSON, default=dict)
    output_json: Mapped[dict] = mapped_column(JSON, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)

    project: Mapped["Project"] = relationship(back_populates="agent_runs")


class Critique(TimestampMixin, Base):
    __tablename__ = "critiques"

    id: Mapped[int] = mapped_column(primary_key=True)
    critique_id: Mapped[str] = mapped_column(String(80), unique=True)
    molecule_id: Mapped[str] = mapped_column(ForeignKey("molecules.molecule_id"), index=True)
    round_id: Mapped[str | None] = mapped_column(ForeignKey("project_rounds.round_id"), index=True)
    con_score: Mapped[float | None] = mapped_column(Float)
    risk_level: Mapped[str] = mapped_column(String(80))
    reason: Mapped[str] = mapped_column(Text)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    refutation_decision: Mapped[str | None] = mapped_column(String(80))
    llm_critique_json: Mapped[dict | None] = mapped_column(JSON, default=None)
    llm_provider: Mapped[str | None] = mapped_column(String(80))
    analysis_method: Mapped[str] = mapped_column(
        String(80), default="heuristic_self_refutation"
    )
    property_diagnostics_json: Mapped[dict | None] = mapped_column(JSON, default=None)
    campaign_patch_suggestions_json: Mapped[dict | None] = mapped_column(JSON, default=None)
    requires_user_confirmation: Mapped[bool] = mapped_column(Boolean, default=False)


class ReasoningTrace(TimestampMixin, Base):
    __tablename__ = "reasoning_traces"

    id: Mapped[int] = mapped_column(primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(80), unique=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    molecule_id: Mapped[str | None] = mapped_column(ForeignKey("molecules.molecule_id"), index=True)
    trace_type: Mapped[str] = mapped_column(String(80), default="molecule_decision")
    claim: Mapped[str] = mapped_column(Text)
    supporting_factors: Mapped[list[str]] = mapped_column(JSON, default=list)
    opposing_factors: Mapped[list[str]] = mapped_column(JSON, default=list)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    uncertainty: Mapped[str | None] = mapped_column(Text)
    next_actions: Mapped[list[str]] = mapped_column(JSON, default=list)
    confidence: Mapped[float | None] = mapped_column(Float)
    source_agent: Mapped[str] = mapped_column(String(120), default="decision_card_generator")
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)


class DecisionCard(TimestampMixin, Base):
    __tablename__ = "decision_cards"

    id: Mapped[int] = mapped_column(primary_key=True)
    decision_id: Mapped[str] = mapped_column(String(80), unique=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    molecule_id: Mapped[str | None] = mapped_column(ForeignKey("molecules.molecule_id"), index=True)
    trace_id: Mapped[str | None] = mapped_column(ForeignKey("reasoning_traces.trace_id"), index=True)
    card_type: Mapped[str] = mapped_column(String(80), default="molecule_validation")
    title: Mapped[str] = mapped_column(String(240))
    decision: Mapped[str] = mapped_column(String(80))
    summary: Mapped[str] = mapped_column(Text)
    support: Mapped[list[str]] = mapped_column(JSON, default=list)
    risk: Mapped[list[str]] = mapped_column(JSON, default=list)
    next_steps: Mapped[list[str]] = mapped_column(JSON, default=list)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    confidence: Mapped[float | None] = mapped_column(Float)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)


class AdvisorSuggestion(TimestampMixin, Base):
    __tablename__ = "advisor_suggestions"

    id: Mapped[int] = mapped_column(primary_key=True)
    suggestion_id: Mapped[str] = mapped_column(String(80), unique=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    round_id: Mapped[str | None] = mapped_column(ForeignKey("project_rounds.round_id"), index=True)
    summary: Mapped[str] = mapped_column(Text)
    suggestions: Mapped[list[dict]] = mapped_column(JSON, default=list)
    next_round_constraints: Mapped[list[dict]] = mapped_column(JSON, default=list)
    suggested_generation_config: Mapped[dict] = mapped_column(JSON, default=dict)


class Ranking(TimestampMixin, Base):
    __tablename__ = "rankings"
    __table_args__ = (UniqueConstraint("project_id", "molecule_id", "round_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.project_id"), index=True)
    molecule_id: Mapped[str] = mapped_column(ForeignKey("molecules.molecule_id"), index=True)
    round_id: Mapped[str | None] = mapped_column(ForeignKey("project_rounds.round_id"), index=True)
    rank: Mapped[int] = mapped_column(Integer)
    pro_score: Mapped[float | None] = mapped_column(Float)
    con_score: Mapped[float | None] = mapped_column(Float)
    evidence_confidence: Mapped[float | None] = mapped_column(Float)
    overall_score: Mapped[float | None] = mapped_column(Float)
    final_decision: Mapped[str] = mapped_column(String(80))
    score_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)


# ---------------------------------------------------------------------------
# Round + Campaign tables
# ---------------------------------------------------------------------------


class TargetLigand(TimestampMixin, Base):
    """靶点已知配体（ChEMBL / PubChem / 内置数据）。"""
    __tablename__ = "target_ligands"

    id: Mapped[int] = mapped_column(primary_key=True)
    target_ligand_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    target_id: Mapped[str] = mapped_column(ForeignKey("targets.target_id"), index=True)
    name: Mapped[str | None] = mapped_column(String(200))
    smiles: Mapped[str] = mapped_column(Text)
    canonical_smiles: Mapped[str | None] = mapped_column(Text)
    inchi_key: Mapped[str | None] = mapped_column(String(120), index=True)
    source: Mapped[str] = mapped_column(String(80))  # chembl / pubchem / builtin
    source_id: Mapped[str | None] = mapped_column(String(200))
    activity_value: Mapped[float | None] = mapped_column(Float)
    activity_unit: Mapped[str | None] = mapped_column(String(40))
    activity_type: Mapped[str | None] = mapped_column(String(40))
    pchembl_value: Mapped[float | None] = mapped_column(Float)
    assay_type: Mapped[str | None] = mapped_column(String(80))
    confidence_level: Mapped[str] = mapped_column(String(40), default="standard")
    properties_json: Mapped[dict | None] = mapped_column(JSON, default=None)
    provenance_json: Mapped[dict | None] = mapped_column(JSON, default=None)


class ProjectResource(TimestampMixin, Base):
    """项目级资源（receptor / pocket / source pool 等）。"""
    __tablename__ = "project_resources"

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.project_id"), index=True)
    target_id: Mapped[str | None] = mapped_column(ForeignKey("targets.target_id"), index=True)
    resource_type: Mapped[str] = mapped_column(String(80))  # receptor / binding_pocket / source_compound_library / ...
    scope: Mapped[str] = mapped_column(String(80))  # builtin / target / project / user_uploaded / generated
    name: Mapped[str] = mapped_column(String(200))
    file_path: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, default=None)
    confidence_level: Mapped[str | None] = mapped_column(String(40))
    source_url: Mapped[str | None] = mapped_column(Text)


class ProjectRound(TimestampMixin, Base):
    """项目轮次。"""
    __tablename__ = "project_rounds"

    id: Mapped[int] = mapped_column(primary_key=True)
    round_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    round_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40), default="draft")  # draft/ready/running/completed/failed/cancelled
    parent_round_id: Mapped[str | None] = mapped_column(ForeignKey("project_rounds.round_id"))
    user_conditions_json: Mapped[dict | None] = mapped_column(JSON, default=None)
    execution_config_snapshot_json: Mapped[dict | None] = mapped_column(JSON, default=None)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    campaigns: Mapped[list["CampaignRun"]] = relationship(back_populates="round")


class CampaignRun(TimestampMixin, Base):
    """方法级运行记录。"""
    __tablename__ = "campaign_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_run_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    round_id: Mapped[str] = mapped_column(ForeignKey("project_rounds.round_id"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    method: Mapped[str] = mapped_column(String(40))  # crem / reinvent4 / autogrow4
    status: Mapped[str] = mapped_column(String(40), default="pending")
    config_json: Mapped[dict | None] = mapped_column(JSON, default=None)
    resource_bundle_json: Mapped[dict | None] = mapped_column(JSON, default=None)
    input_molecule_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    output_molecule_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    metrics_json: Mapped[dict | None] = mapped_column(JSON, default=None)
    warnings_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    round: Mapped["ProjectRound"] = relationship(back_populates="campaigns")


class RoundReport(TimestampMixin, Base):
    """持久化的单轮报告快照。"""

    __tablename__ = "round_reports"
    __table_args__ = (UniqueConstraint("round_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    round_id: Mapped[str] = mapped_column(ForeignKey("project_rounds.round_id"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="completed")
    report_json: Mapped[dict] = mapped_column(JSON, default=dict)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
