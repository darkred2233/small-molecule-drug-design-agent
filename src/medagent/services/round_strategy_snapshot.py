"""Canonical strategy persistence and immutable round execution snapshots."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, datetime
from typing import Any


SNAPSHOT_SCHEMA_VERSION = 1


class ExecutionSnapshotError(ValueError):
    """Raised when a confirmed execution snapshot is missing or was modified."""


def strategy_digest(strategy: dict[str, Any]) -> str:
    payload = json.dumps(
        strategy,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def persist_strategy_document(
    round_obj: Any,
    strategy: dict[str, Any],
    *,
    source: str,
    changed_at: str | None = None,
) -> tuple[int, str]:
    """Replace the one editable strategy document and advance its version if changed."""
    document = copy.deepcopy(strategy)
    digest = strategy_digest(document)
    conditions = copy.deepcopy(round_obj.user_conditions_json or {})
    previous_digest = conditions.get("strategy_hash")
    previous_version = int(conditions.get("strategy_version") or 0)
    version = previous_version if previous_digest == digest and previous_version > 0 else previous_version + 1
    timestamp = changed_at or datetime.now(UTC).isoformat()
    conditions.update(
        {
            "strategy_draft": document,
            "strategy_version": version,
            "strategy_hash": digest,
            "strategy_status": "editable",
            "strategy_last_editor": source,
            "strategy_updated_at": timestamp,
        }
    )
    round_obj.user_conditions_json = conditions
    return version, digest


def build_execution_snapshot(
    strategy: dict[str, Any],
    *,
    strategy_version: int,
    confirmed_at: str,
    parent_round_id: str | None,
    seed_smiles: list[str],
    seed_molecule_ids: list[str],
    method_seed_plans: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compile the confirmed document and resolved seeds into one immutable payload."""
    document = copy.deepcopy(strategy)
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "strategy_version": int(strategy_version),
        "strategy_hash": strategy_digest(document),
        "confirmed_at": confirmed_at,
        "strategy": document,
        "resolved_seed_plan": {
            "parent_round_id": parent_round_id,
            "policy": copy.deepcopy(document.get("seed_policy") or {}),
            "smiles": list(seed_smiles),
            "molecule_ids": list(seed_molecule_ids),
            "methods": copy.deepcopy(method_seed_plans or {}),
        },
        "consumer_map": {
            "objective": "round_audit",
            "campaign_config": "generation_campaigns",
            "seed_policy": "resolved_seed_plan",
            "property_constraints": "candidate_coarse_screen",
            "assessment_config": "candidate_assessment_and_preflight",
            "rationale": "round_audit",
            "warnings": "round_audit",
            "context_snapshot": "round_audit",
        },
    }


def validate_execution_snapshot(snapshot: object) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        raise ExecutionSnapshotError("confirmed execution snapshot is missing")
    if snapshot.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
        raise ExecutionSnapshotError("unsupported execution snapshot schema")
    strategy = snapshot.get("strategy")
    if not isinstance(strategy, dict):
        raise ExecutionSnapshotError("execution snapshot strategy is missing")
    expected = str(snapshot.get("strategy_hash") or "")
    actual = strategy_digest(strategy)
    if not expected or expected != actual:
        raise ExecutionSnapshotError("execution snapshot strategy hash mismatch")
    seed_plan = snapshot.get("resolved_seed_plan")
    if not isinstance(seed_plan, dict):
        raise ExecutionSnapshotError("execution snapshot seed plan is missing")
    if not isinstance(seed_plan.get("smiles"), list) or not isinstance(
        seed_plan.get("molecule_ids"), list
    ):
        raise ExecutionSnapshotError("execution snapshot seed plan is invalid")
    return copy.deepcopy(snapshot)
