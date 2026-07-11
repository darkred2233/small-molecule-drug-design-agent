from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200, title="项目名称")
    target_id: str | None = Field(default=None, title="靶点编号")
    objective: str | None = Field(default=None, title="项目目标")
    constraints: dict[str, Any] = Field(default_factory=dict, title="初始约束")


class ProjectRead(BaseModel):
    project_id: str = Field(title="项目编号")
    name: str = Field(title="项目名称")
    target_id: str | None = Field(title="靶点编号")
    objective: str | None = Field(title="项目目标")
    status: str = Field(title="项目状态")
    created_at: datetime = Field(title="创建时间")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, title="用户消息", description="自然语言优化方向或问题。")


class ConstraintRead(BaseModel):
    constraint_id: str = Field(title="约束编号")
    label: str = Field(title="约束标签")
    field: str | None = Field(default=None, title="约束字段")
    operator: str | None = Field(default=None, title="操作符")
    value: str | None = Field(default=None, title="约束值")
    priority: int = Field(title="优先级")


class ChatResponse(BaseModel):
    reply: str = Field(title="Agent 回复")
    intent: str = Field(title="识别意图")
    created_constraints: list[str] = Field(default_factory=list, title="新建约束编号")


class BuiltinDrugRead(BaseModel):
    drug_name: str = Field(title="药物名称")
    drug_status: str | None = Field(default=None, title="药物状态")
    mechanism: str | None = Field(default=None, title="作用机制")
    indication: str | None = Field(default=None, title="适应症")
    smiles: str | None = Field(default=None, title="SMILES")
    canonical_smiles: str | None = Field(default=None, title="标准 SMILES")
    isomeric_smiles: str | None = Field(default=None, title="异构 SMILES")
    inchi_key: str | None = Field(default=None, title="InChIKey")
    pubchem_cid: int | None = Field(default=None, title="PubChem CID")
    evidence_source: str | None = Field(default=None, title="数据来源")


class BuiltinTargetRead(BaseModel):
    target_id: str = Field(title="靶点编号")
    name: str = Field(title="靶点名称")
    aliases: list[str] = Field(title="别名")
    uniprot_id: str | None = Field(title="UniProt 编号")
    species: str | None = Field(title="物种")
    pdb_ids: list[str] = Field(title="代表 PDB")
    summary: str | None = Field(title="靶点摘要")
    drugs: list[BuiltinDrugRead] = Field(default_factory=list, title="代表药物")


class UploadedFileRead(BaseModel):
    file_id: str = Field(title="文件编号")
    filename: str = Field(title="文件名")
    file_type: str = Field(title="文件类型")
    parse_status: str = Field(title="解析状态")


class FileParseResult(BaseModel):
    file_id: str = Field(title="文件编号")
    filename: str = Field(title="文件名")
    parse_status: str = Field(title="解析状态")
    metadata: dict[str, Any] = Field(title="解析元数据")


class RagBuildRequest(BaseModel):
    include_builtin_target: bool = Field(default=True, title="Index built-in target knowledge")
    include_uploads: bool = Field(default=True, title="Index uploaded text documents")
    file_ids: list[str] | None = Field(default=None, title="Specific uploaded file ids")
    rebuild: bool = Field(default=True, title="Replace prior RAG documents for the same source")


class RagCrawlRequest(BaseModel):
    urls: list[str] = Field(min_length=1, title="URLs to crawl and index")
    document_type: str = Field(default="web", title="Document type label")
    rebuild: bool = Field(default=True, title="Replace prior RAG documents for the same URL")


class RagDocumentRead(BaseModel):
    document_id: str = Field(title="RAG document id")
    project_id: str | None = Field(default=None, title="Project id")
    title: str = Field(title="Document title")
    source: str | None = Field(default=None, title="Document source")
    document_type: str = Field(title="Document type")
    metadata: dict[str, Any] = Field(default_factory=dict, title="Document metadata")


class RagChunkRead(BaseModel):
    chunk_id: str = Field(title="RAG chunk id")
    document_id: str = Field(title="RAG document id")
    page_number: int | None = Field(default=None, title="Page number")
    section: str | None = Field(default=None, title="Section")
    content: str = Field(title="Chunk content")
    embedding_model: str | None = Field(default=None, title="Embedding model")
    embedding_ref: str | None = Field(default=None, title="Embedding reference")
    token_count: int | None = Field(default=None, title="Token count")
    metadata: dict[str, Any] = Field(default_factory=dict, title="Chunk metadata")


class EvidenceLinkRead(BaseModel):
    evidence_id: str = Field(title="Evidence id")
    molecule_id: str | None = Field(default=None, title="Molecule id")
    chunk_id: str = Field(title="RAG chunk id")
    claim_type: str = Field(title="Claim type")
    confidence: float | None = Field(default=None, title="Evidence confidence")
    rationale: str | None = Field(default=None, title="Evidence rationale")


class RagRetrievedChunkRead(BaseModel):
    chunk_id: str = Field(title="RAG chunk id")
    document_id: str = Field(title="RAG document id")
    source_type: str = Field(title="Source type")
    title: str = Field(title="Document title")
    source: str | None = Field(default=None, title="Document source")
    page: int | None = Field(default=None, title="Page")
    section: str | None = Field(default=None, title="Section")
    vector_score: float = Field(title="Vector recall score")
    keyword_score: float = Field(title="BM25 keyword score")
    combined_score: float = Field(title="Hybrid recall score")
    rerank_score: float | None = Field(default=None, title="Rerank score")
    evidence_id: str | None = Field(default=None, title="Evidence id")
    evidence_summary: str = Field(title="Evidence summary")
    content: str = Field(title="Chunk content")


class RagQueryRequest(BaseModel):
    query: str = Field(min_length=1, title="RAG query")
    query_type: str = Field(default="general", title="Query type")
    top_k: int = Field(default=10, ge=1, le=50, title="Number of chunks to return")
    molecule_id: str | None = Field(default=None, title="Optional molecule id for evidence link")
    create_evidence: bool = Field(default=True, title="Create evidence_links records")


class RagBuildResponse(BaseModel):
    agent_run_id: str = Field(title="Agent run id")
    status: str = Field(title="Run status")
    project_id: str = Field(title="Project id")
    adapter_mode: str = Field(title="RAG adapter mode")
    document_count: int = Field(title="Indexed document count")
    chunk_count: int = Field(title="Indexed chunk count")
    documents: list[dict[str, Any]] = Field(title="Indexed document summaries")
    warnings: list[str] = Field(default_factory=list, title="Warnings")


class RagQueryResponse(BaseModel):
    agent_run_id: str = Field(title="Agent run id")
    query: str = Field(title="Query")
    query_type: str = Field(title="Query type")
    retrieved_chunks: list[RagRetrievedChunkRead] = Field(title="Retrieved chunks")
    evidence_ids: list[str] = Field(title="Evidence ids")
    confidence: float = Field(title="Retrieval confidence")
    missing_information: list[str] = Field(title="Missing information")
    adapter_mode: str = Field(title="RAG adapter mode")


class ReceptorPrepareRequest(BaseModel):
    source_file_id: str | None = Field(default=None, title="Uploaded receptor file id")
    receptor_file: str | None = Field(default=None, title="Existing receptor file path")
    binding_site_id: str | None = Field(default=None, title="Binding site id to update")
    pdb_id: str | None = Field(default=None, title="PDB id or receptor identifier")
    grid_center: list[float] | None = Field(default=None, title="Docking grid center")
    grid_size: list[float] | None = Field(default=None, title="Docking grid size")
    key_residues: list[str] = Field(default_factory=list, title="Key binding-site residues")
    prepare_for_vina: bool = Field(default=True, title="Prepare receptor for Vina PDBQT")


class BindingSiteRead(BaseModel):
    binding_site_id: str = Field(title="Binding site id")
    project_id: str | None = Field(title="Project id")
    target_id: str = Field(title="Target id")
    pdb_id: str | None = Field(title="PDB id")
    source_file_id: str | None = Field(title="Source file id")
    receptor_file: str | None = Field(title="Stored receptor file")
    prepared_receptor_file: str | None = Field(title="Prepared receptor file")
    preparation_status: str = Field(title="Preparation status")
    key_residues: list[str] = Field(title="Key residues")
    grid_box: dict[str, Any] = Field(title="Docking grid box")
    labels: list[str] = Field(default_factory=list, title="Preparation labels")
    warnings: list[str] = Field(default_factory=list, title="Preparation warnings")
    tool_status: dict[str, Any] = Field(default_factory=dict, title="Preparation tool status")


class SeedLigandRead(BaseModel):
    ligand_id: str = Field(title="种子配体编号")
    name: str | None = Field(title="名称")
    smiles: str = Field(title="SMILES")
    activity_value: float | None = Field(title="活性值")
    activity_unit: str | None = Field(title="活性单位")
    source: str | None = Field(title="来源文件编号")


class AgentRunRead(BaseModel):
    agent_run_id: str = Field(title="Agent 运行编号")
    agent_name: str = Field(title="Agent 名称")
    model_name: str | None = Field(title="模型名称")
    status: str = Field(title="运行状态")
    output_json: dict[str, Any] = Field(title="输出 JSON")


class ProjectStatus(BaseModel):
    project_id: str = Field(title="项目编号")
    status: str = Field(title="项目状态")
    agent_runs: list[AgentRunRead] = Field(title="Agent 运行记录")


class RunPipelineRequest(BaseModel):
    mode: Literal["dry_run", "full"] = Field(default="dry_run", title="运行模式")


class MoleculeRead(BaseModel):
    molecule_id: str = Field(title="分子编号")
    smiles: str = Field(title="SMILES")
    scaffold: str | None = Field(title="骨架")
    status: str = Field(title="分子状态")
    labels: list[str] = Field(title="标签")
    source_agent: str | None = Field(default=None, title="来源 Agent")


class MoleculeImportResponse(BaseModel):
    imported_count: int = Field(title="导入数量")
    duplicate_count: int = Field(title="重复跳过数量")
    invalid_count: int = Field(title="非法跳过数量")
    imported_molecule_ids: list[str] = Field(title="已导入分子编号")
    skipped: list[dict[str, Any]] = Field(title="跳过明细")


class MoleculeGenerationRequest(BaseModel):
    generation_size: int = Field(default=30, ge=1, le=500, title="Requested molecule count")
    strategies: list[Literal["reinvent4", "crem", "autogrow4"]] = Field(
        default_factory=lambda: ["reinvent4", "crem", "autogrow4"],
        title="Generation strategies",
    )
    constraints: dict[str, Any] = Field(default_factory=dict, title="Generation constraints")
    include_target_library_seeds: bool = Field(
        default=True,
        title="Use built-in target-drug library as fallback seeds",
    )


class MoleculeGenerationStrategySummary(BaseModel):
    requested_count: int = Field(title="Requested count")
    proposed_count: int = Field(title="Proposed candidate count")
    stored_count: int = Field(title="Stored molecule count")
    duplicate_count: int = Field(title="Duplicate candidate count")
    invalid_count: int = Field(title="Invalid candidate count")
    seed_count: int = Field(title="Seed count")
    molecule_ids: list[str] = Field(title="Stored molecule ids")
    adapter_mode: str = Field(title="Generation adapter mode")
    tool_status: dict[str, Any] = Field(default_factory=dict, title="Generation tool status")
    warnings: list[str] = Field(default_factory=list, title="Generation warnings")
    candidate_source_counts: dict[str, int] = Field(
        default_factory=dict,
        title="Candidate source counts",
    )


class MoleculeGenerationResponse(BaseModel):
    agent_run_id: str = Field(title="Generator agent run id")
    requested_count: int = Field(title="Requested molecule count")
    generated_count: int = Field(title="Generated candidate count")
    stored_count: int = Field(title="Stored molecule count")
    duplicate_count: int = Field(title="Duplicate candidate count")
    invalid_count: int = Field(title="Invalid candidate count")
    seed_count: int = Field(title="Seed count")
    failed_reason_summary: dict[str, int] = Field(title="Failure reason summary")
    molecule_ids: list[str] = Field(title="Stored molecule ids")
    strategy_summaries: dict[str, MoleculeGenerationStrategySummary] = Field(
        title="Per-strategy generation summaries"
    )
    adapter_mode: str = Field(title="Generation adapter mode")
    tool_status: dict[str, Any] = Field(default_factory=dict, title="Generation tool status")
    warnings: list[str] = Field(default_factory=list, title="Generation warnings")


class MoleculeValidationResponse(BaseModel):
    validated_count: int = Field(title="校验通过数量")
    invalid_count: int = Field(title="结构异常数量")
    property_count: int = Field(title="性质记录数量")
    validated_molecule_ids: list[str] = Field(title="校验通过分子编号")
    invalid_molecule_ids: list[str] = Field(title="结构异常分子编号")


class MoleculePropertyRead(BaseModel):
    molecule_id: str = Field(title="分子编号")
    mw: float | None = Field(title="估算分子量")
    logp: float | None = Field(title="LogP")
    tpsa: float | None = Field(title="TPSA")
    hbd: int | None = Field(title="氢键供体数")
    hba: int | None = Field(title="氢键受体数")
    sa_score: float | None = Field(title="合成可及性分数")
    tool_metadata: dict[str, Any] = Field(title="工具元数据")


class RuleFilterResponse(BaseModel):
    rule_set: str = Field(title="Rule set")
    evaluated_count: int = Field(title="Evaluated molecule count")
    passed_count: int = Field(title="Passed molecule count")
    failed_count: int = Field(title="Failed molecule count")
    skipped_count: int = Field(title="Skipped molecule count")
    result_ids: list[str] = Field(title="Rule filter result ids")
    passed_molecule_ids: list[str] = Field(title="Passed molecule ids")
    failed_molecule_ids: list[str] = Field(title="Failed molecule ids")
    skipped_molecule_ids: list[str] = Field(title="Skipped molecule ids")


class RuleFilterResultRead(BaseModel):
    filter_result_id: str = Field(title="Rule filter result id")
    project_id: str = Field(title="Project id")
    molecule_id: str = Field(title="Molecule id")
    rule_set: str = Field(title="Rule set")
    decision: str = Field(title="Filter decision")
    failed_rules: list[str] = Field(title="Failed rules")
    warnings: list[str] = Field(title="Warnings")
    labels: list[str] = Field(title="Labels")
    properties_snapshot: dict[str, Any] = Field(title="Properties snapshot")
    raw_output: dict[str, Any] = Field(title="Raw rule output")


class CandidateAssessmentRunRequest(BaseModel):
    molecule_ids: list[str] | None = Field(default=None, title="Molecule ids to evaluate")
    max_molecules: int = Field(default=50, ge=1, le=500, title="Maximum molecules to evaluate")
    binding_site_id: str | None = Field(default=None, title="Binding site id")
    protein_file: str | None = Field(default=None, title="Prepared receptor/protein file")
    prepared_ligand_files: dict[str, str] = Field(
        default_factory=dict,
        title="Prepared ligand files by molecule id",
    )
    grid_center: list[float] | None = Field(default=None, title="Docking grid center")
    grid_size: list[float] | None = Field(default=None, title="Docking grid size")
    key_residues: list[str] = Field(default_factory=list, title="Key binding-site residues")
    admet_properties: list[str] = Field(
        default_factory=lambda: [
            "solubility",
            "permeability",
            "hERG",
            "CYP3A4",
            "CYP2D6",
            "Ames",
            "DILI",
            "Pgp_substrate",
        ],
        title="ADMET properties",
    )
    max_synthesis_steps: int = Field(default=5, ge=1, le=12, title="Maximum synthesis steps")
    prefer_buyable_building_blocks: bool = Field(
        default=True,
        title="Prefer buyable building blocks",
    )


class AssessmentStageSummary(BaseModel):
    agent_run_id: str = Field(title="Agent run id")
    adapter_mode: str = Field(title="Adapter mode")
    requested_count: int = Field(title="Requested molecule count")
    generated_count: int = Field(default=0, title="Generated result count")
    evaluated_count: int = Field(title="Evaluated molecule count")
    skipped_count: int = Field(title="Skipped molecule count")
    failed_count: int = Field(title="Failed molecule count")
    molecule_ids: list[str] = Field(title="Evaluated molecule ids")
    skipped_molecule_ids: list[str] = Field(title="Skipped molecule ids")
    failed_molecule_ids: list[str] = Field(title="Failed molecule ids")
    warnings: list[str] = Field(default_factory=list, title="Warnings")


class CandidateAssessmentRunResponse(BaseModel):
    project_id: str = Field(title="Project id")
    conformer: AssessmentStageSummary = Field(title="Conformer generation summary")
    docking: AssessmentStageSummary = Field(title="Docking summary")
    admet: AssessmentStageSummary = Field(title="ADMET summary")
    synthesis: AssessmentStageSummary = Field(title="Synthesis summary")
    ranking: AssessmentStageSummary = Field(title="Candidate ranking summary")
    tool_status: dict[str, Any] = Field(title="Candidate assessment tool status")


class RankingGenerateRequest(BaseModel):
    molecule_ids: list[str] | None = Field(default=None, title="Molecule ids to rank")
    max_molecules: int = Field(default=50, ge=1, le=500, title="Maximum molecules to rank")
    top_n: int = Field(default=50, ge=1, le=500, title="Maximum rankings to store")


class RankingRunResponse(BaseModel):
    project_id: str = Field(title="Project id")
    ranking: AssessmentStageSummary = Field(title="Candidate ranking summary")


class ConformerResultRead(BaseModel):
    molecule_id: str = Field(title="Molecule id")
    conformer_generated: bool = Field(title="Whether conformer was generated")
    conformer_count: int | None = Field(title="Conformer count")
    lowest_energy: float | None = Field(title="Lowest conformer energy")
    strain_energy: float | None = Field(title="Strain energy")
    rmsd_between_conformers: float | None = Field(title="RMSD between conformers")
    chiral_centers: int | None = Field(title="Chiral center count")
    undefined_stereo_centers: int | None = Field(title="Undefined stereo center count")
    labels: list[str] = Field(title="Conformer labels")
    conformer_file: str | None = Field(title="Conformer file")
    raw_output: dict[str, Any] = Field(title="Raw conformer output")


class DockingResultRead(BaseModel):
    molecule_id: str = Field(title="Molecule id")
    vina_score: float | None = Field(title="Vina score")
    cnn_score: float | None = Field(title="CNN score")
    key_hbond_count: int | None = Field(title="Key hydrogen bond count")
    clash_count: int | None = Field(title="Clash count")
    pose_file: str | None = Field(title="Pose file")
    labels: list[str] = Field(title="Docking labels")


class ADMETResultRead(BaseModel):
    molecule_id: str = Field(title="Molecule id")
    hERG_probability: float | None = Field(title="hERG probability")
    hERG_risk: str | None = Field(title="hERG risk")
    Ames_probability: float | None = Field(title="Ames probability")
    Ames_risk: str | None = Field(title="Ames risk")
    solubility: str | None = Field(title="Solubility")
    permeability: str | None = Field(title="Permeability")
    admet_risk_score: float | None = Field(title="ADMET risk score")
    labels: list[str] = Field(title="ADMET labels")
    raw_output: dict[str, Any] = Field(title="Raw ADMET output")


class SynthesisRouteRead(BaseModel):
    molecule_id: str = Field(title="Molecule id")
    route_found: bool = Field(title="Whether route was found")
    route_steps: int | None = Field(title="Route steps")
    route_confidence: float | None = Field(title="Route confidence")
    buyable_building_blocks: int | None = Field(title="Buyable building block count")
    labels: list[str] = Field(title="Synthesis labels")
    route_json: dict[str, Any] = Field(title="Route json")


class RankingRead(BaseModel):
    molecule_id: str = Field(title="Molecule id")
    rank: int = Field(title="Rank")
    pro_score: float | None = Field(title="Positive evidence score")
    con_score: float | None = Field(title="Risk evidence score")
    evidence_confidence: float | None = Field(title="Evidence confidence")
    overall_score: float | None = Field(title="Overall score")
    final_decision: str = Field(title="Final decision")
    score_breakdown: dict[str, Any] = Field(title="Score breakdown")


class AdviceRead(BaseModel):
    suggestion_id: str = Field(title="建议编号")
    summary: str = Field(title="建议摘要")
    suggestions: list[dict[str, Any]] = Field(title="建议列表")


    next_round_constraints: list[dict[str, Any]] = Field(
        default_factory=list,
        title="Next-round optimization constraints",
    )
    suggested_generation_config: dict[str, Any] = Field(
        default_factory=dict,
        title="Suggested generation config",
    )


class AdvisorApplyResponse(BaseModel):
    status: str = Field(title="Apply status")
    project_id: str = Field(title="Project id")
    suggestion_id: str = Field(title="Advisor suggestion id")
    agent_run_id: str = Field(title="Apply agent run id")
    applied_constraint_count: int = Field(title="Applied next-round constraint count")
    created_constraint_count: int = Field(title="Created constraint count")
    updated_constraint_count: int = Field(title="Updated constraint count")
    unchanged_constraint_count: int = Field(title="Unchanged constraint count")
    removed_constraint_count: int = Field(title="Removed stale Advisor constraint count")
    applied_constraint_ids: list[str] = Field(title="Applied constraint ids")
    next_round_constraints: list[dict[str, Any]] = Field(
        default_factory=list,
        title="Applied next-round constraints",
    )
    suggested_generation_config: dict[str, Any] = Field(
        default_factory=dict,
        title="Suggested generation config",
    )
    generation_payload: dict[str, Any] = Field(
        default_factory=dict,
        title="Prepared next-round generation payload",
    )


class ReasoningTraceRead(BaseModel):
    trace_id: str = Field(title="Reasoning trace id")
    project_id: str = Field(title="Project id")
    molecule_id: str | None = Field(default=None, title="Molecule id")
    trace_type: str = Field(title="Trace type")
    claim: str = Field(title="User-visible claim")
    supporting_factors: list[str] = Field(title="Supporting factors")
    opposing_factors: list[str] = Field(title="Opposing factors")
    evidence_ids: list[str] = Field(title="Evidence ids")
    uncertainty: str | None = Field(default=None, title="Uncertainty")
    next_actions: list[str] = Field(title="Next actions")
    confidence: float | None = Field(default=None, title="Confidence")
    source_agent: str = Field(title="Source agent")
    provenance: dict[str, Any] = Field(title="Trace provenance")


class DecisionCardRead(BaseModel):
    decision_id: str = Field(title="Decision card id")
    project_id: str = Field(title="Project id")
    molecule_id: str | None = Field(default=None, title="Molecule id")
    trace_id: str | None = Field(default=None, title="Reasoning trace id")
    card_type: str = Field(title="Card type")
    title: str = Field(title="Card title")
    decision: str = Field(title="Decision")
    summary: str = Field(title="Summary")
    support: list[str] = Field(title="Supporting factors")
    risk: list[str] = Field(title="Risk factors")
    next_steps: list[str] = Field(title="Next steps")
    evidence_ids: list[str] = Field(title="Evidence ids")
    confidence: float | None = Field(default=None, title="Confidence")
    provenance: dict[str, Any] = Field(title="Card provenance")


class DecisionCardGenerateResponse(BaseModel):
    generated_count: int = Field(title="Generated card count")
    trace_count: int = Field(title="Generated trace count")
    decision_card_ids: list[str] = Field(title="Decision card ids")
    trace_ids: list[str] = Field(title="Reasoning trace ids")


class ToolRunResult(BaseModel):
    tool_name: str = Field(title="工具名称")
    input: dict[str, Any] = Field(title="工具输入")
    output: dict[str, Any] = Field(title="工具输出")
    stdout: str = Field(default="", title="标准输出")
    stderr: str = Field(default="", title="错误输出")
    exit_code: int = Field(title="退出码")
    runtime_seconds: float = Field(title="运行秒数")


class DatabaseSummary(BaseModel):
    target_count: int = Field(title="靶点数量")
    drug_count: int = Field(title="药物数量")
    project_count: int = Field(title="项目数量")
    molecule_count: int = Field(title="分子数量")
    target_ids: list[str] = Field(title="靶点编号列表")


class RagCollectRequest(BaseModel):
    query: str = Field(min_length=1, title="验证查询")
    query_type: str = Field(default="general", title="查询类型")
    top_k: int = Field(default=10, ge=1, le=50, title="验证查询条数")
    molecule_id: str | None = Field(default=None, title="验证证据分子编号")
    create_evidence: bool = Field(default=False, title="是否写入 evidence_links")


class RagCollectResponse(BaseModel):
    agent_run_id: str = Field(title="Agent run id")
    status: str = Field(title="Run status")
    adapter_mode: str = Field(title="RAG adapter mode")
    document_count: int = Field(title="Indexed document count")
    chunk_count: int = Field(title="Indexed chunk count")
    documents: list[dict[str, Any]] = Field(title="Indexed document summaries")
    warnings: list[str] = Field(default_factory=list, title="Warnings")
