"""Explicit contracts for reproducible scientific workflow stages.

This module deliberately separates an unavailable tool, an approximate local
calculation, and a successfully executed external tool.  Consumers must use
the evidence level and execution mode rather than inferring scientific meaning
from an arbitrary numeric field.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable


class EvidenceLevel(str, Enum):
    """The highest claim that a stage result is allowed to make."""

    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


class EvidenceKind(str, Enum):
    NOT_EXECUTED = "not_executed"
    RULE_BASED = "rule_based"
    COMPUTATIONAL = "computational"
    EXPERIMENTAL = "experimental"


def canonical_json_hash(payload: Any) -> str:
    """Hash a JSON-compatible payload with a stable representation."""
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_snapshot(paths: dict[str, str | Path | None]) -> dict[str, dict[str, Any]]:
    """Return hashes only for materialized artifacts, without inventing files."""
    artifacts: dict[str, dict[str, Any]] = {}
    for role, raw_path in paths.items():
        if not raw_path:
            continue
        path = Path(raw_path)
        if not path.is_file():
            continue
        artifacts[role] = {
            "uri": str(path.resolve()),
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
    return artifacts


@dataclass(frozen=True)
class CapabilitySnapshot:
    """Immutable environment and input readiness snapshot for one workflow round."""

    snapshot_id: str
    created_at: str
    tools: dict[str, dict[str, Any]]
    source_release_ids: tuple[str, ...]
    target_resource: dict[str, Any]
    runtime: dict[str, Any]
    licenses: dict[str, Any] = field(default_factory=dict)
    budget: dict[str, Any] = field(default_factory=dict)
    estimated_runtime: dict[str, Any] = field(default_factory=dict)
    snapshot_hash: str = ""

    @classmethod
    def create(
        cls,
        *,
        tools: dict[str, dict[str, Any]],
        source_release_ids: list[str] | tuple[str, ...] | None = None,
        target_resource: dict[str, Any] | None = None,
        runtime: dict[str, Any] | None = None,
        licenses: dict[str, Any] | None = None,
        budget: dict[str, Any] | None = None,
        estimated_runtime: dict[str, Any] | None = None,
    ) -> "CapabilitySnapshot":
        normalized_tools = {
            name: dict(value or {})
            for name, value in sorted(tools.items())
        }
        payload = {
            "tools": normalized_tools,
            "source_release_ids": sorted(source_release_ids or []),
            "target_resource": dict(target_resource or {}),
            "runtime": dict(runtime or {}),
            "licenses": dict(licenses or {}),
            "budget": dict(budget or {}),
            "estimated_runtime": dict(estimated_runtime or {}),
        }
        snapshot_hash = canonical_json_hash(payload)
        return cls(
            snapshot_id=f"CAP-{snapshot_hash[:12].upper()}",
            created_at=datetime.now(UTC).isoformat(),
            tools=normalized_tools,
            source_release_ids=tuple(payload["source_release_ids"]),
            target_resource=payload["target_resource"],
            runtime=payload["runtime"],
            licenses=payload["licenses"],
            budget=payload["budget"],
            estimated_runtime=payload["estimated_runtime"],
            snapshot_hash=snapshot_hash,
        )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def tool(self, name: str) -> dict[str, Any]:
        return self.tools.get(name, {})

    def tool_available(self, name: str) -> bool:
        return bool(self.tool(name).get("available"))


@dataclass(frozen=True)
class StagePlan:
    stage: str
    allowed: bool
    execution_mode: str
    evidence_level: EvidenceLevel
    evidence_kind: EvidenceKind
    tool_name: str | None = None
    reason_codes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    requires_approval: bool = False

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["evidence_level"] = self.evidence_level.value
        data["evidence_kind"] = self.evidence_kind.value
        return data


@dataclass(frozen=True)
class ExecutionPlan:
    capability_snapshot_id: str
    capability_snapshot_hash: str
    formal_round: bool
    formal_round_allowed: bool
    blockers: list[str]
    stages: tuple[StagePlan, ...]
    policy_name: str = "scientific_execution"
    policy_version: str = "1.0"

    def stage(self, name: str) -> StagePlan:
        for stage in self.stages:
            if stage.stage == name:
                return stage
        raise KeyError(name)

    def as_dict(self) -> dict[str, Any]:
        return {
            "capability_snapshot_id": self.capability_snapshot_id,
            "capability_snapshot_hash": self.capability_snapshot_hash,
            "formal_round": self.formal_round,
            "formal_round_allowed": self.formal_round_allowed,
            "blockers": self.blockers,
            "policy_name": self.policy_name,
            "policy_version": self.policy_version,
            "stages": [stage.as_dict() for stage in self.stages],
        }


def _tool_available(snapshot: CapabilitySnapshot, *names: str) -> tuple[str, bool]:
    for name in names:
        if snapshot.tool_available(name):
            return name, True
    return names[0], False


def build_execution_plan(
    snapshot: CapabilitySnapshot,
    *,
    formal_round: bool = False,
    require_external_evidence_for_ranking: bool = False,
) -> ExecutionPlan:
    """Plan stages solely from an immutable capability snapshot.

    The plan does not execute a tool.  It documents exactly which stage is
    blocked, unavailable, approximate, or eligible for actual computation.
    """
    resource = snapshot.target_resource
    # P2Rank produces a computational input, not experimental validation.  A
    # predicted pocket is sufficient to run computational stages when the
    # material artifacts are present; every consumer receives the warning.
    has_predicted_pocket = bool(resource.get("pocket_predicted") or resource.get("verified_pocket"))
    has_prepared_receptor = bool(resource.get("prepared_receptor"))
    has_artifact_hashes = bool(resource.get("artifact_hashes_complete"))
    source_releases_frozen = bool(snapshot.source_release_ids)

    blockers: list[str] = []
    if formal_round and not source_releases_frozen:
        blockers.append("source_releases_not_frozen")

    generation_warnings: list[str] = []
    if has_predicted_pocket:
        generation_warnings.append("predicted_not_experimentally_validated")
    else:
        generation_warnings.append("structure_conditioned_generators_blocked_without_predicted_pocket")
    generation_tool, crem_available = _tool_available(snapshot, "crem")
    targetdiff_available = snapshot.tool_available("targetdiff") and has_predicted_pocket
    autogrow_available = (
        snapshot.tool_available("autogrow4") and has_predicted_pocket and has_prepared_receptor
    )
    generation_allowed = crem_available or targetdiff_available or autogrow_available
    generation_reasons = [] if generation_allowed else ["no_generation_tool_available"]
    if not has_predicted_pocket:
        generation_reasons.append("pocket_predicted_required_for_targetdiff_or_autogrow4")
    elif not has_prepared_receptor and snapshot.tool_available("autogrow4"):
        generation_reasons.append("prepared_receptor_required_for_autogrow4")

    vina_tool, vina_available = _tool_available(snapshot, "vina")
    vina_reasons: list[str] = []
    if not has_predicted_pocket:
        vina_reasons.append("pocket_predicted_required")
    if not has_prepared_receptor:
        vina_reasons.append("prepared_receptor_required")
    if not vina_available:
        vina_reasons.append("vina_unavailable")
    vina_allowed = not vina_reasons
    vina_warnings = ["predicted_not_experimentally_validated"]

    gnina_tool, gnina_available = _tool_available(snapshot, "gnina")
    gnina_reasons: list[str] = []
    if not has_predicted_pocket:
        gnina_reasons.append("pocket_predicted_required")
    if not has_prepared_receptor:
        gnina_reasons.append("prepared_receptor_required")
    if not gnina_available:
        gnina_reasons.append("gnina_unavailable")
    gnina_allowed = not gnina_reasons
    gnina_warnings = ["predicted_not_experimentally_validated"]

    admet_tool, admet_available = _tool_available(snapshot, "admet_ai", "chemprop")
    if admet_available:
        admet_stage = StagePlan(
            "admet_batch", True, "local_model", EvidenceLevel.L2,
            EvidenceKind.COMPUTATIONAL, admet_tool,
        )
    elif snapshot.tool_available("rdkit"):
        admet_stage = StagePlan(
            "admet_batch", True, "rdkit_surrogate", EvidenceLevel.L1,
            EvidenceKind.RULE_BASED, "rdkit",
            warnings=["admet_ai_unavailable", "surrogate_result_not_external_validation"],
        )
    else:
        admet_stage = StagePlan(
            "admet_batch", False, "unavailable", EvidenceLevel.L0,
            EvidenceKind.NOT_EXECUTED, admet_tool, ["admet_ai_unavailable", "rdkit_unavailable"],
        )

    retro_tool, retro_available = _tool_available(snapshot, "aizynthfinder")
    retro_configured = bool(snapshot.tool(retro_tool).get("model_configured", retro_available))
    if retro_available and retro_configured:
        retro_stage = StagePlan(
            "retrosynthesis_batch", True, "local_model", EvidenceLevel.L2,
            EvidenceKind.COMPUTATIONAL, retro_tool,
        )
    elif snapshot.tool_available("rdkit"):
        retro_stage = StagePlan(
            "retrosynthesis_batch", True, "sa_score_only", EvidenceLevel.L1,
            EvidenceKind.RULE_BASED, "rdkit",
            warnings=["aizynthfinder_unavailable", "not_a_retrosynthesis_route"],
        )
    else:
        retro_stage = StagePlan(
            "retrosynthesis_batch", False, "unavailable", EvidenceLevel.L0,
            EvidenceKind.NOT_EXECUTED, retro_tool, ["aizynthfinder_unavailable", "rdkit_unavailable"],
        )

    structure_ready_reasons: list[str] = []
    if not has_predicted_pocket:
        structure_ready_reasons.append("pocket_predicted_required")
    if not has_prepared_receptor:
        structure_ready_reasons.append("prepared_receptor_required")
    if not has_artifact_hashes:
        structure_ready_reasons.append("artifact_hashes_incomplete")

    stages = (
        StagePlan(
            "prepare_target_resource",
            has_predicted_pocket and has_prepared_receptor and has_artifact_hashes,
            "resource_validation" if not structure_ready_reasons else "blocked",
            EvidenceLevel.L2 if not structure_ready_reasons else EvidenceLevel.L0,
            EvidenceKind.COMPUTATIONAL if not structure_ready_reasons else EvidenceKind.NOT_EXECUTED,
            reason_codes=structure_ready_reasons,
        ),
        StagePlan(
            "generate_candidates", generation_allowed, "local_generation" if generation_allowed else "unavailable",
            EvidenceLevel.L2 if generation_allowed else EvidenceLevel.L0,
            EvidenceKind.COMPUTATIONAL if generation_allowed else EvidenceKind.NOT_EXECUTED,
            generation_tool, generation_reasons, generation_warnings,
        ),
        StagePlan(
            "vina_screen", vina_allowed, "local_cli" if vina_allowed else "blocked",
            EvidenceLevel.L2 if vina_allowed else EvidenceLevel.L0,
            EvidenceKind.COMPUTATIONAL if vina_allowed else EvidenceKind.NOT_EXECUTED,
            vina_tool, vina_reasons, vina_warnings,
        ),
        StagePlan(
            "gnina_refine", gnina_allowed, "local_cli" if gnina_allowed else "unavailable",
            EvidenceLevel.L2 if gnina_allowed else EvidenceLevel.L0,
            EvidenceKind.COMPUTATIONAL if gnina_allowed else EvidenceKind.NOT_EXECUTED,
            gnina_tool, gnina_reasons, gnina_warnings,
            requires_approval=gnina_allowed,
        ),
        admet_stage,
        retro_stage,
        StagePlan(
            "ranking", not require_external_evidence_for_ranking or vina_allowed or gnina_allowed,
            "evidence_gated_ranking", EvidenceLevel.L1, EvidenceKind.RULE_BASED,
            reason_codes=(
                ["external_evidence_required_but_unavailable"]
                if require_external_evidence_for_ranking and not (vina_allowed or gnina_allowed)
                else []
            ),
        ),
        StagePlan(
            "build_round_report", True, "reporting", EvidenceLevel.L1, EvidenceKind.RULE_BASED,
        ),
    )
    return ExecutionPlan(
        capability_snapshot_id=snapshot.snapshot_id,
        capability_snapshot_hash=snapshot.snapshot_hash,
        formal_round=formal_round,
        formal_round_allowed=not blockers,
        blockers=blockers,
        stages=stages,
    )


@dataclass
class ScientificResult:
    """Uniform result contract for every scientific execution stage."""

    stage: str
    status: str
    evidence_level: EvidenceLevel
    evidence_kind: EvidenceKind
    execution_mode: str
    tool_name: str | None = None
    tool_version: str | None = None
    model_version: str | None = None
    fallback_used: bool = False
    warnings: list[str] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)
    input_artifacts: dict[str, dict[str, Any]] = field(default_factory=dict)
    output_artifacts: dict[str, dict[str, Any]] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)
    manifest_hash: str | None = None

    def __post_init__(self) -> None:
        if self.execution_mode in {"surrogate", "rdkit_surrogate", "sa_score_only"}:
            self.evidence_level = EvidenceLevel.L1
            self.evidence_kind = EvidenceKind.RULE_BASED
            self.fallback_used = True
            if "surrogate_result_not_external_validation" not in self.warnings:
                self.warnings.append("surrogate_result_not_external_validation")
        if self.status in {"unavailable", "blocked", "failed", "not_executed"}:
            self.evidence_level = EvidenceLevel.L0
            self.evidence_kind = EvidenceKind.NOT_EXECUTED
        self.manifest_hash = self.manifest_hash or canonical_json_hash(self.manifest_payload())

    @classmethod
    def unavailable(
        cls, *, stage: str, tool_name: str | None, warnings: list[str], status: str = "unavailable"
    ) -> "ScientificResult":
        return cls(
            stage=stage,
            status=status,
            evidence_level=EvidenceLevel.L0,
            evidence_kind=EvidenceKind.NOT_EXECUTED,
            execution_mode=status,
            tool_name=tool_name,
            warnings=list(warnings),
        )

    @classmethod
    def surrogate(
        cls,
        *,
        stage: str,
        tool_name: str,
        payload: dict[str, Any],
        warnings: list[str] | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> "ScientificResult":
        return cls(
            stage=stage,
            status="succeeded",
            evidence_level=EvidenceLevel.L1,
            evidence_kind=EvidenceKind.RULE_BASED,
            execution_mode="surrogate",
            tool_name=tool_name,
            fallback_used=True,
            warnings=list(warnings or []),
            parameters=dict(parameters or {}),
            payload=dict(payload),
        )

    @classmethod
    def from_adapter(
        cls,
        *,
        stage: str,
        adapter_result: Any,
        capability_snapshot: CapabilitySnapshot,
        parameters: dict[str, Any] | None = None,
        input_artifacts: dict[str, str | Path | None] | None = None,
        output_artifacts: dict[str, str | Path | None] | None = None,
    ) -> "ScientificResult":
        """Translate an adapter return value without promoting its claim level."""
        tool_name = getattr(adapter_result, "tool_name", None)
        adapter_mode = str(getattr(adapter_result, "adapter_mode", "adapter"))
        success = bool(getattr(adapter_result, "success", False))
        warnings = list(getattr(adapter_result, "warnings", []) or [])
        tool_info = capability_snapshot.tool(tool_name or "")
        data = _adapter_payload(adapter_result)
        artifact_paths = dict(output_artifacts or {})
        pose_file = getattr(adapter_result, "pose_file", None)
        if pose_file:
            artifact_paths.setdefault("pose", pose_file)
        if success:
            return cls(
                stage=stage,
                status="succeeded",
                evidence_level=EvidenceLevel.L2,
                evidence_kind=EvidenceKind.COMPUTATIONAL,
                execution_mode=adapter_mode,
                tool_name=tool_name,
                tool_version=tool_info.get("version"),
                model_version=tool_info.get("model_version"),
                warnings=warnings,
                parameters=dict(parameters or {}),
                input_artifacts=artifact_snapshot(input_artifacts or {}),
                output_artifacts=artifact_snapshot(artifact_paths),
                provenance={
                    **dict(getattr(adapter_result, "provenance", {}) or {}),
                    "command": list(getattr(adapter_result, "command", []) or []),
                    "stdout": str(getattr(adapter_result, "stdout", "") or ""),
                    "stderr": str(getattr(adapter_result, "stderr", "") or ""),
                    "exit_code": getattr(adapter_result, "exit_code", None),
                },
                payload=data,
            )
        unavailable_markers = ("unavailable", "not_found", "not_installed", "not_configured", "missing")
        status = "unavailable" if any(marker in adapter_mode for marker in unavailable_markers) else "failed"
        return cls.unavailable(
            stage=stage,
            tool_name=tool_name,
            status=status,
            warnings=warnings or [f"{stage}_adapter_{status}"],
        )

    @property
    def is_eligible_for_external_validation(self) -> bool:
        return self.status == "succeeded" and self.evidence_level in {EvidenceLevel.L2, EvidenceLevel.L3}

    def manifest_payload(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "status": self.status,
            "evidence_level": self.evidence_level.value,
            "evidence_kind": self.evidence_kind.value,
            "execution_mode": self.execution_mode,
            "tool_name": self.tool_name,
            "tool_version": self.tool_version,
            "model_version": self.model_version,
            "fallback_used": self.fallback_used,
            "warnings": self.warnings,
            "parameters": self.parameters,
            "input_artifacts": self.input_artifacts,
            "output_artifacts": self.output_artifacts,
            "provenance": self.provenance,
            "payload": self.payload,
        }

    def as_dict(self) -> dict[str, Any]:
        data = self.manifest_payload()
        data["manifest_hash"] = self.manifest_hash
        data["is_eligible_for_external_validation"] = self.is_eligible_for_external_validation
        return data


def _adapter_payload(adapter_result: Any) -> dict[str, Any]:
    if hasattr(adapter_result, "__dataclass_fields__"):
        raw = asdict(adapter_result)
    elif hasattr(adapter_result, "model_dump"):
        raw = adapter_result.model_dump(mode="json")
    elif isinstance(adapter_result, dict):
        raw = dict(adapter_result)
    else:
        raw = dict(vars(adapter_result))
    return {key: value for key, value in raw.items() if key not in {"stdout", "stderr"}}


def execute(
    stage: str,
    request: dict[str, Any],
    capability_snapshot: CapabilitySnapshot,
    executor: Callable[[dict[str, Any]], Any],
    *,
    formal_round: bool = False,
) -> ScientificResult:
    """Execute one pre-planned stage and return a truthfully typed result."""
    plan = build_execution_plan(capability_snapshot, formal_round=formal_round)
    if formal_round and not plan.formal_round_allowed:
        return ScientificResult.unavailable(
            stage=stage,
            tool_name=None,
            status="blocked",
            warnings=plan.blockers,
        )
    stage_plan = plan.stage(stage)
    if not stage_plan.allowed:
        return ScientificResult.unavailable(
            stage=stage,
            tool_name=stage_plan.tool_name,
            status="blocked",
            warnings=stage_plan.reason_codes + stage_plan.warnings,
        )
    try:
        adapter_result = executor(request)
    except Exception as exc:  # The caller receives an auditable failure rather than a fake score.
        return ScientificResult.unavailable(
            stage=stage,
            tool_name=stage_plan.tool_name,
            status="failed",
            warnings=[f"stage_execution_exception:{type(exc).__name__}", str(exc)],
        )
    return ScientificResult.from_adapter(
        stage=stage,
        adapter_result=adapter_result,
        capability_snapshot=capability_snapshot,
        parameters=request,
    )
