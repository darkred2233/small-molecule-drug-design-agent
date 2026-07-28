"""Safely resume a round whose in-process background task was interrupted."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

from medagent.api.rounds_router import _run_confirmed_round
from medagent.core.config import get_settings
from medagent.db.models import CampaignRun, Project, ProjectRound, ScientificJob
from medagent.db.session import build_session_factory


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_id")
    parser.add_argument("round_id")
    args = parser.parse_args()

    settings = get_settings()
    session_factory = build_session_factory(settings)
    with session_factory() as db:
        project = db.query(Project).filter_by(project_id=args.project_id).one_or_none()
        round_obj = db.query(ProjectRound).filter_by(
            project_id=args.project_id, round_id=args.round_id
        ).one_or_none()
        if project is None or round_obj is None:
            raise SystemExit("project or round does not exist")
        if round_obj.status != "queued":
            raise SystemExit(f"round must be queued, found {round_obj.status!r}")
        if db.query(CampaignRun).filter_by(round_id=args.round_id).count():
            raise SystemExit("refusing recovery: campaign records already exist")
        if db.query(ScientificJob).filter_by(round_id=args.round_id).count():
            raise SystemExit("refusing recovery: scientific job records already exist")

        from medagent.services.round_strategy_snapshot import (
            ExecutionSnapshotError,
            validate_execution_snapshot,
        )

        try:
            snapshot = validate_execution_snapshot(round_obj.execution_config_snapshot_json)
        except ExecutionSnapshotError as exc:
            raise SystemExit(f"refusing recovery: {exc}") from exc
        conditions = dict(round_obj.user_conditions_json or {})
        conditions["recovery"] = {
            "reason": "interrupted_background_task",
            "recovered_at": datetime.now(UTC).isoformat(),
        }
        round_obj.user_conditions_json = conditions
        db.commit()

    print(
        f"resuming {args.round_id} with "
        f"{len(snapshot['resolved_seed_plan']['smiles'])} seed molecules"
    )
    _run_confirmed_round(
        project_id=args.project_id,
        round_id=args.round_id,
        settings=settings,
    )


if __name__ == "__main__":
    main()
