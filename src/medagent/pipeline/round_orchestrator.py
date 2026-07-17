"""Round + Campaign 编排器。

负责单轮运行的完整生命周期：
  create_round_draft → start_round → run campaigns → assessment → ranking → self-refutation → complete_round → create_next_round_draft
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from medagent.db.models import (
    AgentRun,
    CampaignRun,
    Molecule,
    Project,
    ProjectRound,
)
from medagent.domain.schemas import (
    AgentTask,
    AutoGrow4CampaignConfig,
    AutoGrow4ResourceBundle,
    CampaignConfig,
    CremCampaignConfig,
    Reinvent4CampaignConfig,
    RunPlan,
)
from medagent.pipeline.state import (
    CAMPAIGN_COMPLETED,
    CAMPAIGN_FAILED,
    CAMPAIGN_PENDING,
    CAMPAIGN_RUNNING,
    CAMPAIGN_SKIPPED,
    ROUND_COMPLETED,
    ROUND_DRAFT,
    ROUND_FAILED,
    ROUND_RUNNING,
)
from medagent.services.ids import new_id


class RoundOrchestrator:
    """单轮运行编排器。"""

    def __init__(self, settings: Any):
        self.settings = settings

    # ------------------------------------------------------------------
    # Round lifecycle
    # ------------------------------------------------------------------

    def create_round_draft(
        self,
        db: Session,
        project: Project,
        round_number: int,
        parent_round_id: str | None = None,
        user_conditions: dict[str, Any] | None = None,
    ) -> ProjectRound:
        """创建一轮 draft。"""
        round_id = new_id("round")
        pr = ProjectRound(
            round_id=round_id,
            project_id=project.project_id,
            round_number=round_number,
            status=ROUND_DRAFT,
            parent_round_id=parent_round_id,
            user_conditions_json=user_conditions,
        )
        db.add(pr)
        db.flush()
        return pr

    def start_round(
        self,
        db: Session,
        round_obj: ProjectRound,
        run_plan: RunPlan | None = None,
    ) -> None:
        """设置 round 为 running。"""
        round_obj.status = ROUND_RUNNING
        round_obj.started_at = datetime.now(UTC)
        if run_plan:
            round_obj.run_plan_snapshot_json = run_plan.model_dump()
        db.flush()

    def complete_round(
        self,
        db: Session,
        round_obj: ProjectRound,
    ) -> None:
        """设置 round 为 completed。"""
        round_obj.status = ROUND_COMPLETED
        round_obj.completed_at = datetime.now(UTC)
        db.flush()

    def fail_round(
        self,
        db: Session,
        round_obj: ProjectRound,
    ) -> None:
        """设置 round 为 failed。"""
        round_obj.status = ROUND_FAILED
        round_obj.completed_at = datetime.now(UTC)
        db.flush()

    # ------------------------------------------------------------------
    # Campaign execution
    # ------------------------------------------------------------------

    def run_crem_campaign(
        self,
        db: Session,
        project: Project,
        round_obj: ProjectRound,
        config: CremCampaignConfig,
        seeds: list[str],
    ) -> CampaignRun:
        """运行 CReM campaign。"""
        campaign = self._create_campaign_run(db, project, round_obj, "crem", config.model_dump())
        campaign.status = CAMPAIGN_RUNNING
        campaign.started_at = datetime.now(UTC)
        db.flush()

        try:
            from medagent.agents.crem_agent import CremAgent

            agent = CremAgent()
            task = AgentTask(
                round=round_obj.round_number,
                agent="crem",
                seed_molecules=seeds,
                constraints={},
                round_id=round_obj.round_id,
                campaign_run_id=campaign.campaign_run_id,
                campaign_config=config.model_dump(),
            )
            result = agent.run(task)

            if result.success:
                molecule_ids = self._store_agent_molecules(db, project, result, round_obj.round_id)
                campaign.output_molecule_ids = molecule_ids
                campaign.status = CAMPAIGN_COMPLETED
            else:
                campaign.status = CAMPAIGN_FAILED
                campaign.warnings_json = result.warnings

        except Exception as exc:
            campaign.status = CAMPAIGN_FAILED
            campaign.warnings_json = [f"crem_campaign_exception:{type(exc).__name__}:{exc}"]

        campaign.completed_at = datetime.now(UTC)
        db.flush()
        return campaign

    def run_reinvent4_campaign(
        self,
        db: Session,
        project: Project,
        round_obj: ProjectRound,
        config: Reinvent4CampaignConfig,
        seeds: list[str],
        reference_ligands: list[str] | None = None,
    ) -> CampaignRun:
        """运行 REINVENT4 campaign。"""
        campaign = self._create_campaign_run(db, project, round_obj, "reinvent4", config.model_dump())
        campaign.status = CAMPAIGN_RUNNING
        campaign.started_at = datetime.now(UTC)
        db.flush()

        try:
            from medagent.agents.reinvent4_agent import Reinvent4Agent

            agent = Reinvent4Agent()
            campaign_config = config.model_dump()
            if reference_ligands:
                campaign_config["reference_ligand_count"] = len(reference_ligands)

            task = AgentTask(
                round=round_obj.round_number,
                agent="reinvent4",
                seed_molecules=reference_ligands or seeds,
                constraints={},
                round_id=round_obj.round_id,
                campaign_run_id=campaign.campaign_run_id,
                campaign_config=campaign_config,
            )
            result = agent.run(task)

            if result.success:
                molecule_ids = self._store_agent_molecules(db, project, result, round_obj.round_id)
                campaign.output_molecule_ids = molecule_ids
                campaign.status = CAMPAIGN_COMPLETED

                # optional docking-informed rerank
                if config.enable_docking_rerank:
                    self._docking_rerank(db, project, round_obj, molecule_ids, config.docking_rerank_top_n)

            else:
                campaign.status = CAMPAIGN_FAILED
                campaign.warnings_json = result.warnings

        except Exception as exc:
            campaign.status = CAMPAIGN_FAILED
            campaign.warnings_json = [f"reinvent4_campaign_exception:{type(exc).__name__}:{exc}"]

        campaign.completed_at = datetime.now(UTC)
        db.flush()
        return campaign

    def run_autogrow4_campaign(
        self,
        db: Session,
        project: Project,
        round_obj: ProjectRound,
        config: AutoGrow4CampaignConfig,
        seeds: list[str],
    ) -> CampaignRun:
        """运行 AutoGrow4 campaign。"""
        campaign = self._create_campaign_run(db, project, round_obj, "autogrow4", config.model_dump())
        campaign.status = CAMPAIGN_RUNNING
        campaign.started_at = datetime.now(UTC)
        db.flush()

        try:
            from medagent.services.autogrow4_resources import resolve_autogrow4_resources

            bundle = resolve_autogrow4_resources(db, project, config)
            campaign.resource_bundle_json = bundle.model_dump()

            from medagent.agents.autogrow4_agent import AutoGrow4Agent

            agent = AutoGrow4Agent()
            task = AgentTask(
                round=round_obj.round_number,
                agent="autogrow4",
                seed_molecules=seeds,
                constraints={},
                round_id=round_obj.round_id,
                campaign_run_id=campaign.campaign_run_id,
                campaign_config=config.model_dump(),
                resource_bundle=bundle.model_dump(),
            )
            result = agent.run(task)

            if result.success:
                molecule_ids = self._store_agent_molecules(db, project, result, round_obj.round_id)
                campaign.output_molecule_ids = molecule_ids
                campaign.status = CAMPAIGN_COMPLETED
            else:
                campaign.status = CAMPAIGN_FAILED
                campaign.warnings_json = result.warnings

        except Exception as exc:
            campaign.status = CAMPAIGN_FAILED
            campaign.warnings_json = [f"autogrow4_campaign_exception:{type(exc).__name__}:{exc}"]

        campaign.completed_at = datetime.now(UTC)
        db.flush()
        return campaign

    # ------------------------------------------------------------------
    # Round assessment & ranking
    # ------------------------------------------------------------------

    def run_round_assessment(
        self,
        db: Session,
        project: Project,
        round_obj: ProjectRound,
        plan: RunPlan | None = None,
    ) -> dict:
        """评估当前 round 的分子。"""
        from medagent.services.candidate_assessment import run_project_candidate_assessment

        assessment_kwargs: dict[str, Any] = {"round_id": round_obj.round_id}
        if plan and plan.evaluation:
            assessment_kwargs["assessment_mode"] = (
                "external" if plan.evaluation.mode == "external_top_n" else plan.evaluation.mode
            )
            assessment_kwargs["external_top_n"] = plan.evaluation.top_n

        return run_project_candidate_assessment(db, project, **assessment_kwargs)

    def run_round_ranking(
        self,
        db: Session,
        project: Project,
        round_obj: ProjectRound,
    ) -> dict:
        """按 round_id 生成排名。"""
        from medagent.services.candidate_ranking import generate_project_rankings

        molecules = self.collect_round_candidates(db, project, round_obj)
        summary = generate_project_rankings(
            db,
            project,
            molecules=molecules,
            max_molecules=len(molecules),
            top_n=len(molecules) or 1,
            round_id=round_obj.round_id,
        )
        return summary.as_dict()

    def run_round_self_refutation(
        self,
        db: Session,
        project: Project,
        round_obj: ProjectRound,
    ) -> dict:
        """自我反驳，输出理化性质建议。"""
        from medagent.services.self_refutation import generate_project_critiques

        return generate_project_critiques(
            db, project, self.settings, round_id=round_obj.round_id
        )

    def collect_round_candidates(
        self,
        db: Session,
        project: Project,
        round_obj: ProjectRound,
    ) -> list[Molecule]:
        """收集当前 round 所有 campaign 的输出分子。"""
        return db.query(Molecule).filter(
            Molecule.project_id == project.project_id,
            Molecule.round_id == round_obj.round_id,
        ).all()

    # ------------------------------------------------------------------
    # Full round execution
    # ------------------------------------------------------------------

    def run_round(
        self,
        db: Session,
        project: Project,
        round_obj: ProjectRound,
        campaign_config: CampaignConfig,
        run_plan: RunPlan | None = None,
        seeds: list[str] | None = None,
        reference_ligands: list[str] | None = None,
    ) -> dict[str, Any]:
        """运行单轮完整流程。"""
        self.start_round(db, round_obj, run_plan)
        effective_seeds = seeds or []

        campaigns: dict[str, CampaignRun] = {}

        # CReM
        if campaign_config.crem.enabled:
            campaigns["crem"] = self.run_crem_campaign(
                db, project, round_obj, campaign_config.crem, effective_seeds
            )

        # REINVENT4
        if campaign_config.reinvent4.enabled:
            campaigns["reinvent4"] = self.run_reinvent4_campaign(
                db, project, round_obj, campaign_config.reinvent4,
                effective_seeds, reference_ligands
            )

        # AutoGrow4
        if campaign_config.autogrow4.enabled:
            campaigns["autogrow4"] = self.run_autogrow4_campaign(
                db, project, round_obj, campaign_config.autogrow4, effective_seeds
            )

        # 收集候选
        candidates = self.collect_round_candidates(db, project, round_obj)

        # 评估
        assessment_result = self.run_round_assessment(db, project, round_obj, run_plan)

        # 排名
        ranking_result = self.run_round_ranking(db, project, round_obj)

        # 自我反驳
        refutation_result = self.run_round_self_refutation(db, project, round_obj)

        # 完成
        self.complete_round(db, round_obj)

        # 创建下一轮 draft（不自动启动）
        next_round = self.create_round_draft(
            db, project,
            round_number=round_obj.round_number + 1,
            parent_round_id=round_obj.round_id,
        )

        return {
            "round_id": round_obj.round_id,
            "round_number": round_obj.round_number,
            "campaigns": {k: v.campaign_run_id for k, v in campaigns.items()},
            "candidate_count": len(candidates),
            "assessment": assessment_result,
            "ranking": ranking_result,
            "refutation": refutation_result,
            "next_round_draft_id": next_round.round_id,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _create_campaign_run(
        self,
        db: Session,
        project: Project,
        round_obj: ProjectRound,
        method: str,
        config: dict[str, Any],
    ) -> CampaignRun:
        """创建 CampaignRun 记录。"""
        campaign = CampaignRun(
            campaign_run_id=new_id("campaign"),
            round_id=round_obj.round_id,
            project_id=project.project_id,
            method=method,
            status=CAMPAIGN_PENDING,
            config_json=config,
        )
        db.add(campaign)
        db.flush()
        return campaign

    def _store_agent_molecules(
        self,
        db: Session,
        project: Project,
        result: Any,
        round_id: str,
    ) -> list[str]:
        """将 AgentResult 中的分子存入数据库。"""
        molecule_ids: list[str] = []
        for candidate in result.molecules:
            molecule_id = new_id("mol")
            mol = Molecule(
                molecule_id=molecule_id,
                project_id=project.project_id,
                round_id=round_id,
                smiles=candidate.smiles,
                source_agent=result.agent,
                status="generated",
                labels=list(candidate.metadata.get("labels", [])),
            )
            db.add(mol)
            molecule_ids.append(molecule_id)
        db.flush()
        return molecule_ids

    def _docking_rerank(
        self,
        db: Session,
        project: Project,
        round_obj: ProjectRound,
        molecule_ids: list[str],
        top_n: int,
    ) -> None:
        """Post-generation docking rerank（可选）。"""
        # TODO: 实现 docking-informed rerank
        # 1. 从 molecule_ids 中取 top N（按 property/SA/QED 快速筛）
        # 2. 对 top N 做 GNINA/Vina docking
        # 3. 综合 docking + ADMET + property 重新 ranking
        pass
