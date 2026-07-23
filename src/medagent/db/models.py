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
    # Reproducible structure/pocket fields. Existing user-created sites remain valid.
    structure_id: Mapped[str | None] = mapped_column(String(80), index=True)
    reference_ligand_id: Mapped[str | None] = mapped_column(String(80), index=True)
    pocket_residues_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    pocket_method: Mapped[str | None] = mapped_column(String(80))
    validation_status: Mapped[str] = mapped_column(String(80), default="unvalidated")
    redock_rmsd: Mapped[float | None] = mapped_column(Float)
    artifact_id: Mapped[str | None] = mapped_column(String(80), index=True)


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
    method: Mapped[str] = mapped_column(String(40))  # crem / targetdiff / autogrow4; historical values remain readable
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


# ---------------------------------------------------------------------------
# Scientific execution and data provenance
# ---------------------------------------------------------------------------


class SourceRelease(TimestampMixin, Base):
    """An immutable imported source release; imports must never overwrite it."""

    __tablename__ = "source_releases"
    __table_args__ = (UniqueConstraint("source_name", "release_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_release_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    source_name: Mapped[str] = mapped_column(String(120), index=True)
    release_name: Mapped[str] = mapped_column(String(160))
    release_date: Mapped[datetime | None] = mapped_column(DateTime)
    source_url: Mapped[str | None] = mapped_column(Text)
    license_name: Mapped[str | None] = mapped_column(String(240))
    license_url: Mapped[str | None] = mapped_column(Text)
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime)
    file_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    record_count: Mapped[int | None] = mapped_column(Integer)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


class TargetExternalId(TimestampMixin, Base):
    __tablename__ = "target_external_ids"
    __table_args__ = (
        UniqueConstraint("target_id", "namespace", "external_id", "source_release_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    target_id: Mapped[str] = mapped_column(ForeignKey("targets.target_id"), index=True)
    namespace: Mapped[str] = mapped_column(String(80))
    external_id: Mapped[str] = mapped_column(String(160))
    taxon_id: Mapped[int | None] = mapped_column(Integer)
    isoform: Mapped[str | None] = mapped_column(String(80))
    source_release_id: Mapped[str] = mapped_column(
        ForeignKey("source_releases.source_release_id"), index=True
    )


class TargetStructure(TimestampMixin, Base):
    __tablename__ = "target_structures"
    __table_args__ = (
        UniqueConstraint("source", "source_structure_id", "source_release_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    structure_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    target_id: Mapped[str] = mapped_column(ForeignKey("targets.target_id"), index=True)
    source: Mapped[str] = mapped_column(String(80))
    source_structure_id: Mapped[str] = mapped_column(String(80), index=True)
    assembly_id: Mapped[str | None] = mapped_column(String(80))
    experimental_method: Mapped[str | None] = mapped_column(String(120))
    resolution: Mapped[float | None] = mapped_column(Float)
    is_experimental: Mapped[bool] = mapped_column(Boolean, default=True)
    is_preferred: Mapped[bool] = mapped_column(Boolean, default=False)
    quality_status: Mapped[str] = mapped_column(String(80), default="metadata_only")
    source_release_id: Mapped[str] = mapped_column(
        ForeignKey("source_releases.source_release_id"), index=True
    )


class StructureChain(TimestampMixin, Base):
    __tablename__ = "structure_chains"
    __table_args__ = (UniqueConstraint("structure_id", "chain_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    structure_id: Mapped[str] = mapped_column(ForeignKey("target_structures.structure_id"), index=True)
    chain_id: Mapped[str] = mapped_column(String(16))
    uniprot_accession: Mapped[str | None] = mapped_column(String(80), index=True)
    uniprot_start: Mapped[int | None] = mapped_column(Integer)
    uniprot_end: Mapped[int | None] = mapped_column(Integer)
    sequence_identity: Mapped[float | None] = mapped_column(Float)
    is_target_chain: Mapped[bool] = mapped_column(Boolean, default=False)


class Compound(TimestampMixin, Base):
    __tablename__ = "compounds"
    __table_args__ = (UniqueConstraint("inchi_key", "source_release_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    compound_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    canonical_smiles: Mapped[str] = mapped_column(Text)
    isomeric_smiles: Mapped[str | None] = mapped_column(Text)
    inchi_key: Mapped[str | None] = mapped_column(String(120), index=True)
    parent_inchi_key: Mapped[str | None] = mapped_column(String(120), index=True)
    standardization_version: Mapped[str | None] = mapped_column(String(80))
    molecular_weight: Mapped[float | None] = mapped_column(Float)
    source_release_id: Mapped[str] = mapped_column(
        ForeignKey("source_releases.source_release_id"), index=True
    )


class Assay(TimestampMixin, Base):
    __tablename__ = "assays"
    __table_args__ = (UniqueConstraint("source", "source_assay_id", "source_release_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    assay_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    source: Mapped[str] = mapped_column(String(80))
    source_assay_id: Mapped[str] = mapped_column(String(160))
    target_id: Mapped[str | None] = mapped_column(ForeignKey("targets.target_id"), index=True)
    assay_type: Mapped[str | None] = mapped_column(String(80))
    target_confidence: Mapped[float | None] = mapped_column(Float)
    organism: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    document_ref: Mapped[str | None] = mapped_column(String(240))
    source_release_id: Mapped[str] = mapped_column(
        ForeignKey("source_releases.source_release_id"), index=True
    )


class Bioactivity(TimestampMixin, Base):
    """A raw activity measurement, never deduplicated only by target and compound."""

    __tablename__ = "bioactivities"
    __table_args__ = (UniqueConstraint("source", "source_record_id", "source_release_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    activity_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    source: Mapped[str] = mapped_column(String(80))
    source_record_id: Mapped[str] = mapped_column(String(160))
    compound_id: Mapped[str] = mapped_column(ForeignKey("compounds.compound_id"), index=True)
    target_id: Mapped[str] = mapped_column(ForeignKey("targets.target_id"), index=True)
    assay_id: Mapped[str] = mapped_column(ForeignKey("assays.assay_id"), index=True)
    activity_type: Mapped[str] = mapped_column(String(40))
    relation: Mapped[str | None] = mapped_column(String(8))
    value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(40))
    p_activity: Mapped[float | None] = mapped_column(Float)
    is_direct_binding: Mapped[bool] = mapped_column(Boolean, default=False)
    quality_tier: Mapped[str] = mapped_column(String(8), default="D")
    source_release_id: Mapped[str] = mapped_column(
        ForeignKey("source_releases.source_release_id"), index=True
    )


class ScientificArtifact(TimestampMixin, Base):
    __tablename__ = "scientific_artifacts"
    __table_args__ = (UniqueConstraint("sha256", "uri"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    artifact_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    artifact_type: Mapped[str] = mapped_column(String(80))
    uri: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    producer_tool: Mapped[str | None] = mapped_column(String(120))
    producer_version: Mapped[str | None] = mapped_column(String(120))
    source_release_id: Mapped[str | None] = mapped_column(
        ForeignKey("source_releases.source_release_id"), index=True
    )


class TargetResourceLink(TimestampMixin, Base):
    __tablename__ = "target_resource_links"
    __table_args__ = (UniqueConstraint("target_id", "artifact_id", "role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    target_id: Mapped[str] = mapped_column(ForeignKey("targets.target_id"), index=True)
    artifact_id: Mapped[str] = mapped_column(ForeignKey("scientific_artifacts.artifact_id"), index=True)
    role: Mapped[str] = mapped_column(String(80))
    structure_id: Mapped[str | None] = mapped_column(ForeignKey("target_structures.structure_id"), index=True)
    binding_site_id: Mapped[str | None] = mapped_column(ForeignKey("binding_sites.binding_site_id"), index=True)
    is_preferred: Mapped[bool] = mapped_column(Boolean, default=False)


class TargetResourcePackage(TimestampMixin, Base):
    """A compact readiness record for a target's executable resource package."""

    __tablename__ = "target_resource_packages"
    __table_args__ = (UniqueConstraint("target_id", "package_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    package_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    target_id: Mapped[str] = mapped_column(ForeignKey("targets.target_id"), index=True)
    package_version: Mapped[str] = mapped_column(String(80), default="v1")
    uniprot_accession: Mapped[str | None] = mapped_column(String(80))
    primary_structure_id: Mapped[str | None] = mapped_column(String(80), index=True)
    binding_site_id: Mapped[str | None] = mapped_column(String(80), index=True)
    reference_ligand_id: Mapped[str | None] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(80), default="metadata_ready")
    completeness_json: Mapped[dict] = mapped_column(JSON, default=dict)
    source_release_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)


class CapabilitySnapshotRecord(TimestampMixin, Base):
    __tablename__ = "capability_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    snapshot_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.project_id"), index=True)
    round_id: Mapped[str | None] = mapped_column(ForeignKey("project_rounds.round_id"), index=True)
    snapshot_json: Mapped[dict] = mapped_column(JSON, default=dict)


class ExecutionPlanRecord(TimestampMixin, Base):
    __tablename__ = "execution_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    plan_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.project_id"), index=True)
    round_id: Mapped[str | None] = mapped_column(ForeignKey("project_rounds.round_id"), index=True)
    capability_snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("capability_snapshots.snapshot_id"), index=True
    )
    status: Mapped[str] = mapped_column(String(40), default="planned")
    plan_json: Mapped[dict] = mapped_column(JSON, default=dict)


class ExecutionManifest(TimestampMixin, Base):
    __tablename__ = "execution_manifests"

    id: Mapped[int] = mapped_column(primary_key=True)
    manifest_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    manifest_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.project_id"), index=True)
    round_id: Mapped[str | None] = mapped_column(ForeignKey("project_rounds.round_id"), index=True)
    job_id: Mapped[str | None] = mapped_column(String(80), index=True)
    stage: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(40))
    request_hash: Mapped[str] = mapped_column(String(64), index=True)
    policy_name: Mapped[str] = mapped_column(String(120), default="scientific_execution")
    policy_version: Mapped[str] = mapped_column(String(80), default="1.0")
    capability_snapshot_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    source_release_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    command: Mapped[list[str]] = mapped_column(JSON, default=list)
    environment_json: Mapped[dict] = mapped_column(JSON, default=dict)
    input_artifacts: Mapped[dict] = mapped_column(JSON, default=dict)
    output_artifacts: Mapped[dict] = mapped_column(JSON, default=dict)
    stdout: Mapped[str | None] = mapped_column(Text)
    stderr: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    exit_code: Mapped[int | None] = mapped_column(Integer)
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)


class ScientificJob(TimestampMixin, Base):
    __tablename__ = "scientific_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    round_id: Mapped[str | None] = mapped_column(ForeignKey("project_rounds.round_id"), index=True)
    stage: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    input_snapshot_json: Mapped[dict] = mapped_column(JSON, default=dict)
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)
    claimed_by: Mapped[str | None] = mapped_column(String(160))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_message: Mapped[str | None] = mapped_column(Text)


class WorkflowPacket(TimestampMixin, Base):
    __tablename__ = "workflow_packets"

    id: Mapped[int] = mapped_column(primary_key=True)
    packet_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    packet_type: Mapped[str] = mapped_column(String(80), index=True)
    packet_version: Mapped[int] = mapped_column(Integer, default=1)
    parent_packet_id: Mapped[str | None] = mapped_column(String(80), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    round_id: Mapped[str | None] = mapped_column(ForeignKey("project_rounds.round_id"), index=True)
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    parameter_snapshot_json: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_summary_json: Mapped[dict] = mapped_column(JSON, default=dict)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)


class ScientificPolicy(TimestampMixin, Base):
    __tablename__ = "scientific_policies"
    __table_args__ = (UniqueConstraint("policy_name", "policy_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    policy_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    policy_name: Mapped[str] = mapped_column(String(120))
    policy_version: Mapped[str] = mapped_column(String(80))
    ranking_weights: Mapped[dict] = mapped_column(JSON, default=dict)
    hard_constraints: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_requirements: Mapped[dict] = mapped_column(JSON, default=dict)
    allowed_fallbacks: Mapped[dict] = mapped_column(JSON, default=dict)
    budget_limits: Mapped[dict] = mapped_column(JSON, default=dict)


class ApprovalEvent(TimestampMixin, Base):
    __tablename__ = "approval_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    approval_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    round_id: Mapped[str | None] = mapped_column(ForeignKey("project_rounds.round_id"), index=True)
    event_type: Mapped[str] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    requested_by: Mapped[str | None] = mapped_column(String(120))
    decided_by: Mapped[str | None] = mapped_column(String(120))
    rationale: Mapped[str | None] = mapped_column(Text)
    request_json: Mapped[dict] = mapped_column(JSON, default=dict)
    decision_json: Mapped[dict] = mapped_column(JSON, default=dict)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
