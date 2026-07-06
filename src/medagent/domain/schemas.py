from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    target_id: str | None = None
    objective: str | None = None
    constraints: dict[str, Any] = Field(default_factory=dict)


class ProjectRead(BaseModel):
    project_id: str
    name: str
    target_id: str | None
    objective: str | None
    status: str
    created_at: datetime


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)


class ConstraintRead(BaseModel):
    constraint_id: str
    label: str
    field: str | None = None
    operator: str | None = None
    value: str | None = None
    priority: int


class ChatResponse(BaseModel):
    reply: str
    intent: str
    created_constraints: list[str] = Field(default_factory=list)


class BuiltinDrugRead(BaseModel):
    drug_name: str
    drug_status: str | None = None
    mechanism: str | None = None
    indication: str | None = None
    smiles: str | None = None
    evidence_source: str | None = None


class BuiltinTargetRead(BaseModel):
    target_id: str
    name: str
    aliases: list[str]
    uniprot_id: str | None
    species: str | None
    pdb_ids: list[str]
    summary: str | None
    drugs: list[BuiltinDrugRead] = Field(default_factory=list)


class UploadedFileRead(BaseModel):
    file_id: str
    filename: str
    file_type: str
    parse_status: str


class AgentRunRead(BaseModel):
    agent_run_id: str
    agent_name: str
    model_name: str | None
    status: str
    output_json: dict[str, Any]


class ProjectStatus(BaseModel):
    project_id: str
    status: str
    agent_runs: list[AgentRunRead]


class RunPipelineRequest(BaseModel):
    mode: Literal["dry_run", "full"] = "dry_run"


class MoleculeRead(BaseModel):
    molecule_id: str
    smiles: str
    scaffold: str | None
    status: str
    labels: list[str]


class AdviceRead(BaseModel):
    suggestion_id: str
    summary: str
    suggestions: list[dict[str, Any]]


class ToolRunResult(BaseModel):
    tool_name: str
    input: dict[str, Any]
    output: dict[str, Any]
    stdout: str = ""
    stderr: str = ""
    exit_code: int
    runtime_seconds: float
