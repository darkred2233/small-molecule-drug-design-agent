"""Central LLM planner for round-level molecule generation."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from sqlalchemy.orm import Session

from medagent.db.models import (
    ADMETResult,
    AdvisorSuggestion,
    BindingSite,
    CampaignRun,
    Critique,
    DockingResult,
    Molecule,
    MoleculeProperty,
    Project,
    ProjectResource,
    ProjectRound,
    RagDocument,
    Ranking,
    RoundReport,
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
        planning_mode = "llm"
        planner_error_type: str | None = None
        try:
            llm_response = self.llm_client.generate_structured(
                prompt=prompt,
                schema=self._strategy_draft_schema(context),
                temperature=0.3,
            )
        except Exception as exc:
            planning_mode = "deterministic_fallback"
            planner_error_type = type(exc).__name__
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
        strategy["planner_metadata"] = {
            "mode": planning_mode,
            "provider": "qwen" if planning_mode == "llm" else None,
            "error_type": planner_error_type,
        }
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
        later_round = round_number > 1

        # Keep counts proportional to the available input pool and bounded for offline runs.
        base_count = max(10, min(100, max(seed_count, len(previous_ids), 1) * 10))
        campaign_config = {
            "crem": {
                "enabled": self._availability_value(tool_availability.get("crem"))
                and has_seed_source,
                "num_molecules": min(50, base_count),
                "edit_depth": 2,
            },
            "targetdiff": {
                "enabled": self._availability_value(tool_availability.get("targetdiff"))
                and bool(
                    (data_summary.get("resource_types") or {}).get("binding_pocket")
                    or data_summary.get("prepared_binding_site_count")
                    or data_summary.get("binding_site_count")
                ),
                "num_molecules": min(50, base_count),
                "sampling_mode": "balanced",
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
        available_binding_sites = [
            site
            for site in binding_sites
            if project.active_structure_id
            and site.structure_id == project.active_structure_id
            and (site.grid_box or {}).get("pocket_file")
            and (site.grid_box or {}).get("center")
            and (site.grid_box or {}).get("size")
        ]

        context: dict[str, Any] = {
            "project_objective": project.objective,
            "project_constraints": project.constraints_json or {},
            "target_id": project.target_id,
            "active_structure_id": project.active_structure_id,
            "active_binding_site_id": project.active_binding_site_id,
            "available_binding_site_ids": [
                site.binding_site_id for site in available_binding_sites
            ],
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
                "binding_site_count": len(available_binding_sites),
                "prepared_binding_site_count": sum(
                    1
                    for item in available_binding_sites
                    if item.prepared_receptor_file or item.preparation_status == "prepared"
                ),
            },
            "has_previous_round": False,
        }

        if not parent_round_id:
            return context

        parent_round = db.query(ProjectRound).filter_by(
            round_id=parent_round_id,
            project_id=project.project_id,
        ).first()
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
                "warnings": item.warnings_json or [],
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
        ranked_ids = [item.molecule_id for item in rankings]
        properties_by_id = {
            item.molecule_id: item
            for item in db.query(MoleculeProperty)
            .filter(MoleculeProperty.molecule_id.in_(ranked_ids))
            .all()
        } if ranked_ids else {}
        docking_by_id = {
            item.molecule_id: item
            for item in db.query(DockingResult).filter(
                DockingResult.round_id == parent_round_id,
                DockingResult.molecule_id.in_(ranked_ids),
            ).all()
        } if ranked_ids else {}
        admet_by_id = {
            item.molecule_id: item
            for item in db.query(ADMETResult).filter(
                ADMETResult.round_id == parent_round_id,
                ADMETResult.molecule_id.in_(ranked_ids),
            ).all()
        } if ranked_ids else {}
        synthesis_by_id = {
            item.molecule_id: item
            for item in db.query(SynthesisRoute).filter(
                SynthesisRoute.round_id == parent_round_id,
                SynthesisRoute.molecule_id.in_(ranked_ids),
            ).all()
        } if ranked_ids else {}
        critique_by_id = {
            item.molecule_id: item
            for item in db.query(Critique).filter(
                Critique.round_id == parent_round_id,
                Critique.molecule_id.in_(ranked_ids),
            ).all()
        } if ranked_ids else {}
        context["previous_top_molecules"] = [
            self._ranked_molecule_evidence(
                item,
                molecule_by_id.get(item.molecule_id),
                properties_by_id.get(item.molecule_id),
                docking_by_id.get(item.molecule_id),
                admet_by_id.get(item.molecule_id),
                synthesis_by_id.get(item.molecule_id),
                critique_by_id.get(item.molecule_id),
            )
            for item in rankings
        ]
        context["previous_ranked_molecule_ids"] = ranked_ids

        report = db.query(RoundReport).filter_by(round_id=parent_round_id).one_or_none()
        if report is not None:
            report_json = report.report_json or {}
            context["previous_report_recommendations"] = {
                "next_round_recommendations": report_json.get("next_round_recommendations", []),
                "warnings": report_json.get("warnings", []),
            }
        advisor = db.query(AdvisorSuggestion).filter_by(
            project_id=project.project_id,
            round_id=parent_round_id,
        ).order_by(AdvisorSuggestion.created_at.desc()).first()
        if advisor is not None:
            context["previous_advisor_suggestion"] = {
                "summary": advisor.summary,
                "suggestions": advisor.suggestions or [],
                "next_round_constraints": advisor.next_round_constraints or [],
                "suggested_generation_config": advisor.suggested_generation_config or {},
            }
        return context

    @staticmethod
    def _ranked_molecule_evidence(
        ranking: Ranking,
        molecule: Molecule | None,
        properties: MoleculeProperty | None,
        docking: DockingResult | None,
        admet: ADMETResult | None,
        synthesis: SynthesisRoute | None,
        critique: Critique | None,
    ) -> dict[str, Any]:
        return {
            "molecule_id": ranking.molecule_id,
            "rank": ranking.rank,
            "overall_score": ranking.overall_score,
            "final_decision": ranking.final_decision,
            "score_breakdown": ranking.score_breakdown or {},
            "smiles": molecule.smiles if molecule else None,
            "status": molecule.status if molecule else None,
            "source_agent": molecule.source_agent if molecule else None,
            "generation_method": molecule.generation_method if molecule else None,
            "properties": (
                {
                    "mw": properties.mw,
                    "logp": properties.logp,
                    "tpsa": properties.tpsa,
                    "hbd": properties.hbd,
                    "hba": properties.hba,
                    "sa_score": properties.sa_score,
                }
                if properties else None
            ),
            "docking": (
                {
                    "vina_score": docking.vina_score,
                    "cnn_score": docking.cnn_score,
                    "key_hbond_count": docking.key_hbond_count,
                    "clash_count": docking.clash_count,
                }
                if docking else None
            ),
            "admet": (
                {
                    "hERG_risk": admet.hERG_risk,
                    "Ames_risk": admet.Ames_risk,
                    "solubility": admet.solubility,
                    "permeability": admet.permeability,
                    "risk_score": admet.admet_risk_score,
                }
                if admet else None
            ),
            "synthesis": (
                {
                    "route_found": synthesis.route_found,
                    "route_steps": synthesis.route_steps,
                    "route_confidence": synthesis.route_confidence,
                }
                if synthesis else None
            ),
            "critique": (
                {
                    "risk_level": critique.risk_level,
                    "decision": critique.refutation_decision,
                    "reason": critique.reason,
                    "campaign_patch_suggestions": critique.campaign_patch_suggestions_json or {},
                }
                if critique else None
            ),
        }

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

    def _strategy_draft_schema(self, context: dict[str, Any]) -> dict[str, Any]:
        binding_site_schema = {
            "type": "string",
            "enum": list(context.get("available_binding_site_ids") or []),
        }
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
                        "targetdiff": {
                            "type": "object",
                            "properties": {
                                "enabled": {"type": "boolean"},
                                "num_molecules": {"type": "integer", "minimum": 0, "maximum": 300},
                                "sampling_mode": {
                                    "type": "string",
                                    "enum": ["fast", "balanced", "thorough"],
                                },
                                "binding_site_id": binding_site_schema,
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
                                "binding_site_id": binding_site_schema,
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
        campaign_config.setdefault("targetdiff", {})
        for method in ("crem", "targetdiff", "autogrow4"):
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
