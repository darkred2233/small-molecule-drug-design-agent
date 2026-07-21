from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class SeedLigandInput(BaseModel):
    name: str | None = Field(default=None, max_length=160, title="种子/样例分子名称")
    smiles: str = Field(min_length=1, title="种子/样例分子 SMILES")
    source: str | None = Field(default=None, max_length=240, title="来源")
    activity_value: float | None = Field(default=None, title="活性数值")
    activity_unit: str | None = Field(default=None, max_length=40, title="活性单位")
    activity_type: str | None = Field(default=None, max_length=40, title="活性类型")


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200, title="项目名称")
    target_id: str | None = Field(default=None, title="靶点编号")
    target_name: str | None = Field(default=None, title="自定义靶点名称")
    objective: str | None = Field(default=None, title="项目目标")
    constraints: dict[str, Any] = Field(default_factory=dict, title="初始约束")
    seed_ligands: list[SeedLigandInput] = Field(default_factory=list, title="项目样例/种子分子")
    generation_config: dict[str, Any] = Field(
        default_factory=dict,
        title="Initial molecule generation and ranking configuration",
    )


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


AgentName = Literal["reinvent4", "crem", "autogrow4"]
AgentBudget = Literal["low", "medium", "high"]
EvidenceType = Literal[
    "admet_prediction",
    "advisor_rule",
    "docking_pose",
    "pose_image",
    "rag_reference",
    "sar_observation",
    "synthesis_score",
    "tool_log",
]


class AgentTask(BaseModel):
    round: int = Field(ge=1, title="优化轮次")
    agent: AgentName = Field(title="目标生成 Agent")
    seed_molecules: list[str] = Field(default_factory=list, title="本轮种子分子")
    constraints: dict[str, Any] = Field(default_factory=dict, title="生成约束")
    budget: AgentBudget = Field(default="medium", title="预算等级")
    sar_context: list[str] = Field(default_factory=list, title="SAR 上下文")
    evaluation_context: dict[str, Any] = Field(default_factory=dict, title="评估上下文")
    # Round + Campaign 扩展字段
    round_id: str | None = Field(default=None, title="轮次 ID")
    campaign_run_id: str | None = Field(default=None, title="Campaign 运行 ID")
    campaign_config: dict[str, Any] | None = Field(default=None, title="Campaign 配置")
    resource_bundle: dict[str, Any] | None = Field(default=None, title="资源包（如 AutoGrow4ResourceBundle）")


class AgentMoleculeCandidate(BaseModel):
    smiles: str = Field(title="候选分子 SMILES")
    rationale: str | None = Field(default=None, title="Agent 生成理由")
    provenance: dict[str, Any] = Field(default_factory=dict, title="生成来源与工具信息")
    metadata: dict[str, Any] = Field(default_factory=dict, title="候选分子补充信息")


class AgentResult(BaseModel):
    agent: AgentName = Field(title="生成 Agent")
    round: int = Field(ge=1, title="优化轮次")
    success: bool = Field(title="是否成功产出结果")
    status: Literal["completed", "failed", "skipped"] = Field(title="Agent 执行状态")
    molecules: list[AgentMoleculeCandidate] = Field(default_factory=list, title="候选分子")
    warnings: list[str] = Field(default_factory=list, title="警告")
    failure_reason: str | None = Field(default=None, title="失败或跳过原因")


class EvidenceRef(BaseModel):
    type: EvidenceType = Field(title="证据类型")
    source: str = Field(title="证据来源工具或模块")
    molecule_id: str | None = Field(default=None, title="关联分子编号")
    round: int | None = Field(default=None, ge=1, title="关联优化轮次")
    summary: str = Field(title="证据摘要")
    artifact_path: str | None = Field(default=None, title="证据文件路径")
    score: float | None = Field(default=None, title="证据分数")
    metadata: dict[str, Any] = Field(default_factory=dict, title="证据补充数据")


class ChatResponse(BaseModel):
    reply: str = Field(title="Agent 回复")
    intent: str = Field(title="识别意图")
    created_constraints: list[str] = Field(default_factory=list, title="新建约束编号")
    suggested_execution: bool = Field(default=False, title="是否建议执行")
    requires_confirmation: bool = Field(default=False, title="是否需要用户确认")
    warnings: list[str] = Field(default_factory=list, title="Agent 警告")


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
    pocket_summary: str | None = Field(default=None, title="口袋摘要")
    binding_sites: list[dict[str, Any]] = Field(default_factory=list, title="结构化口袋")
    sar_rules: list[dict[str, Any]] = Field(default_factory=list, title="结构化 SAR 规则")
    admet_risks: list[dict[str, Any]] = Field(default_factory=list, title="结构化 ADMET 风险")
    seed_ligand_count: int = Field(default=0, title="种子配体数量")
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
    chunk_id: str | None = Field(default=None, title="RAG chunk id")
    claim_type: str = Field(title="Claim type")
    confidence: float | None = Field(default=None, title="Evidence confidence")
    rationale: str | None = Field(default=None, title="Evidence rationale")
    document_title: str | None = Field(default=None, title="Evidence document title")
    source: str | None = Field(default=None, title="Evidence source")
    page_number: int | None = Field(default=None, title="Evidence page number")
    section: str | None = Field(default=None, title="Evidence section")
    content: str | None = Field(default=None, title="Evidence chunk content")


class RagRetrievedChunkRead(BaseModel):
    retrieval_rank: int = Field(title="Retrieval rank")
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
    retrieval_method: str = Field(title="Retrieval method")
    score_semantics: str = Field(title="Retrieval score semantics")
    embedding_model: str = Field(title="Embedding model actually used")
    rerank_model: str | None = Field(default=None, title="Rerank model actually used")
    evidence_id: str | None = Field(default=None, title="Evidence id")
    evidence_confidence: float | None = Field(default=None, title="Calibrated evidence confidence")
    evidence_confidence_semantics: str = Field(title="Evidence confidence semantics")
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
    confidence: float | None = Field(default=None, title="Calibrated evidence confidence")
    confidence_semantics: str = Field(title="Confidence semantics")
    retrieval_support_score: float = Field(title="Heuristic retrieval support score")
    retrieval_support_score_semantics: str = Field(title="Retrieval support score semantics")
    embedding_model: str = Field(title="Embedding model actually used")
    rerank_model: str | None = Field(default=None, title="Rerank model actually used")
    retrieval_method: str = Field(title="Retrieval method")
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
    site_name: str | None = Field(default=None, title="Site name")
    reference_ligand: str | None = Field(default=None, title="Reference ligand")
    source_url: str | None = Field(default=None, title="Source URL")
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
    activity_type: str | None = Field(title="实验活性终点类型，如 IC50、Ki 或 Kd")
    source: str | None = Field(title="来源文件编号")


class AgentRunRead(BaseModel):
    round_id: str | None = Field(default=None, title="Round id")
    agent_run_id: str = Field(title="Agent 运行编号")
    agent_name: str = Field(title="Agent 名称")
    model_name: str | None = Field(title="模型名称")
    status: str = Field(title="运行状态")
    input_json: dict[str, Any] = Field(default_factory=dict, title="输入 JSON")
    output_json: dict[str, Any] = Field(title="输出 JSON")


class ProjectStatus(BaseModel):
    project_id: str = Field(title="项目编号")
    status: str = Field(title="项目状态")
    agent_runs: list[AgentRunRead] = Field(title="Agent 运行记录")


class MoleculeRead(BaseModel):
    round_id: str | None = Field(default=None, title="Round id")
    molecule_id: str = Field(title="分子编号")
    smiles: str = Field(title="SMILES")
    scaffold: str | None = Field(title="骨架")
    status: str = Field(title="分子状态")
    labels: list[str] = Field(title="标签")
    source_agent: str | None = Field(default=None, title="来源 Agent")
    campaign_run_id: str | None = Field(default=None, title="Campaign 运行编号")
    generation_method: str | None = Field(default=None, title="生成方法")
    parent_molecule_ids: list[str] = Field(default_factory=list, title="父分子编号")
    provenance_json: dict[str, Any] = Field(default_factory=dict, title="生成溯源")
    generation_metadata_json: dict[str, Any] = Field(default_factory=dict, title="生成元数据")


class MoleculeImportResponse(BaseModel):
    imported_count: int = Field(title="导入数量")
    duplicate_count: int = Field(title="重复跳过数量")
    invalid_count: int = Field(title="非法跳过数量")
    imported_molecule_ids: list[str] = Field(title="已导入分子编号")
    skipped: list[dict[str, Any]] = Field(title="跳过明细")


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
    warning_count: int = Field(default=0, title="Warning-pass molecule count")
    skipped_count: int = Field(title="Skipped molecule count")
    result_ids: list[str] = Field(title="Rule filter result ids")
    passed_molecule_ids: list[str] = Field(title="Passed molecule ids")
    failed_molecule_ids: list[str] = Field(title="Failed molecule ids")
    warning_molecule_ids: list[str] = Field(default_factory=list, title="Warning-pass molecule ids")
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
    round_id: str | None = Field(default=None, title="Round id")
    molecule_ids: list[str] | None = Field(default=None, title="Molecule ids to evaluate")
    max_molecules: int = Field(default=50, ge=1, le=500, title="Maximum molecules to evaluate")
    top_n: int | None = Field(default=None, ge=1, le=500, title="Maximum rankings to store")
    assessment_mode: Literal["fast", "external", "full"] = Field(
        default="external",
        title="Candidate assessment mode",
    )
    external_top_n: int = Field(
        default=10,
        ge=1,
        le=100,
        title="Top-ranked molecules to refine with external tools in external mode",
    )
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
    enable_external_synthesis_routes: bool = Field(
        default=True,
        title="Whether external retrosynthesis route prediction is allowed",
        description=(
            "SA/synthesis feasibility still runs in every assessment; this flag only controls "
            "external retrosynthesis route prediction."
        ),
    )
    skip_docking: bool = Field(default=False, title="Skip docking assessment")
    skip_admet: bool = Field(default=False, title="Skip ADMET assessment")
    skip_synthesis: bool = Field(default=False, title="Skip synthesis assessment")
    skip_ranking: bool = Field(
        default=False,
        title="Skip candidate ranking",
        description=(
            "When true, conformer/docking/ADMET/synthesis assessment runs without writing "
            "candidate ranking rows."
        ),
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


    round_id: str | None = Field(default=None, title="Round id")
    execution_mode: str = Field(default="not_run", title="Execution mode")
    external_tools_requested: bool = Field(
        default=False,
        title="Whether external tools were requested",
    )
    external_tools_enabled: bool = Field(
        default=False,
        title="Whether external tools were available/enabled for this stage",
    )
    external_attempted_count: int = Field(
        default=0,
        title="External tool attempt count",
    )
    external_success_count: int = Field(
        default=0,
        title="External tool success count",
    )
    surrogate_count: int = Field(default=0, title="Surrogate result count")
    fallback_count: int = Field(default=0, title="Fallback result count")
    fallback_used: bool = Field(default=False, title="Whether fallback was used")


class CoarseScreenSummary(BaseModel):
    requested_count: int = Field(title="Coarse-screen requested molecule count")
    passed_count: int = Field(title="Coarse-screen passed molecule count")
    failed_count: int = Field(title="Coarse-screen failed molecule count")
    passed_molecule_ids: list[str] = Field(title="Coarse-screen passed molecule ids")
    failed_molecule_ids: list[str] = Field(title="Coarse-screen failed molecule ids")
    failure_reasons_by_id: dict[str, list[str]] = Field(
        default_factory=dict,
        title="Coarse-screen failure reasons by molecule id",
    )


class CandidateAssessmentRunResponse(BaseModel):
    round_id: str | None = Field(default=None, title="Round id")
    project_id: str = Field(title="Project id")
    assessment_mode: Literal["fast", "external", "full"] = Field(
        default="external",
        title="Candidate assessment mode",
    )
    external_top_n: int = Field(default=10, title="External refinement top N")
    external_synthesis_routes_enabled: bool = Field(
        default=True,
        title="Whether external retrosynthesis route prediction was enabled",
    )
    skipped_stages: list[str] = Field(default_factory=list, title="Skipped assessment stages")
    ranking_skipped: bool = Field(default=False, title="Whether ranking was skipped")
    runtime_policy: dict[str, Any] = Field(
        default_factory=dict,
        title="Assessment runtime policy",
    )
    conformer: AssessmentStageSummary = Field(title="Conformer generation summary")
    docking: AssessmentStageSummary = Field(title="Docking summary")
    admet: AssessmentStageSummary = Field(title="ADMET summary")
    synthesis: AssessmentStageSummary = Field(title="Synthesis summary")
    ranking: AssessmentStageSummary = Field(title="Candidate ranking summary")
    coarse_screen: CoarseScreenSummary = Field(title="Coarse-screen summary")
    tool_status: dict[str, Any] = Field(title="Candidate assessment tool status")


class RankingGenerateRequest(BaseModel):
    round_id: str | None = Field(default=None, title="Round id")
    molecule_ids: list[str] | None = Field(default=None, title="Molecule ids to rank")
    max_molecules: int = Field(default=50, ge=1, le=500, title="Maximum molecules to rank")
    top_n: int = Field(default=50, ge=1, le=500, title="Maximum rankings to store")


class RankingRunResponse(BaseModel):
    project_id: str = Field(title="Project id")
    ranking: AssessmentStageSummary = Field(title="Candidate ranking summary")


class ConformerResultRead(BaseModel):
    round_id: str | None = Field(default=None, title="Round id")
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
    round_id: str | None = Field(default=None, title="Round id")
    molecule_id: str = Field(title="Molecule id")
    vina_score: float | None = Field(title="Vina score")
    cnn_score: float | None = Field(title="GNINA CNN score")
    diffdock_confidence: float | None = Field(title="DiffDock pose confidence")
    key_hbond_count: int | None = Field(title="Key hydrogen bond count")
    clash_count: int | None = Field(title="Clash count")
    pose_file: str | None = Field(title="Pose file")
    labels: list[str] = Field(title="Docking labels")
    raw_output: dict[str, Any] = Field(title="Raw docking output and provenance")


class ADMETResultRead(BaseModel):
    round_id: str | None = Field(default=None, title="Round id")
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
    round_id: str | None = Field(default=None, title="Round id")
    molecule_id: str = Field(title="Molecule id")
    route_found: bool = Field(title="Whether route was found")
    route_steps: int | None = Field(title="Route steps")
    route_confidence: float | None = Field(title="Route confidence")
    buyable_building_blocks: int | None = Field(title="Buyable building block count")
    labels: list[str] = Field(title="Synthesis labels")
    route_json: dict[str, Any] = Field(title="Route json")


class RankingRead(BaseModel):
    round_id: str | None = Field(default=None, title="Round id")
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


# ---------------------------------------------------------------------------
# Round + Campaign schemas
# ---------------------------------------------------------------------------

RoundStatus = Literal["draft", "ready", "running", "completed", "failed", "cancelled"]
CampaignStatus = Literal["pending", "running", "completed", "failed", "skipped"]
SearchIntensity = Literal["quick", "normal", "heavy"]
SourcePoolPolicy = Literal["auto", "target_ligands", "previous_top", "user_uploaded"]
Reinvent4Mode = Literal["rl_only", "light_tl_then_rl", "tl_then_rl"]


class TargetLigandRead(BaseModel):
    target_ligand_id: str = Field(title="配体编号")
    target_id: str = Field(title="靶点编号")
    name: str | None = Field(title="名称")
    smiles: str = Field(title="SMILES")
    canonical_smiles: str | None = Field(title="标准 SMILES")
    inchi_key: str | None = Field(title="InChIKey")
    source: str = Field(title="来源")
    source_id: str | None = Field(title="来源编号")
    activity_value: float | None = Field(title="活性值")
    activity_unit: str | None = Field(title="活性单位")
    activity_type: str | None = Field(title="活性类型")
    pchembl_value: float | None = Field(title="pChEMBL 值")
    assay_type: str | None = Field(title="实验类型")
    confidence_level: str = Field(title="置信度")


class ProjectResourceRead(BaseModel):
    resource_id: str = Field(title="资源编号")
    project_id: str | None = Field(title="项目编号")
    target_id: str | None = Field(title="靶点编号")
    resource_type: str = Field(title="资源类型")
    scope: str = Field(title="作用域")
    name: str = Field(title="资源名称")
    file_path: str | None = Field(title="文件路径")
    metadata_json: dict[str, Any] | None = Field(title="元数据")
    confidence_level: str | None = Field(title="置信度")
    source_url: str | None = Field(title="来源 URL")


class ProjectRoundRead(BaseModel):
    round_id: str = Field(title="轮次编号")
    project_id: str = Field(title="项目编号")
    round_number: int = Field(title="轮次序号")
    status: str = Field(title="轮次状态")
    parent_round_id: str | None = Field(title="父轮次编号")
    user_conditions_json: dict[str, Any] | None = Field(title="用户条件")
    execution_config_snapshot_json: dict[str, Any] | None = Field(title="执行配置快照")
    started_at: datetime | None = Field(title="开始时间")
    completed_at: datetime | None = Field(title="完成时间")
    created_at: datetime = Field(title="创建时间")


class RoundCreate(BaseModel):
    round_number: int = Field(ge=1, title="轮次序号")
    parent_round_id: str | None = Field(default=None, title="父轮次编号")
    user_conditions_json: dict[str, Any] | None = Field(default=None, title="用户条件")


class RoundStartRequest(BaseModel):
    campaign_config: dict[str, Any] | None = Field(default=None, title="本轮生成配置")
    assessment_config: dict[str, Any] | None = Field(default=None, title="本轮评估配置")


class CremSeedAllocation(BaseModel):
    seed_molecule_id: str = Field(title="种子分子编号")
    requested_count: int = Field(ge=1, le=500, title="请求生成数量")


class CremCampaignConfig(BaseModel):
    enabled: bool = Field(default=True, title="是否启用")
    num_molecules: int = Field(default=100, ge=0, le=500, title="生成候选数")
    seed_allocations: list[CremSeedAllocation] = Field(default_factory=list, title="种子分配")
    edit_depth: int = Field(default=2, ge=1, le=5, title="编辑深度")


class Reinvent4CampaignConfig(BaseModel):
    enabled: bool = Field(default=True, title="是否启用")
    mode: Reinvent4Mode = Field(default="rl_only", title="运行模式")
    rl_steps: int = Field(default=30, ge=5, le=200, title="RL 训练步数")
    batch_size: int = Field(default=128, ge=16, le=1024, title="RL batch size")
    sample_count: int = Field(default=100, ge=0, le=1000, title="生成候选数")
    tl_epochs: int | None = Field(default=None, ge=1, le=100, title="TL epochs")
    reward_profile: str = Field(default="default", title="reward 配置名")
    seed_similarity_min: float = Field(default=0.35, ge=0, le=1, title="seed 相似度下限")
    seed_similarity_max: float = Field(default=0.75, ge=0, le=1, title="seed 相似度上限")
    seed_similarity_penalty_low: float = Field(default=0.25, ge=0, le=1, title="低相似度惩罚阈值")
    seed_similarity_penalty_high: float = Field(default=0.85, ge=0, le=1, title="高相似度惩罚阈值")
    property_targets: dict[str, Any] = Field(default_factory=dict, title="理化性质目标范围")
    enable_docking_rerank: bool = Field(default=False, title="是否启用 docking 后处理 rerank")
    docking_rerank_top_n: int = Field(default=50, ge=10, le=200, title="docking rerank 取 top N")


class AutoGrow4CampaignConfig(BaseModel):
    enabled: bool = Field(default=True, title="是否启用")
    num_molecules: int = Field(default=100, ge=0, le=300, title="生成候选数")
    generations: int = Field(default=5, ge=1, le=50, title="遗传代数")
    search_intensity: SearchIntensity = Field(default="normal", title="搜索强度")
    source_pool_policy: SourcePoolPolicy = Field(default="auto", title="source pool 策略")
    receptor_resource_id: str | None = Field(default=None, title="receptor 资源编号")
    binding_site_id: str | None = Field(default=None, title="binding site 编号")


class AutoGrow4ResourceBundle(BaseModel):
    receptor_file: str = Field(title="receptor .pdb 文件路径")
    prepared_receptor_file: str | None = Field(default=None, title="prepared receptor 文件路径")
    binding_site_id: str | None = Field(default=None, title="binding site 编号")
    grid_center: list[float] = Field(title="docking grid center [x, y, z]")
    grid_size: list[float] = Field(title="docking grid size [sx, sy, sz]")
    source_compounds_file: str = Field(title="source_compounds.smi 文件路径")
    source_compound_count: int = Field(title="source compound 数量")
    docking_config: dict[str, Any] = Field(default_factory=dict, title="docking 配置")
    provenance: dict[str, Any] = Field(default_factory=dict, title="来源记录")


class CampaignRunRead(BaseModel):
    campaign_run_id: str = Field(title="Campaign 运行编号")
    round_id: str = Field(title="轮次编号")
    project_id: str = Field(title="项目编号")
    method: str = Field(title="生成方法")
    status: str = Field(title="运行状态")
    config_json: dict[str, Any] | None = Field(title="配置")
    resource_bundle_json: dict[str, Any] | None = Field(title="资源包")
    input_molecule_ids: list[str] = Field(title="输入分子编号")
    output_molecule_ids: list[str] = Field(title="输出分子编号")
    metrics_json: dict[str, Any] | None = Field(title="运行指标")
    warnings_json: list[str] = Field(title="警告")
    started_at: datetime | None = Field(title="开始时间")
    completed_at: datetime | None = Field(title="完成时间")
    created_at: datetime = Field(title="创建时间")


class SelfRefutationRecommendation(BaseModel):
    main_failure_modes: list[str] = Field(default_factory=list, title="主要失败模式")
    property_diagnostics: dict[str, Any] = Field(default_factory=dict, title="理化性质诊断")
    next_round_recommendations: list[dict[str, Any]] = Field(
        default_factory=list, title="下一轮建议"
    )
    campaign_patch_suggestions: dict[str, Any] = Field(
        default_factory=dict, title="Campaign 配置修改建议"
    )
    requires_user_confirmation: bool = Field(default=True, title="是否需要用户确认")


class CampaignConfig(BaseModel):
    """所有 campaign 配置的容器。"""
    crem: CremCampaignConfig = Field(default_factory=CremCampaignConfig, title="CReM 配置")
    reinvent4: Reinvent4CampaignConfig = Field(default_factory=Reinvent4CampaignConfig, title="REINVENT4 配置")
    autogrow4: AutoGrow4CampaignConfig = Field(default_factory=AutoGrow4CampaignConfig, title="AutoGrow4 配置")


# ============================================================================
# Round Strategy Schemas - 轮次策略相关
# ============================================================================


class RoundStrategyDraftRequest(BaseModel):
    """生成策略草稿请求。"""
    user_message: str | None = Field(default=None, title="用户自然语言要求")
    user_overrides: dict[str, Any] | None = Field(default=None, title="用户手动覆盖配置")


class RoundStrategyReviseRequest(BaseModel):
    """用自然语言要求中枢 Agent 修改当前策略。"""

    user_message: str = Field(min_length=1, title="用户修改要求")
    user_overrides: dict[str, Any] | None = Field(default=None, title="用户手动覆盖配置")


class SeedPolicyRead(BaseModel):
    """种子选择策略。"""
    source: str = Field(title="种子来源", description="all_seeds, top_from_previous, mixed")
    top_n: int | None = Field(default=None, title="从上轮选 Top N")
    molecule_ids: list[str] = Field(default_factory=list, title="指定进入下一轮的分子")
    description: str | None = Field(default=None, title="策略说明")


class PropertyConstraintsRead(BaseModel):
    """理化性质约束。"""
    mw_range: list[float] | None = Field(default=None, title="分子量范围 [min, max]")
    logp_range: list[float] | None = Field(default=None, title="LogP 范围 [min, max]")
    tpsa_range: list[float] | None = Field(default=None, title="TPSA 范围 [min, max]")
    hbd_range: list[int] | None = Field(default=None, title="氢键供体范围 [min, max]")
    hba_range: list[int] | None = Field(default=None, title="氢键受体范围 [min, max]")


class AssessmentConfigRead(BaseModel):
    """评估配置。"""
    mode: str = Field(title="评估模式", description="all 或 external_top_n")
    top_n: int | None = Field(default=None, title="评估 Top N 分子")
    skip_docking: bool = Field(default=False, title="跳过对接评估")
    skip_admet: bool = Field(default=False, title="跳过 ADMET 评估")
    skip_synthesis: bool = Field(default=False, title="跳过合成评估")


class RoundStrategyDraftRead(BaseModel):
    """轮次策略草稿（LLM 生成的策略）。"""
    round_id: str = Field(title="轮次编号")
    round_number: int = Field(title="轮次序号")
    objective: str = Field(title="本轮目标")
    campaign_config: dict[str, Any] = Field(title="生成配置")
    seed_policy: SeedPolicyRead | None = Field(default=None, title="种子选择策略")
    property_constraints: PropertyConstraintsRead | None = Field(default=None, title="理化性质约束")
    assessment_config: AssessmentConfigRead | None = Field(default=None, title="评估配置")
    rationale: str = Field(title="策略理由")
    warnings: list[str] = Field(default_factory=list, title="警告信息")
    requires_user_confirmation: bool = Field(default=True, title="是否需要用户确认")
    created_at: datetime = Field(title="创建时间")


class RoundStrategyConfirmRequest(BaseModel):
    """策略确认请求。"""
    confirmed: bool = Field(title="是否确认")
    user_modifications: dict[str, Any] | None = Field(default=None, title="用户修改")


class RoundStrategyExecuteResponse(BaseModel):
    """策略执行响应。"""
    round_id: str = Field(title="轮次编号")
    status: str = Field(title="执行状态")
    message: str = Field(title="执行消息")
    result: dict[str, Any] | None = Field(default=None, title="执行结果")
