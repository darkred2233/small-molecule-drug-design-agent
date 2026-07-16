"""
Report Agent

负责生成完整的项目评估报告。

功能：
1. 整合所有评估结果
2. 生成可视化图表数据
3. 导出多种格式报告
4. 提供执行摘要
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from medagent.agents.advisor import AdvisorReport
from medagent.agents.ranker import MoleculeScore, RankingResult
from medagent.db.models import (
    ADMETResult,
    Critique,
    DockingResult,
    Molecule,
    MoleculeProperty,
    Project,
    SynthesisRoute,
)
from medagent.services.docking_adapters import pose_artifact_available


@dataclass
class ExecutiveSummary:
    """执行摘要"""
    project_name: str
    report_date: str
    total_candidates: int
    excellent_candidates: int
    recommended_candidates: list[str]
    key_achievements: list[str]
    main_challenges: list[str]
    candidate_readiness_score: float
    score_semantics: str
    next_steps: list[str]


@dataclass
class MoleculeDetailedReport:
    """分子详细报告"""
    molecule_id: str
    mol_name: str
    smiles: str
    rank: int
    tier: str
    final_score: float
    structure_analysis: dict[str, Any]
    admet_analysis: dict[str, Any]
    docking_analysis: dict[str, Any]
    synthesis_analysis: dict[str, Any]
    refutation_summary: dict[str, Any] | None
    recommendation: str


@dataclass
class VisualizationData:
    """可视化数据"""
    score_distribution: dict[str, Any]
    tier_distribution: dict[str, Any]
    dimension_radar: dict[str, Any]
    top_molecules_comparison: dict[str, Any]
    admet_heatmap: dict[str, Any]


@dataclass
class ProjectReport:
    """完整项目报告"""
    executive_summary: ExecutiveSummary
    project_overview: dict[str, Any]
    ranking_summary: RankingResult | None
    advisor_report: AdvisorReport | None
    detailed_molecules: list[MoleculeDetailedReport]
    visualization_data: VisualizationData
    appendix: dict[str, Any]
    metadata: dict[str, Any]


class ReportAgent:
    """报告Agent"""

    def __init__(self, db: Session):
        self.db = db

    def generate_report(
        self,
        project: Project,
        ranking_result: RankingResult | None = None,
        advisor_report: AdvisorReport | None = None,
        include_details: bool = True,
    ) -> ProjectReport:
        """
        生成完整项目报告

        Args:
            project: 项目
            ranking_result: 排序结果
            advisor_report: 建议报告
            include_details: 是否包含详细分子报告

        Returns:
            ProjectReport
        """
        # 获取所有分子
        molecules = self.db.query(Molecule).filter_by(
            project_id=project.project_id
        ).all()

        # 生成各部分
        executive_summary = self._generate_executive_summary(
            project, molecules, ranking_result, advisor_report
        )

        project_overview = self._generate_project_overview(project, molecules)

        detailed_molecules = []
        if include_details and ranking_result:
            detailed_molecules = self._generate_detailed_reports(
                ranking_result,
                self._get_critiques_for_ranking(ranking_result),
            )

        visualization_data = self._generate_visualization_data(
            molecules, ranking_result
        )

        appendix = self._generate_appendix(project, molecules)

        metadata = {
            "report_generated_at": datetime.utcnow().isoformat(),
            "report_version": "1.0",
            "agent": "ReportAgent",
        }

        return ProjectReport(
            executive_summary=executive_summary,
            project_overview=project_overview,
            ranking_summary=ranking_result,
            advisor_report=advisor_report,
            detailed_molecules=detailed_molecules,
            visualization_data=visualization_data,
            appendix=appendix,
            metadata=metadata,
        )

    def _generate_executive_summary(
        self,
        project: Project,
        molecules: list[Molecule],
        ranking_result: RankingResult | None,
        advisor_report: AdvisorReport | None,
    ) -> ExecutiveSummary:
        """生成执行摘要"""

        # 推荐候选物
        recommended = []
        excellent_count = 0
        if ranking_result:
            excellent_count = ranking_result.excellent_count
            top_molecules = [
                m for m in ranking_result.ranked_molecules[:3]
                if m.tier == "excellent"
            ]
            recommended = [m.molecule_id for m in top_molecules]

        # 关键成就
        achievements = []
        if excellent_count > 0:
            achievements.append(f"成功识别{excellent_count}个优秀候选物")
        if len(molecules) >= 50:
            achievements.append(f"构建了包含{len(molecules)}个分子的候选库")
        if ranking_result and ranking_result.ranked_molecules:
            top_score = ranking_result.ranked_molecules[0].final_score
            if top_score >= 80:
                achievements.append(f"最佳候选物评分达到{top_score:.1f}分")

        # 主要挑战
        challenges = []
        if excellent_count == 0:
            challenges.append("尚未获得优秀级别的候选物")
        if advisor_report and advisor_report.risk_warnings:
            challenges.extend(advisor_report.risk_warnings[:2])

        # 下一步
        next_steps = []
        if advisor_report and advisor_report.action_plan:
            next_steps = [
                action.title
                for action in advisor_report.action_plan[:3]
            ]

        # 候选成熟度启发式评分；不得解释为项目成功概率
        candidate_readiness_score = 0.0
        score_semantics = "heuristic_not_probability"
        if advisor_report:
            candidate_readiness_score = advisor_report.candidate_readiness_score
            score_semantics = advisor_report.score_semantics

        return ExecutiveSummary(
            project_name=self._project_name(project),
            report_date=datetime.utcnow().strftime("%Y-%m-%d"),
            total_candidates=len(molecules),
            excellent_candidates=excellent_count,
            recommended_candidates=recommended,
            key_achievements=achievements,
            main_challenges=challenges,
            candidate_readiness_score=candidate_readiness_score,
            score_semantics=score_semantics,
            next_steps=next_steps,
        )

    def _generate_project_overview(
        self,
        project: Project,
        molecules: list[Molecule],
    ) -> dict[str, Any]:
        """生成项目概览"""

        # 统计评估完成度
        with_property = sum(1 for m in molecules if self._has_property(m))
        with_admet = sum(1 for m in molecules if self._has_admet(m))
        with_docking = sum(1 for m in molecules if self._has_docking(m))
        with_synthesis = sum(1 for m in molecules if self._has_synthesis(m))

        return {
            "project_id": project.project_id,
            "project_name": self._project_name(project),
            "target_protein": getattr(project, "target_protein", None) or project.target_id,
            "disease_area": getattr(project, "disease_area", None) or project.objective,
            "status": project.status,
            "total_molecules": len(molecules),
            "evaluation_completeness": {
                "structure_properties": {
                    "completed": with_property,
                    "total": len(molecules),
                    "percentage": round(with_property / len(molecules) * 100, 1) if molecules else 0,
                },
                "admet_prediction": {
                    "completed": with_admet,
                    "total": len(molecules),
                    "percentage": round(with_admet / len(molecules) * 100, 1) if molecules else 0,
                },
                "docking_score": {
                    "completed": with_docking,
                    "total": len(molecules),
                    "percentage": round(with_docking / len(molecules) * 100, 1) if molecules else 0,
                },
                "synthesis_assessment": {
                    "completed": with_synthesis,
                    "total": len(molecules),
                    "percentage": round(with_synthesis / len(molecules) * 100, 1) if molecules else 0,
                },
            },
        }

    def _get_critiques_for_ranking(self, ranking_result: RankingResult) -> list[Critique]:
        molecule_ids = [
            mol_score.molecule_id
            for mol_score in ranking_result.ranked_molecules[:10]
        ]
        if not molecule_ids:
            return []
        return (
            self.db.query(Critique)
            .filter(Critique.molecule_id.in_(molecule_ids))
            .all()
        )

    def _analyze_critique(self, critique: Critique) -> dict[str, Any]:
        llm_critique = critique.llm_critique_json or {}
        if not isinstance(llm_critique, dict):
            llm_critique = {}
        verdict = llm_critique.get("verdict") or {}
        decision = critique.refutation_decision or "unknown"
        assessment_map = {
            "pass": "recommended",
            "reserve": "questionable",
            "reject": "rejected",
        }
        return {
            "assessment": assessment_map.get(decision, decision),
            "decision": decision,
            "con_score": critique.con_score,
            "risk_level": critique.risk_level,
            "reason": critique.reason,
            "evidence_ids": critique.evidence_ids or [],
            "llm_provider": critique.llm_provider,
            "analysis_method": critique.analysis_method,
            "hidden_risks": llm_critique.get("hidden_risks", []),
            "evidence_concerns": llm_critique.get("evidence_concerns", []),
            "analogy_failures": llm_critique.get("analogy_failures", []),
            "verdict": verdict,
        }

    def _generate_detailed_reports(
        self,
        ranking_result: RankingResult,
        refutation_results: list[Critique] | None = None,
    ) -> list[MoleculeDetailedReport]:
        """生成详细分子报告"""

        detailed_reports: list[MoleculeDetailedReport] = []

        # 构建反驳结果字典
        refutation_dict = {}
        if refutation_results:
            refutation_dict = {r.molecule_id: r for r in refutation_results}

        # 只报告Top 10
        for mol_score in ranking_result.ranked_molecules[:10]:
            molecule = self.db.query(Molecule).filter_by(
                molecule_id=mol_score.molecule_id
            ).first()

            if not molecule:
                continue

            # 获取各项评估数据
            mol_property = self._get_property(mol_score.molecule_id)
            admet_result = self._get_admet(mol_score.molecule_id)
            docking_result = self._get_docking(mol_score.molecule_id)
            synthesis_route = self._get_synthesis(mol_score.molecule_id)

            # 结构分析
            structure_analysis = self._analyze_structure(mol_property) if mol_property else {}

            # ADMET分析
            admet_analysis = self._analyze_admet(admet_result) if admet_result else {}

            # 对接分析
            docking_analysis = self._analyze_docking(docking_result) if docking_result else {}

            # 合成分析
            synthesis_analysis = self._analyze_synthesis(synthesis_route) if synthesis_route else {}

            # 反驳总结
            refutation_summary = None
            refutation = refutation_dict.get(mol_score.molecule_id)
            if refutation:
                refutation_summary = self._analyze_critique(refutation)

            # 推荐意见
            recommendation = self._generate_molecule_recommendation(
                mol_score, refutation
            )

            detailed_reports.append(MoleculeDetailedReport(
                molecule_id=molecule.molecule_id,
                mol_name=getattr(molecule, "mol_name", None) or f"Molecule-{mol_score.rank}",
                smiles=molecule.smiles,
                rank=mol_score.rank,
                tier=mol_score.tier,
                final_score=mol_score.final_score,
                structure_analysis=structure_analysis,
                admet_analysis=admet_analysis,
                docking_analysis=docking_analysis,
                synthesis_analysis=synthesis_analysis,
                refutation_summary=refutation_summary,
                recommendation=recommendation,
            ))

        return detailed_reports

    def _analyze_structure(self, mol_property: MoleculeProperty) -> dict[str, Any]:
        """分析结构"""
        metadata = mol_property.tool_metadata or {}
        lipinski_violations = self._lipinski_violations(mol_property)
        labels = metadata.get("labels") or []
        return {
            "molecular_weight": mol_property.mw,
            "logp": mol_property.logp,
            "tpsa": mol_property.tpsa,
            "hbd": mol_property.hbd,
            "hba": mol_property.hba,
            "rotatable_bonds": metadata.get("rotatable_bond_count"),
            "qed": metadata.get("qed"),
            "lipinski_compliant": lipinski_violations == 0,
            "lipinski_violations": lipinski_violations,
            "structural_alerts": any("alert" in label for label in labels),
        }

    def _analyze_admet(self, admet_result: ADMETResult) -> dict[str, Any]:
        """分析ADMET"""
        raw_output = admet_result.raw_output or {}
        return {
            "hERG": {
                "probability": admet_result.hERG_probability,
                "risk": admet_result.hERG_risk,
            },
            "ames": {
                "probability": admet_result.Ames_probability,
                "risk": admet_result.Ames_risk,
            },
            "cyp3a4": {
                "inhibition": raw_output.get("CYP3A4_inhibition"),
                "risk": raw_output.get("CYP3A4_risk"),
            },
            "solubility": admet_result.solubility,
            "permeability": admet_result.permeability,
            "dili": {
                "probability": raw_output.get("DILI_probability"),
                "risk": raw_output.get("DILI_risk"),
            },
        }

    def _analyze_docking(self, docking_result: DockingResult) -> dict[str, Any]:
        """分析对接"""
        raw_output = docking_result.raw_output or {}
        selected_pose_rank = raw_output.get("selected_pose_rank")
        pose_selection_method = raw_output.get("pose_selection_method")
        pose_available = pose_artifact_available(docking_result.pose_file)
        best_pose_confirmed = raw_output.get("best_pose_confirmed")
        if best_pose_confirmed is None:
            best_pose_confirmed = bool(
                selected_pose_rank == 1
                and pose_selection_method
                and "not_confirmed" not in pose_selection_method
            )
        best_pose_confirmed = bool(best_pose_confirmed and pose_available)
        return {
            "tool": getattr(docking_result, "tool_name", None) or docking_result.tool_run_id,
            "vina_score": docking_result.vina_score,
            "cnn_score": docking_result.cnn_score,
            "diffdock_confidence": docking_result.diffdock_confidence,
            "cnn_affinity": getattr(docking_result, "cnn_affinity", None),
            "pose_file": docking_result.pose_file if pose_available else None,
            "pose_artifact_available": pose_available,
            "selected_pose_rank": selected_pose_rank,
            "pose_count": raw_output.get("pose_count"),
            "pose_selection_method": pose_selection_method,
            "best_pose_confirmed": best_pose_confirmed,
            "raw_output": raw_output,
        }

    def _analyze_synthesis(self, synthesis_route: SynthesisRoute) -> dict[str, Any]:
        """分析合成"""
        route_json = synthesis_route.route_json or {}
        return {
            "sa_score": route_json.get("sa_score"),
            "complexity_level": route_json.get("complexity_level"),
            "route_found": synthesis_route.route_found,
            "num_steps": synthesis_route.route_steps,
        }

    def _generate_molecule_recommendation(
        self,
        mol_score: MoleculeScore,
        refutation: Critique | None,
    ) -> str:
        """生成分子推荐意见"""

        decision = refutation.refutation_decision if refutation else "pass"
        risk_level = refutation.risk_level if refutation else "low"

        if decision == "reject" or risk_level == "high":
            return "不推荐：自我反驳发现高风险或淘汰建议，不建议继续投入资源"

        if mol_score.tier == "excellent" and decision == "pass":
            return "强烈推荐：该分子表现优异，建议优先推进合成和测试"

        elif mol_score.tier == "excellent" or mol_score.tier == "good":
            if decision == "reserve" or risk_level == "medium":
                return "谨慎推荐：分子整体良好但存在一些问题，建议优化后再推进"
            else:
                return "推荐：该分子表现良好，可列入候选清单"

        elif mol_score.tier == "acceptable":
            return "备选：分子基本可接受，建议作为备选方案或进一步优化"

        else:
            return "不推荐：分子评分较低，不建议继续投入资源"

    def _generate_visualization_data(
        self,
        molecules: list[Molecule],
        ranking_result: RankingResult | None,
    ) -> VisualizationData:
        """生成可视化数据"""

        # 评分分布
        score_distribution = self._calc_score_distribution(ranking_result)

        # 分层分布
        tier_distribution = self._calc_tier_distribution(ranking_result)

        # 雷达图数据
        dimension_radar = self._calc_dimension_radar(ranking_result)

        # Top分子对比
        top_comparison = self._calc_top_comparison(ranking_result)

        # ADMET热图
        admet_heatmap = self._calc_admet_heatmap(molecules)

        return VisualizationData(
            score_distribution=score_distribution,
            tier_distribution=tier_distribution,
            dimension_radar=dimension_radar,
            top_molecules_comparison=top_comparison,
            admet_heatmap=admet_heatmap,
        )

    def _calc_score_distribution(
        self,
        ranking_result: RankingResult | None,
    ) -> dict[str, Any]:
        """计算评分分布"""
        if not ranking_result:
            return {}

        # 分数段统计
        bins = [0, 40, 50, 65, 80, 100]
        labels = ["<40", "40-50", "50-65", "65-80", "80+"]
        distribution = {label: 0 for label in labels}

        for mol_score in ranking_result.ranked_molecules:
            score = mol_score.final_score
            for i in range(len(bins) - 1):
                if bins[i] <= score < bins[i + 1] or (i == len(bins) - 2 and score >= bins[i + 1]):
                    distribution[labels[i]] += 1
                    break

        return {
            "bins": labels,
            "counts": list(distribution.values()),
        }

    def _calc_tier_distribution(
        self,
        ranking_result: RankingResult | None,
    ) -> dict[str, Any]:
        """计算分层分布"""
        if not ranking_result:
            return {}

        return {
            "labels": ["优秀", "良好", "可接受", "较差"],
            "counts": [
                ranking_result.excellent_count,
                ranking_result.good_count,
                ranking_result.acceptable_count,
                ranking_result.poor_count,
            ],
        }

    def _calc_dimension_radar(
        self,
        ranking_result: RankingResult | None,
    ) -> dict[str, Any]:
        """计算维度雷达图"""
        if not ranking_result or not ranking_result.ranked_molecules:
            return {}

        # 取Top 3平均
        top_molecules = ranking_result.ranked_molecules[:3]

        avg_structure = sum(m.structure_score for m in top_molecules) / len(top_molecules)
        avg_admet = sum(m.admet_score for m in top_molecules) / len(top_molecules)
        avg_docking = sum(m.docking_score for m in top_molecules) / len(top_molecules)
        avg_synthesis = sum(m.synthesis_score for m in top_molecules) / len(top_molecules)

        return {
            "dimensions": ["结构", "ADMET", "对接", "合成"],
            "values": [
                round(avg_structure, 1),
                round(avg_admet, 1),
                round(avg_docking, 1),
                round(avg_synthesis, 1),
            ],
        }

    def _calc_top_comparison(
        self,
        ranking_result: RankingResult | None,
    ) -> dict[str, Any]:
        """计算Top分子对比"""
        if not ranking_result or not ranking_result.ranked_molecules:
            return {}

        top_molecules = ranking_result.ranked_molecules[:5]

        return {
            "molecules": [f"Rank {m.rank}" for m in top_molecules],
            "structure_scores": [m.structure_score for m in top_molecules],
            "admet_scores": [m.admet_score for m in top_molecules],
            "docking_scores": [m.docking_score for m in top_molecules],
            "synthesis_scores": [m.synthesis_score for m in top_molecules],
        }

    def _calc_admet_heatmap(
        self,
        molecules: list[Molecule],
    ) -> dict[str, Any]:
        """计算ADMET热图"""

        # 取前10个分子
        top_molecules = molecules[:10]

        heatmap_data = []
        properties = ["hERG", "Ames", "CYP3A4", "溶解度", "DILI"]

        for molecule in top_molecules:
            admet = self._get_admet(molecule.molecule_id)
            if not admet:
                continue
            raw_output = admet.raw_output or {}

            # 转换为0-1分数
            row = [
                self._risk_to_score(admet.hERG_risk),
                self._risk_to_score(admet.Ames_risk),
                self._risk_to_score(raw_output.get("CYP3A4_risk")),
                self._solubility_to_score(admet.solubility),
                self._risk_to_score(raw_output.get("DILI_risk")),
            ]
            heatmap_data.append(row)

        return {
            "molecules": [
                getattr(m, "mol_name", None) or m.molecule_id[:8]
                for m in top_molecules[:len(heatmap_data)]
            ],
            "properties": properties,
            "data": heatmap_data,
        }

    def _risk_to_score(self, risk: str | None) -> float:
        """风险转分数"""
        if risk == "low_risk":
            return 1.0
        elif risk == "medium_risk":
            return 0.5
        elif risk == "high_risk":
            return 0.0
        else:
            return 0.5

    def _solubility_to_score(self, solubility: str | None) -> float:
        """溶解度转分数"""
        if solubility == "high":
            return 1.0
        elif solubility == "medium":
            return 0.5
        elif solubility == "low":
            return 0.0
        else:
            return 0.5

    def _generate_appendix(
        self,
        project: Project,
        molecules: list[Molecule],
    ) -> dict[str, Any]:
        """生成附录"""
        return {
            "methodology": {
                "structure_scoring": "基于Lipinski规则、QED评分和结构警报",
                "admet_scoring": "基于hERG、Ames、DILI等多维度风险评估",
                "docking_scoring": "基于Vina评分和CNN预测置信度",
                "synthesis_scoring": "基于SA Score合成可及性评分",
            },
            "data_sources": {
                "rdkit_version": "2023.09.1",
                "chemprop_models": "预训练ADMET模型",
                "docking_tools": "GNINA/Vina/DiffDock",
            },
            "glossary": {
                "QED": "Quantitative Estimate of Drug-likeness，药物相似性定量评估",
                "SA Score": "Synthetic Accessibility Score，合成可及性评分（1-10）",
                "PAINS": "Pan-Assay Interference Compounds，泛干扰化合物",
                "hERG": "人类心脏钾离子通道，与心脏毒性相关",
                "Ames": "Ames试验，检测化合物致突变性",
                "DILI": "Drug-Induced Liver Injury，药物性肝损伤",
            },
        }

    # 辅助方法
    def _project_name(self, project: Project) -> str:
        return getattr(project, "project_name", None) or getattr(project, "name", project.project_id)

    def _lipinski_violations(self, mol_property: MoleculeProperty) -> int:
        violations = 0
        if mol_property.mw is not None and mol_property.mw > 500:
            violations += 1
        if mol_property.logp is not None and mol_property.logp > 5:
            violations += 1
        if mol_property.hbd is not None and mol_property.hbd > 5:
            violations += 1
        if mol_property.hba is not None and mol_property.hba > 10:
            violations += 1
        return violations

    def _get_property(self, molecule_id: str) -> MoleculeProperty | None:
        return self.db.query(MoleculeProperty).filter_by(molecule_id=molecule_id).first()

    def _get_admet(self, molecule_id: str) -> ADMETResult | None:
        return self.db.query(ADMETResult).filter_by(molecule_id=molecule_id).first()

    def _get_docking(self, molecule_id: str) -> DockingResult | None:
        return self.db.query(DockingResult).filter_by(molecule_id=molecule_id).first()

    def _get_synthesis(self, molecule_id: str) -> SynthesisRoute | None:
        return self.db.query(SynthesisRoute).filter_by(molecule_id=molecule_id).first()

    def _has_property(self, molecule: Molecule) -> bool:
        return self._get_property(molecule.molecule_id) is not None

    def _has_admet(self, molecule: Molecule) -> bool:
        return self._get_admet(molecule.molecule_id) is not None

    def _has_docking(self, molecule: Molecule) -> bool:
        return self._get_docking(molecule.molecule_id) is not None

    def _has_synthesis(self, molecule: Molecule) -> bool:
        return self._get_synthesis(molecule.molecule_id) is not None
