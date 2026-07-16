"""
Advisor Agent

负责提供专业建议和下一步行动方案。

功能：
1. 分析项目整体进展
2. 识别关键问题和瓶颈
3. 提供结构优化建议
4. 制定下一步行动计划
"""

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from medagent.agents.ranker import MoleculeScore, RankingResult
from medagent.db.models import (
    ADMETResult,
    DockingResult,
    Molecule,
    MoleculeProperty,
    Project,
    SynthesisRoute,
)


@dataclass
class OptimizationAdvice:
    """优化建议"""
    target: str  # molecule_id or "general"
    category: str  # structure, admet, docking, synthesis
    priority: str  # high, medium, low
    title: str
    problem: str
    suggestion: str
    rationale: str
    expected_improvement: str


@dataclass
class ActionItem:
    """行动项"""
    action_type: str  # optimize, retest, generate, synthesize
    priority: int  # 1-5
    title: str
    description: str
    target_molecules: list[str] = field(default_factory=list)
    estimated_time: str = ""
    dependencies: list[str] = field(default_factory=list)


@dataclass
class AdvisorReport:
    """建议报告"""
    project_id: str
    project_status_summary: str
    key_findings: list[str] = field(default_factory=list)
    optimization_advice: list[OptimizationAdvice] = field(default_factory=list)
    action_plan: list[ActionItem] = field(default_factory=list)
    risk_warnings: list[str] = field(default_factory=list)
    candidate_readiness_score: float = 0.0
    score_semantics: str = "heuristic_not_probability"
    next_milestone: str = ""


class AdvisorAgent:
    """建议Agent"""

    def __init__(self, db: Session):
        self.db = db

    def analyze_project(
        self,
        project: Project,
        ranking_result: RankingResult | None = None,
    ) -> AdvisorReport:
        """
        分析项目并提供建议

        Args:
            project: 项目
            ranking_result: 排序结果（可选）

        Returns:
            AdvisorReport
        """
        # 获取项目中的所有分子
        molecules = self.db.query(Molecule).filter_by(
            project_id=project.project_id
        ).all()

        # 项目状态总结
        status_summary = self._summarize_project_status(project, molecules, ranking_result)

        # 关键发现
        key_findings = self._identify_key_findings(project, molecules, ranking_result)

        # 优化建议
        optimization_advice = self._generate_optimization_advice(molecules, ranking_result)

        # 行动计划
        action_plan = self._create_action_plan(project, molecules, ranking_result)

        # 风险警告
        risk_warnings = self._identify_risks(molecules, ranking_result)

        # 候选成熟度启发式评分；不是项目成功概率
        candidate_readiness_score = self._estimate_candidate_readiness_score(
            molecules, ranking_result
        )

        # 下一个里程碑
        next_milestone = self._determine_next_milestone(project, molecules, ranking_result)

        return AdvisorReport(
            project_id=project.project_id,
            project_status_summary=status_summary,
            key_findings=key_findings,
            optimization_advice=optimization_advice,
            action_plan=action_plan,
            risk_warnings=risk_warnings,
            candidate_readiness_score=candidate_readiness_score,
            next_milestone=next_milestone,
        )

    def _summarize_project_status(
        self,
        project: Project,
        molecules: list[Molecule],
        ranking_result: RankingResult | None,
    ) -> str:
        """总结项目状态"""
        lines = [f"项目 {project.project_name} 当前状态："]

        # 分子数量
        lines.append(f"- 候选分子数量：{len(molecules)}个")

        # 排序结果
        if ranking_result:
            lines.append(f"- 优秀候选物：{ranking_result.excellent_count}个")
            lines.append(f"- 良好候选物：{ranking_result.good_count}个")
            lines.append(f"- 可接受候选物：{ranking_result.acceptable_count}个")

            if ranking_result.excellent_count > 0:
                lines.append("- 项目状态：进展良好，已有优质候选物")
            elif ranking_result.good_count > 0:
                lines.append("- 项目状态：进展正常，需要进一步优化")
            elif ranking_result.acceptable_count > 0:
                lines.append("- 项目状态：进展缓慢，候选物质量有待提升")
            else:
                lines.append("- 项目状态：需要重新设计或生成新候选物")
        else:
            lines.append("- 项目状态：评估中")

        return "\n".join(lines)

    def _identify_key_findings(
        self,
        project: Project,
        molecules: list[Molecule],
        ranking_result: RankingResult | None,
    ) -> list[str]:
        """识别关键发现"""
        findings: list[str] = []

        if not molecules:
            findings.append("项目尚未生成候选分子")
            return findings

        # 统计评估数据完整性
        with_property = sum(1 for m in molecules if self._has_property(m))
        with_admet = sum(1 for m in molecules if self._has_admet(m))
        with_docking = sum(1 for m in molecules if self._has_docking(m))
        with_synthesis = sum(1 for m in molecules if self._has_synthesis(m))

        if with_synthesis < len(molecules):
            findings.append(f"{len(molecules) - with_synthesis}个分子缺少合成评估")

        if with_property < len(molecules):
            findings.append(f"{len(molecules) - with_property}个分子缺少性质评估")

        if with_admet < len(molecules):
            findings.append(f"{len(molecules) - with_admet}个分子缺少ADMET预测")

        if with_docking < len(molecules):
            findings.append(f"{len(molecules) - with_docking}个分子缺少对接评分")

        # 分析排序结果
        if ranking_result:
            if ranking_result.excellent_count == 0 and ranking_result.good_count == 0:
                findings.append("所有候选物评分偏低，建议重新评估筛选标准")

            # 分析得分分布
            if ranking_result.ranked_molecules:
                top_score = ranking_result.ranked_molecules[0].final_score
                if top_score < 50:
                    findings.append("最高评分低于50分，候选物质量不理想")
                elif top_score >= 80:
                    findings.append(f"最佳候选物评分{top_score:.1f}分，表现优异")

        # 分析常见问题
        common_issues = self._analyze_common_issues(molecules)
        if common_issues:
            findings.extend(common_issues)

        return findings

    def _generate_optimization_advice(
        self,
        molecules: list[Molecule],
        ranking_result: RankingResult | None,
    ) -> list[OptimizationAdvice]:
        """生成优化建议"""
        advice_list: list[OptimizationAdvice] = []

        # 针对Top分子提供具体优化建议
        if ranking_result and ranking_result.ranked_molecules:
            top_molecules = ranking_result.ranked_molecules[:5]

            for mol_score in top_molecules:
                molecule = self._get_molecule(mol_score.molecule_id)
                if not molecule:
                    continue

                # 结构优化
                if mol_score.structure_score < 70:
                    advice = self._advise_structure_optimization(molecule, mol_score)
                    if advice:
                        advice_list.append(advice)

                # ADMET优化
                if mol_score.admet_score < 70:
                    advice = self._advise_admet_optimization(molecule, mol_score)
                    if advice:
                        advice_list.append(advice)

                # 对接优化
                if mol_score.docking_score < 70:
                    advice = self._advise_docking_optimization(molecule, mol_score)
                    if advice:
                        advice_list.append(advice)

                # 合成优化
                if mol_score.synthesis_score < 60:
                    advice = self._advise_synthesis_optimization(molecule, mol_score)
                    if advice:
                        advice_list.append(advice)

        # 通用建议
        general_advice = self._generate_general_advice(molecules, ranking_result)
        advice_list.extend(general_advice)

        # 按优先级排序
        priority_order = {"high": 0, "medium": 1, "low": 2}
        advice_list.sort(key=lambda x: priority_order.get(x.priority, 1))

        return advice_list

    def _advise_structure_optimization(
        self,
        molecule: Molecule,
        mol_score: MoleculeScore,
    ) -> OptimizationAdvice | None:
        """结构优化建议"""
        mol_property = self._get_property(molecule.molecule_id)
        if not mol_property:
            return None

        # 分析主要问题
        issues = []
        suggestions = []

        if not mol_property.lipinski_compliant:
            issues.append("违反Lipinski规则")
            if mol_property.mw and mol_property.mw > 500:
                suggestions.append("减小分子量：去除非必需的功能基团")
            if mol_property.logp and mol_property.logp > 5:
                suggestions.append("降低脂溶性：引入极性基团或氢键供体")
            if mol_property.hbd and mol_property.hbd > 5:
                suggestions.append("减少氢键供体数量")

        if mol_property.qed and mol_property.qed < 0.5:
            issues.append("QED评分过低")
            suggestions.append("优化分子整体药物相似性")

        if not issues:
            return None

        return OptimizationAdvice(
            target=molecule.molecule_id,
            category="structure",
            priority="high" if mol_score.structure_score < 50 else "medium",
            title=f"优化分子 {molecule.mol_name or molecule.molecule_id[:8]} 的结构",
            problem="、".join(issues),
            suggestion="；".join(suggestions),
            rationale="改善结构可提高成药性和通过临床前筛选的概率",
            expected_improvement=f"预计结构评分可提升{70 - mol_score.structure_score:.0f}分",
        )

    def _advise_admet_optimization(
        self,
        molecule: Molecule,
        mol_score: MoleculeScore,
    ) -> OptimizationAdvice | None:
        """ADMET优化建议"""
        admet_result = self._get_admet(molecule.molecule_id)
        if not admet_result:
            return None

        issues = []
        suggestions = []

        if admet_result.hERG_risk in ["high_risk", "medium_risk"]:
            issues.append("hERG心脏毒性风险")
            suggestions.append("减少碱性中心、降低LogP或引入极性基团")

        if admet_result.Ames_risk in ["high_risk", "medium_risk"]:
            issues.append("Ames致突变性风险")
            suggestions.append("去除芳香胺、硝基等警报结构")

        if admet_result.solubility == "low":
            issues.append("溶解度低")
            suggestions.append("增加极性基团或引入可电离基团")

        if not issues:
            return None

        return OptimizationAdvice(
            target=molecule.molecule_id,
            category="admet",
            priority="high" if admet_result.hERG_risk == "high_risk" else "medium",
            title=f"改善分子 {molecule.mol_name or molecule.molecule_id[:8]} 的ADMET性质",
            problem="、".join(issues),
            suggestion="；".join(suggestions),
            rationale="改善ADMET性质可降低临床失败风险",
            expected_improvement=f"预计ADMET评分可提升{70 - mol_score.admet_score:.0f}分",
        )

    def _advise_docking_optimization(
        self,
        molecule: Molecule,
        mol_score: MoleculeScore,
    ) -> OptimizationAdvice | None:
        """对接优化建议"""
        docking_result = self._get_docking(molecule.molecule_id)
        if not docking_result:
            return None

        if docking_result.vina_score and docking_result.vina_score > -7.0:
            return OptimizationAdvice(
                target=molecule.molecule_id,
                category="docking",
                priority="high" if docking_result.vina_score > -6.0 else "medium",
                title=f"增强分子 {molecule.mol_name or molecule.molecule_id[:8]} 的结合亲和力",
                problem=f"对接评分{docking_result.vina_score:.2f}，结合亲和力不足",
                suggestion="增加与靶点关键残基的相互作用：氢键、疏水作用或π-π堆积",
                rationale="提高结合亲和力可增强药效",
                expected_improvement="预计对接评分可改善2-3 kcal/mol",
            )

        return None

    def _advise_synthesis_optimization(
        self,
        molecule: Molecule,
        mol_score: MoleculeScore,
    ) -> OptimizationAdvice | None:
        """合成优化建议"""
        synthesis_route = self._get_synthesis(molecule.molecule_id)
        if not synthesis_route or not synthesis_route.sa_score:
            return None

        if synthesis_route.sa_score > 6.0:
            return OptimizationAdvice(
                target=molecule.molecule_id,
                category="synthesis",
                priority="medium",
                title=f"简化分子 {molecule.mol_name or molecule.molecule_id[:8]} 的结构",
                problem=f"SA Score为{synthesis_route.sa_score:.2f}，合成难度高",
                suggestion="去除复杂的立体中心、减少保护基团步骤或寻找商业可得的砌块",
                rationale="降低合成难度可加快候选物推进速度并降低成本",
                expected_improvement="预计SA Score可降低1-2分",
            )

        return None

    def _generate_general_advice(
        self,
        molecules: list[Molecule],
        ranking_result: RankingResult | None,
    ) -> list[OptimizationAdvice]:
        """生成通用建议"""
        advice_list: list[OptimizationAdvice] = []

        # 如果候选物整体质量不高
        if ranking_result and ranking_result.excellent_count == 0:
            advice_list.append(OptimizationAdvice(
                target="general",
                category="structure",
                priority="high",
                title="考虑重新设计分子骨架",
                problem="当前候选物整体评分偏低",
                suggestion="分析失败原因，调整分子设计策略或使用不同的生成方法",
                rationale="系统性问题需要系统性解决方案",
                expected_improvement="可能获得质量更好的候选物",
            ))

        # 如果ADMET问题普遍
        admet_issues = sum(1 for m in molecules if self._has_admet_issue(m))
        if admet_issues > len(molecules) * 0.5:
            advice_list.append(OptimizationAdvice(
                target="general",
                category="admet",
                priority="high",
                title="整体改善ADMET性质",
                problem=f"{admet_issues}/{len(molecules)}个分子存在ADMET问题",
                suggestion="在分子生成阶段增加ADMET约束，优先生成安全性更好的结构",
                rationale="早期筛选可节省后期优化成本",
                expected_improvement="减少高风险候选物比例",
            ))

        return advice_list

    def _create_action_plan(
        self,
        project: Project,
        molecules: list[Molecule],
        ranking_result: RankingResult | None,
    ) -> list[ActionItem]:
        """创建行动计划"""
        action_plan: list[ActionItem] = []

        # 基于项目状态确定行动
        if not molecules:
            action_plan.append(ActionItem(
                action_type="generate",
                priority=1,
                title="生成初始候选分子",
                description="使用分子生成工具创建候选物库",
                estimated_time="1-2天",
            ))
            return action_plan

        # 检查评估完整性
        incomplete_molecules = [
            m for m in molecules
            if not (self._has_property(m) and self._has_admet(m) and
                   self._has_docking(m) and self._has_synthesis(m))
        ]

        if incomplete_molecules:
            action_plan.append(ActionItem(
                action_type="retest",
                priority=1,
                title="完成缺失的评估",
                description=f"对{len(incomplete_molecules)}个分子完成性质、ADMET、对接和合成评估",
                target_molecules=[m.molecule_id for m in incomplete_molecules],
                estimated_time="1-3天",
            ))

        # 优化Top分子
        if ranking_result and ranking_result.good_count > 0:
            top_molecules = [
                m for m in ranking_result.ranked_molecules[:5]
                if m.tier in ["excellent", "good"]
            ]

            if top_molecules:
                action_plan.append(ActionItem(
                    action_type="optimize",
                    priority=2,
                    title="优化Top候选物",
                    description=f"对{len(top_molecules)}个优质候选物进行结构优化和ADMET改善",
                    target_molecules=[m.molecule_id for m in top_molecules],
                    estimated_time="3-5天",
                    dependencies=["完成缺失的评估"] if incomplete_molecules else [],
                ))

        # 如果所有候选物都不理想
        if ranking_result and ranking_result.excellent_count == 0 and ranking_result.good_count == 0:
            action_plan.append(ActionItem(
                action_type="generate",
                priority=1,
                title="生成新一轮候选物",
                description="调整生成策略，产生质量更好的候选分子",
                estimated_time="2-3天",
            ))

        # 合成计划
        if ranking_result and ranking_result.excellent_count > 0:
            excellent_molecules = [
                m for m in ranking_result.ranked_molecules
                if m.tier == "excellent"
            ]

            action_plan.append(ActionItem(
                action_type="synthesize",
                priority=3,
                title="准备合成优秀候选物",
                description=f"准备{len(excellent_molecules)}个优秀候选物的合成方案",
                target_molecules=[m.molecule_id for m in excellent_molecules],
                estimated_time="1-2周",
                dependencies=["完成缺失的评估", "优化Top候选物"],
            ))

        return action_plan

    def _identify_risks(
        self,
        molecules: list[Molecule],
        ranking_result: RankingResult | None,
    ) -> list[str]:
        """识别风险"""
        risks: list[str] = []

        if not molecules:
            risks.append("项目尚未生成候选分子，存在启动延迟风险")
            return risks

        # 候选物数量风险
        if len(molecules) < 10:
            risks.append("候选物数量较少，建议扩大候选库以增加成功概率")

        # 质量风险
        if ranking_result:
            if ranking_result.excellent_count == 0:
                risks.append("缺少优秀候选物，项目成功率较低")

            if ranking_result.poor_count > len(molecules) * 0.7:
                risks.append("大部分候选物评分低，可能需要重新设计")

        # ADMET风险
        high_risk_admet = sum(
            1 for m in molecules
            if self._has_high_admet_risk(m)
        )
        if high_risk_admet > len(molecules) * 0.3:
            risks.append(f"{high_risk_admet}个分子存在严重ADMET风险，可能影响临床开发")

        # 合成风险
        hard_synthesis = sum(
            1 for m in molecules
            if self._has_synthesis_difficulty(m)
        )
        if hard_synthesis > len(molecules) * 0.5:
            risks.append(f"{hard_synthesis}个分子合成困难，可能延长开发周期")

        return risks

    def _estimate_candidate_readiness_score(
        self,
        molecules: list[Molecule],
        ranking_result: RankingResult | None,
    ) -> float:
        """计算候选成熟度启发式评分；该值不是校准概率。"""
        if not molecules:
            return 0.0

        if not ranking_result:
            return 0.3  # 未排序候选的低成熟度基线，不代表成功概率

        # 基于排序结果计算
        score = 0.0

        # 优秀候选物
        if ranking_result.excellent_count > 0:
            score += min(0.5, ranking_result.excellent_count * 0.15)

        # 良好候选物
        if ranking_result.good_count > 0:
            score += min(0.3, ranking_result.good_count * 0.1)

        # 可接受候选物
        if ranking_result.acceptable_count > 0:
            score += min(0.15, ranking_result.acceptable_count * 0.05)

        # 候选物多样性奖励
        if len(molecules) >= 20:
            score += 0.05

        return min(1.0, score)

    def _determine_next_milestone(
        self,
        project: Project,
        molecules: list[Molecule],
        ranking_result: RankingResult | None,
    ) -> str:
        """确定下一个里程碑"""
        if not molecules:
            return "生成初始候选分子库（目标：50-100个）"

        # 检查评估完整性
        complete = all(
            self._has_property(m) and self._has_admet(m) and
            self._has_docking(m) and self._has_synthesis(m)
            for m in molecules
        )

        if not complete:
            return "完成所有候选物的全面评估"

        if ranking_result:
            if ranking_result.excellent_count >= 3:
                return "准备前3个优秀候选物的合成方案"
            elif ranking_result.good_count >= 5:
                return "优化前5个良好候选物，目标达到优秀标准"
            elif ranking_result.acceptable_count >= 10:
                return "优化可接受候选物或生成新一轮候选库"
            else:
                return "重新设计分子骨架，生成新候选库"

        return "完成候选物排序和优先级分配"

    # 辅助方法
    def _get_molecule(self, molecule_id: str) -> Molecule | None:
        return self.db.query(Molecule).filter_by(molecule_id=molecule_id).first()

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

    def _has_admet_issue(self, molecule: Molecule) -> bool:
        admet = self._get_admet(molecule.molecule_id)
        if not admet:
            return False
        return (admet.hERG_risk in ["high_risk", "medium_risk"] or
                admet.Ames_risk in ["high_risk", "medium_risk"])

    def _has_high_admet_risk(self, molecule: Molecule) -> bool:
        admet = self._get_admet(molecule.molecule_id)
        if not admet:
            return False
        return (admet.hERG_risk == "high_risk" or admet.Ames_risk == "high_risk")

    def _has_synthesis_difficulty(self, molecule: Molecule) -> bool:
        synthesis = self._get_synthesis(molecule.molecule_id)
        if not synthesis or not synthesis.sa_score:
            return False
        return synthesis.sa_score > 6.0

    def _analyze_common_issues(self, molecules: list[Molecule]) -> list[str]:
        """分析常见问题"""
        issues: list[str] = []

        # 统计Lipinski违规
        lipinski_violations = sum(
            1 for m in molecules
            if self._get_property(m.molecule_id) and
            not self._get_property(m.molecule_id).lipinski_compliant
        )

        if lipinski_violations > len(molecules) * 0.5:
            issues.append("超过50%的分子违反Lipinski规则")

        # 统计PAINS警报
        pains_count = sum(
            1 for m in molecules
            if self._get_property(m.molecule_id) and
            "pains_alert" in self._get_property(m.molecule_id).labels
        )

        if pains_count > 0:
            issues.append(f"{pains_count}个分子包含PAINS结构警报")

        return issues
