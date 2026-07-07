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
    target_id: Mapped[str] = mapped_column(ForeignKey("targets.target_id"), index=True)
    pdb_id: Mapped[str | None] = mapped_column(String(40))
    key_residues: Mapped[list[str]] = mapped_column(JSON, default=list)
    grid_box: Mapped[dict] = mapped_column(JSON, default=dict)


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
    smiles: Mapped[str] = mapped_column(Text)
    inchi_key: Mapped[str | None] = mapped_column(String(120), index=True)
    scaffold: Mapped[str | None] = mapped_column(String(160), index=True)
    source_agent: Mapped[str | None] = mapped_column(String(120))
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


class DockingResult(TimestampMixin, Base):
    __tablename__ = "docking_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    molecule_id: Mapped[str] = mapped_column(ForeignKey("molecules.molecule_id"), index=True)
    tool_run_id: Mapped[str | None] = mapped_column(String(80))
    vina_score: Mapped[float | None] = mapped_column(Float)
    cnn_score: Mapped[float | None] = mapped_column(Float)
    key_hbond_count: Mapped[int | None] = mapped_column(Integer)
    clash_count: Mapped[int | None] = mapped_column(Integer)
    pose_file: Mapped[str | None] = mapped_column(Text)
    labels: Mapped[list[str]] = mapped_column(JSON, default=list)


class ADMETResult(TimestampMixin, Base):
    __tablename__ = "admet_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    molecule_id: Mapped[str] = mapped_column(ForeignKey("molecules.molecule_id"), index=True)
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

    id: Mapped[int] = mapped_column(primary_key=True)
    molecule_id: Mapped[str] = mapped_column(ForeignKey("molecules.molecule_id"), index=True)
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
    risk_level: Mapped[str] = mapped_column(String(80))
    reason: Mapped[str] = mapped_column(Text)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    refutation_decision: Mapped[str | None] = mapped_column(String(80))


class AdvisorSuggestion(TimestampMixin, Base):
    __tablename__ = "advisor_suggestions"

    id: Mapped[int] = mapped_column(primary_key=True)
    suggestion_id: Mapped[str] = mapped_column(String(80), unique=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    summary: Mapped[str] = mapped_column(Text)
    suggestions: Mapped[list[dict]] = mapped_column(JSON, default=list)


class Ranking(TimestampMixin, Base):
    __tablename__ = "rankings"

    id: Mapped[int] = mapped_column(primary_key=True)
    molecule_id: Mapped[str] = mapped_column(ForeignKey("molecules.molecule_id"), index=True)
    rank: Mapped[int] = mapped_column(Integer)
    pro_score: Mapped[float | None] = mapped_column(Float)
    con_score: Mapped[float | None] = mapped_column(Float)
    evidence_confidence: Mapped[float | None] = mapped_column(Float)
    overall_score: Mapped[float | None] = mapped_column(Float)
    final_decision: Mapped[str] = mapped_column(String(80))
    score_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
