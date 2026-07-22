"""Central LLM planner for round-level molecule generation."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from sqlalchemy.orm import Session

from medagent.db.models import (
    ADMETResult,
    BindingSite,
    CampaignRun,
    DockingResult,
    Molecule,
    Project,
    ProjectResource,
    ProjectRound,
    RagDocument,
    Ranking,
    SeedLigand,
    SynthesisRoute,
    TargetLigand,
    UploadedFile,
)
from medagent.llm.client import LLMClient, get_llm_client


class RoundStrategyAgent:
    """Analyze project data and produce an executable round strategy draft."""

    def __init__(self, llm_client: LLMClient | None = None):
        self.llm_client = llm_client or get_llm_client()

    def generate_strategy_draft(
        self,
        db: Session,
        project: Project,
        round_number: int,
        parent_round_id: str | None = None,
        user_message: str | None = None,
        tool_availability: dict[str, Any] | None = None,
        existing_strategy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        context = self._collect_context(db, project, parent_round_id)
        prompt = self._build_strategy_prompt(
            project=project,
            round_number=round_number,
            context=context,
            user_message=user_message,
            tool_availability=tool_availability or {},
            existing_strategy=existing_strategy,
        )
        try:
            llm_response = self.llm_client.generate_structured(
                prompt=prompt,
                schema=self._strategy_draft_schema(),
                temperature=0.3,
            )
        except Exception as exc:
            llm_response = self._fallback_strategy(
                context=context,
                round_number=round_number,
                tool_availability=tool_availability or {},
                user_message=user_message,
                existing_strategy=existing_strategy,
                error=exc,
            )
        strategy = self._parse_llm_response(llm_response, tool_availability or {})
        strategy["context_snapshot"] = context
        return strategy

    def _fallback_strategy(
        self,
        context: dict[str, Any],
        round_number: int,
        tool_availability: dict[str, Any],
        user_message: str | None,
        existing_strategy: dict[str, Any] | None,
        error: Exception,
    ) -> dict[str, Any]:
        """Build a bounded draft when the configured LLM cannot be reached."""
        data_summary = context.get("data_summary") or {}
        seed_count = int(data_summary.get("seed_ligand_count", 0) or 0)
        previous_ids = list(context.get("previous_ranked_molecule_ids") or [])
        previous_count = int(context.get("previous_molecule_count", 0) or 0)
        has_seed_source = bool(seed_count or previous_ids or previous_count)
        later_round = bool(previous_ids or context.get("has_previous_round"))

        # Keep counts proportional to the available input pool and bounded for offline runs.
        base_count = max(10, min(100, max(seed_count, len(previous_ids), 1) * 10))
        campaign_config = {
            "crem": {
                "enabled": self._availability_value(tool_availability.get("crem"))
                and has_seed_source,
                "num_molecules": min(50, base_count),
                "edit_depth": 2,
            },
            "reinvent4": {
                "enabled": self._availability_value(tool_availability.get("reinvent4")),
                "sample_count": base_count,
                "mode": "light_tl_then_rl" if later_round else "rl_only",
                "rl_steps": 30,
                "batch_size": 128,
            },
            "autogrow4": {
                "enabled": self._availability_value(tool_availability.get("autogrow4"))
                and bool(
                    data_summary.get("prepared_binding_site_count")
                    or data_summary.get("binding_site_count")
                ),
                "num_molecules": min(50, base_count),
                "generations": 5,
                "search_intensity": "quick",
                "source_pool_policy": "previous_top" if later_round else "auto",
            },
        }
        if existing_strategy and isinstance(existing_strategy.get("campaign_config"), dict):
            campaign_config = existing_strategy["campaign_config"]

        seed_policy: dict[str, Any]
        if later_round and previous_ids:
            seed_policy = {
                "source": "top_from_previous",
                "top_n": min(10, len(previous_ids)),
                "molecule_ids": previous_ids[:10],
                "description": "Use the highest-ranked molecules from the previous round.",
            }
        else:
            seed_policy = {"source": "all_seeds"}
        if existing_strategy and isinstance(existing_strategy.get("seed_policy"), dict):
            seed_policy = existing_strategy["seed_policy"]

        assessment_config = {
            "mode": "external_top_n",
            "top_n": min(10, max(3, (base_count + 19) // 20)),
            "skip_docking": False,
            "skip_admet": False,
            "skip_synthesis": False,
        }
        if existing_strategy and isinstance(existing_strategy.get("assessment_config"), dict):
            assessment_config = existing_strategy["assessment_config"]

        warnings = [
            "LLM strategy planning was unavailable; a deterministic fallback draft was created.",
            f"LLM error type: {type(error).__name__}",
        ]
        if not any(
            isinstance(config, dict) and config.get("enabled")
            for config in campaign_config.values()
        ):
            warnings.append("No generation tool is currently available; enable or install a tool before confirmation.")

        return {
            "objective": (
                existing_strategy.get("objective")
                if existing_strategy and existing_strategy.get("objective")
                else context.get("project_objective") or f"Plan round {round_number} molecule generation"
            ),
            "campaign_config": campaign_config,
            "seed_policy": seed_policy,
            "property_constraints": (
                existing_strategy.get("property_constraints", {})
                if existing_strategy
                else {}
            ),
            "assessment_config": assessment_config,
            "rationale": (
                "The offline fallback uses the available seed pool and prior ranking evidence. "
                "Review the draft before execution."
            ),
            "warnings": warnings + ([f"User request preserved for review: {user_message}"] if user_message else []),
            "requires_user_confirmation": True,
        }

    def _collect_context(
        self,
        db: Session,
        project: Project,
        parent_round_id: str | None,
    ) -> dict[str, Any]:
        """Collect the bounded data summary supplied to the planner."""
        target_ligands = []
        if project.target_id:
            target_ligands = db.query(TargetLigand).filter_by(target_id=project.target_id).all()
        seed_ligands = db.query(SeedLigand).filter_by(project_id=project.project_id).all()
        resources = db.query(ProjectResource).filter_by(project_id=project.project_id).all()
        uploaded_files = db.query(UploadedFile).filter_by(project_id=project.project_id).all()
        documents = db.query(RagDocument).filter_by(project_id=project.project_id).all()
        binding_sites = db.query(BindingSite).filter_by(project_id=project.project_id).all()

        context: dict[str, Any] = {
            "project_objective": project.objective,
            "project_constraints": project.constraints_json or {},
            "target_id": project.target_id,
            "data_summary": {
                "seed_ligand_count": len(seed_ligands),
                "seed_ligand_sources": dict(Counter(item.source or "unknown" for item in seed_ligands)),
                "seed_ligands_with_activity": sum(
                    1 for item in seed_ligands if item.activity_value is not None
                ),
                "target_ligand_count": len(target_ligands),
                "target_ligand_sources": dict(
                    Counter(item.source or "unknown" for item in target_ligands)
                ),
                "uploaded_file_count": len(uploaded_files),
                "uploaded_file_types": dict(Counter(item.file_type for item in uploaded_files)),
                "uploaded_file_statuses": dict(
                    Counter(item.parse_status for item in uploaded_files)
                ),
                "rag_document_count": len(documents),
                "rag_document_types": dict(Counter(item.document_type for item in documents)),
                "resource_count": len(resources),
                "resource_types": dict(Counter(item.resource_type for item in resources)),
                "resource_scopes": dict(Counter(item.scope for item in resources)),
                "binding_site_count": len(binding_sites),
                "prepared_binding_site_count": sum(
                    1
                    for item in binding_sites
                    if item.prepared_receptor_file or item.preparation_status == "prepared"
                ),
            },
            "has_previous_round": False,
        }

        if not parent_round_id:
            return context

        parent_round = db.query(ProjectRound).filter_by(round_id=parent_round_id).first()
        if not parent_round:
            return context

        context["has_previous_round"] = True
        context["parent_round_number"] = parent_round.round_number
        molecules = db.query(Molecule).filter_by(
            project_id=project.project_id,
            round_id=parent_round_id,
        ).all()
        context["previous_molecule_count"] = len(molecules)
        context["previous_status_counts"] = dict(Counter(item.status for item in molecules))

        campaigns = db.query(CampaignRun).filter_by(round_id=parent_round_id).all()
        context["previous_campaigns"] = [
            {
                "campaign_run_id": item.campaign_run_id,
                "method": item.method,
                "status": item.status,
                "input_count": len(item.input_molecule_ids or []),
                "output_count": len(item.output_molecule_ids or []),
                "metrics": item.metrics_json or {},
            }
            for item in campaigns
        ]
        context["previous_assessment_counts"] = {
            "docking": db.query(DockingResult).filter(
                DockingResult.round_id == parent_round_id
            ).count(),
            "admet": db.query(ADMETResult).filter(
                ADMETResult.round_id == parent_round_id
            ).count(),
            "synthesis": db.query(SynthesisRoute).filter(
                SynthesisRoute.round_id == parent_round_id
            ).count(),
        }

        rankings = db.query(Ranking).filter_by(round_id=parent_round_id).order_by(
            Ranking.rank.asc()
        ).limit(50).all()
        molecule_by_id = {item.molecule_id: item for item in molecules}
        context["previous_top_molecules"] = [
            {
                "molecule_id": item.molecule_id,
                "rank": item.rank,
                "overall_score": item.overall_score,
                "final_decision": item.final_decision,
                "source_agent": molecule_by_id.get(item.molecule_id).source_agent
                if molecule_by_id.get(item.molecule_id)
                else None,
            }
            for item in rankings
        ]
        context["previous_ranked_molecule_ids"] = [item.molecule_id for item in rankings]
        return context

    def _build_strategy_prompt(
        self,
        project: Project,
        round_number: int,
        context: dict[str, Any],
        user_message: str | None,
        tool_availability: dict[str, Any],
        existing_strategy: dict[str, Any] | None,
    ) -> str:
        prompt_parts = [
            "# Small-molecule drug design round planner",
            "Return only JSON matching the supplied schema.",
            f"Project: {project.name}",
            f"Target: {project.target_id or 'not specified'}",
            f"Round: {round_number}",
            "",
            "## Project and data context",
            json.dumps(context, ensure_ascii=False, indent=2, default=str),
            "",
            "## Available generation tools",
            json.dumps(
                {name: self._availability_value(value) for name, value in tool_availability.items()},
                ensure_ascii=False,
            ),
        ]
        if existing_strategy:
            prompt_parts.extend([
                "",
                "## Current strategy to revise",
                json.dumps(existing_strategy, ensure_ascii=False, indent=2, default=str),
            ])
        if user_message:
            prompt_parts.extend(["", "## User request", user_message])
        prompt_parts.extend([
            "",
            "## Planning requirements",
            "- Choose method-specific candidate counts from the available data and round number.",
            "- Use only available generation methods and respect missing seed/receptor resources.",
            "- For later rounds, select explicit molecule_ids when ranking evidence supports them.",
            "- Keep assessment scope proportional to candidate count and available tools.",
            "- Preserve user intent while making an executable, bounded plan.",
            "- The user must be able to review and override every material choice.",
        ])
        return "\n".join(prompt_parts)

    def _strategy_draft_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "objective": {"type": "string"},
                "campaign_config": {
                    "type": "object",
                    "properties": {
                        "crem": {
                            "type": "object",
                            "properties": {
                                "enabled": {"type": "boolean"},
                                "num_molecules": {"type": "integer", "minimum": 0, "maximum": 500},
                                "edit_depth": {"type": "integer", "minimum": 1, "maximum": 5},
                            },
                        },
                        "reinvent4": {
                            "type": "object",
                            "properties": {
                                "enabled": {"type": "boolean"},
                                "sample_count": {"type": "integer", "minimum": 0, "maximum": 1000},
                                "mode": {
                                    "type": "string",
                                    "enum": ["rl_only", "light_tl_then_rl", "tl_then_rl"],
                                },
                                "rl_steps": {"type": "integer", "minimum": 5, "maximum": 200},
                                "batch_size": {"type": "integer", "minimum": 16, "maximum": 1024},
                            },
                        },
                        "autogrow4": {
                            "type": "object",
                            "properties": {
                                "enabled": {"type": "boolean"},
                                "num_molecules": {"type": "integer", "minimum": 0, "maximum": 300},
                                "generations": {"type": "integer", "minimum": 1, "maximum": 50},
                                "search_intensity": {"type": "string", "enum": ["quick", "normal", "heavy"]},
                                "source_pool_policy": {
                                    "type": "string",
                                    "enum": ["auto", "target_ligands", "previous_top", "user_uploaded"],
                                },
                            },
                        },
                    },
                },
                "seed_policy": {
                    "type": "object",
                    "properties": {
                        "source": {
                            "type": "string",
                            "enum": ["all_seeds", "top_from_previous", "mixed"],
                        },
                        "top_n": {"type": "integer", "minimum": 1, "maximum": 50},
                        "molecule_ids": {"type": "array", "items": {"type": "string"}},
                        "description": {"type": "string"},
                    },
                },
                "property_constraints": {"type": "object"},
                "assessment_config": {
                    "type": "object",
                    "properties": {
                        "mode": {"type": "string", "enum": ["all", "external_top_n", "fast"]},
                        "top_n": {"type": "integer", "minimum": 1, "maximum": 200},
                        "skip_docking": {"type": "boolean"},
                        "skip_admet": {"type": "boolean"},
                        "skip_synthesis": {"type": "boolean"},
                    },
                },
                "rationale": {"type": "string"},
                "warnings": {"type": "array", "items": {"type": "string"}},
                "requires_user_confirmation": {"type": "boolean"},
            },
            "required": ["objective", "campaign_config", "rationale"],
        }

    def _parse_llm_response(
        self,
        llm_response: dict[str, Any],
        tool_availability: dict[str, Any],
    ) -> dict[str, Any]:
        strategy = dict(llm_response or {})
        campaign_config = {
            name: dict(value) if isinstance(value, dict) else {}
            for name, value in (strategy.get("campaign_config") or {}).items()
        }
        reinvent4 = campaign_config.setdefault("reinvent4", {})
        if "sample_count" not in reinvent4 and "num_molecules" in reinvent4:
            reinvent4["sample_count"] = reinvent4.pop("num_molecules")
        mode_aliases = {
            "sampling": "rl_only",
            "light_transfer": "light_tl_then_rl",
            "full_transfer": "tl_then_rl",
        }
        if reinvent4.get("mode") in mode_aliases:
            reinvent4["mode"] = mode_aliases[reinvent4["mode"]]
        for method in ("crem", "reinvent4", "autogrow4"):
            if not self._availability_value(tool_availability.get(method, False)):
                campaign_config.setdefault(method, {})["enabled"] = False
        strategy["campaign_config"] = campaign_config
        strategy.setdefault("seed_policy", {"source": "all_seeds"})
        strategy.setdefault("assessment_config", {"mode": "external_top_n", "top_n": 50})
        strategy.setdefault("warnings", [])
        strategy.setdefault("requires_user_confirmation", True)
        return strategy

    @staticmethod
    def _availability_value(value: Any) -> bool:
        if isinstance(value, dict):
            return bool(value.get("available"))
        return bool(value)
