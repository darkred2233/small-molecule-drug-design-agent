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


class AdviceRead(BaseModel):
    suggestion_id: str = Field(title="建议编号")
    summary: str = Field(title="建议摘要")
    suggestions: list[dict[str, Any]] = Field(title="建议列表")


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
