"""
Filter Agent

负责基础规则过滤，淘汰明显不合格的分子。

功能：
1. 应用Lipinski、PAINS、Brenk等规则过滤
2. 检查分子性质是否在合理范围内
3. 记录过滤决策和理由
4. 生成可解释的推理轨迹
"""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from medagent.db.models import (
    AgentRun,
    Molecule,
    MoleculeProperty,
    Project,
)
from medagent.services.rule_filtering import (
    FilterConfig,
    filter_molecules,
)


@dataclass
class FilterDecision:
    """过滤决策"""
    molecule_id: str
    passed: bool
    failed_rules: list[str] = field(default_factory=list)
    property_violations: dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""


@dataclass
class FilterResult:
    """过滤结果"""
    project_id: str
    input_count: int
    passed_count: int
    failed_count: int
    failure_breakdown: dict[str, int] = field(default_factory=dict)
    passed_molecule_ids: list[str] = field(default_factory=list)
    failed_molecule_ids: list[str] = field(default_factory=list)
    reasoning_trace: dict[str, Any] | None = None
    recommendations: list[str] = field(default_factory=list)


class FilterAgent:
    """规则过滤Agent"""

    def __init__(self, db: Session, llm_client: Any = None):
        self.db = db
        self.llm = llm_client

    def filter_molecules(
        self,
        project: Project,
        molecule_ids: list[str] | None = None,
        config: FilterConfig | None = None,
    ) -> FilterResult:
        """
        过滤分子

        Args:
            project: 项目
            molecule_ids: 分子ID列表（None表示过滤所有未过滤的分子）
            config: 过滤配置

        Returns:
            FilterResult
        """
        # 记录Agent运行
        agent_run = AgentRun(
            project_id=project.project_id,
            agent_name="filter_agent",
            agent_type="filtering",
            status="running",
        )
        self.db.add(agent_run)
        self.db.commit()

        try:
            # 获取待过滤的分子
            if molecule_ids is None:
                molecules = self.db.query(Molecule).filter(
                    Molecule.project_id == project.project_id,
                    Molecule.status == "generated",
                ).all()
                molecule_ids = [m.molecule_id for m in molecules]

            input_count = len(molecule_ids)

            # 使用默认配置或用户配置
            if config is None:
                config = self._create_default_config(project)

            # 调用过滤服务
            filter_result = filter_molecules(
                project_id=project.project_id,
                molecule_ids=molecule_ids,
                config=config,
                db=self.db,
            )

            # 统计结果
            passed_count = filter_result.get("passed_count", 0)
            failed_count = filter_result.get("failed_count", 0)
            failure_breakdown = filter_result.get("failure_breakdown", {})
            passed_molecule_ids = filter_result.get("passed_molecule_ids", [])
            failed_molecule_ids = filter_result.get("failed_molecule_ids", [])

            # 生成推理轨迹
            reasoning_trace = self._create_reasoning_trace(
                project=project,
                input_count=input_count,
                passed_count=passed_count,
                failed_count=failed_count,
                failure_breakdown=failure_breakdown,
                config=config,
            )

            # 生成建议
            recommendations = self._generate_recommendations(
                input_count=input_count,
                passed_count=passed_count,
                failure_breakdown=failure_breakdown,
            )

            # 更新Agent运行状态
            agent_run.status = "completed"
            agent_run.output_data = {
                "input_count": input_count,
                "passed_count": passed_count,
                "failed_count": failed_count,
            }
            agent_run.success = True
            self.db.commit()

            return FilterResult(
                project_id=project.project_id,
                input_count=input_count,
                passed_count=passed_count,
                failed_count=failed_count,
                failure_breakdown=failure_breakdown,
                passed_molecule_ids=passed_molecule_ids,
                failed_molecule_ids=failed_molecule_ids,
                reasoning_trace=reasoning_trace,
                recommendations=recommendations,
            )

        except Exception as e:
            agent_run.status = "failed"
            agent_run.error_message = str(e)
            agent_run.success = False
            self.db.commit()
            raise

    def explain_filter_decision(
        self,
        molecule: Molecule,
        mol_property: MoleculeProperty,
        config: FilterConfig,
    ) -> FilterDecision:
        """
        解释单个分子的过滤决策

        Args:
            molecule: 分子
            mol_property: 分子性质
            config: 过滤配置

        Returns:
            FilterDecision
        """
        failed_rules = []
        property_violations = {}

        # 检查PAINS
        if config.remove_pains and mol_property.pains_alert:
            failed_rules.append("PAINS")

        # 检查Brenk
        if config.remove_brenk and mol_property.brenk_alert:
            failed_rules.append("Brenk")

        # 检查Lipinski规则
        if mol_property.mw is not None:
            mw_range = config.property_filters.get("MW", [0, 600])
            if not (mw_range[0] <= mol_property.mw <= mw_range[1]):
                failed_rules.append("MW_out_of_range")
                property_violations["MW"] = {
                    "value": mol_property.mw,
                    "range": mw_range,
                }

        if mol_property.logp is not None:
            logp_range = config.property_filters.get("cLogP", [-2, 6])
            if not (logp_range[0] <= mol_property.logp <= logp_range[1]):
                failed_rules.append("cLogP_out_of_range")
                property_violations["cLogP"] = {
                    "value": mol_property.logp,
                    "range": logp_range,
                }

        if mol_property.tpsa is not None:
            tpsa_range = config.property_filters.get("TPSA", [20, 140])
            if not (tpsa_range[0] <= mol_property.tpsa <= tpsa_range[1]):
                failed_rules.append("TPSA_out_of_range")
                property_violations["TPSA"] = {
                    "value": mol_property.tpsa,
                    "range": tpsa_range,
                }

        # 检查SA Score
        if mol_property.sa_score is not None:
            max_sa = config.property_filters.get("SA_score_max", 5.0)
            if mol_property.sa_score > max_sa:
                failed_rules.append("SA_score_too_high")
                property_violations["SA_score"] = {
                    "value": mol_property.sa_score,
                    "threshold": max_sa,
                }

        passed = len(failed_rules) == 0

        # 生成推理
        reasoning = self._generate_decision_reasoning(
            molecule=molecule,
            passed=passed,
            failed_rules=failed_rules,
            property_violations=property_violations,
        )

        return FilterDecision(
            molecule_id=molecule.molecule_id,
            passed=passed,
            failed_rules=failed_rules,
            property_violations=property_violations,
            reasoning=reasoning,
        )

    def _create_default_config(self, project: Project) -> FilterConfig:
        """创建默认过滤配置"""
        return FilterConfig(
            remove_pains=True,
            remove_brenk=True,
            property_filters={
                "MW": [250, 550],
                "cLogP": [0, 5],
                "TPSA": [40, 120],
                "HBD_max": 5,
                "HBA_max": 10,
                "RotB_max": 10,
                "SA_score_max": 4.5,
            },
        )

    def _create_reasoning_trace(
        self,
        project: Project,
        input_count: int,
        passed_count: int,
        failed_count: int,
        failure_breakdown: dict[str, int],
        config: FilterConfig,
    ) -> dict[str, Any]:
        """创建推理轨迹"""
        pass_rate = (passed_count / input_count * 100) if input_count > 0 else 0

        supporting_factors = [
            f"成功过滤{input_count}个候选分子",
            f"{passed_count}个分子通过规则过滤（{pass_rate:.1f}%）",
        ]

        if config.remove_pains:
            supporting_factors.append("应用了PAINS结构警报过滤")
        if config.remove_brenk:
            supporting_factors.append("应用了Brenk毒性团过滤")

        opposing_factors = []
        if failed_count > 0:
            opposing_factors.append(
                f"{failed_count}个分子未通过过滤（{failed_count/input_count*100:.1f}%）"
            )

            # 列出主要失败原因
            for reason, count in sorted(
                failure_breakdown.items(),
                key=lambda x: x[1],
                reverse=True
            )[:3]:
                opposing_factors.append(f"{reason}: {count}个（{count/failed_count*100:.1f}%）")

        uncertainties = [
            "规则过滤基于化学直觉，不能替代实验验证",
            "某些具有干扰结构的分子可能在特定assay中仍有活性",
        ]

        return {
            "trace_id": f"TRACE-FILTER-{project.project_id}",
            "agent_name": "filter_agent",
            "claim": f"通过规则过滤筛选出{passed_count}个符合基本药化要求的候选分子",
            "confidence": 0.85,  # 规则过滤置信度较高
            "supporting_factors": supporting_factors,
            "opposing_factors": opposing_factors,
            "uncertainties": uncertainties,
        }

    def _generate_decision_reasoning(
        self,
        molecule: Molecule,
        passed: bool,
        failed_rules: list[str],
        property_violations: dict[str, Any],
    ) -> str:
        """生成决策推理"""
        if passed:
            return f"分子 {molecule.molecule_id} 通过了所有规则过滤，符合基本药化要求。"

        reasons = []
        if "PAINS" in failed_rules:
            reasons.append("命中PAINS干扰结构")
        if "Brenk" in failed_rules:
            reasons.append("命中Brenk毒性团")

        for prop, violation in property_violations.items():
            if "range" in violation:
                reasons.append(
                    f"{prop}={violation['value']:.2f}超出范围{violation['range']}"
                )
            elif "threshold" in violation:
                reasons.append(
                    f"{prop}={violation['value']:.2f}超过阈值{violation['threshold']}"
                )

        return f"分子 {molecule.molecule_id} 未通过过滤：" + "、".join(reasons)

    def _generate_recommendations(
        self,
        input_count: int,
        passed_count: int,
        failure_breakdown: dict[str, int],
    ) -> list[str]:
        """生成建议"""
        recommendations = []

        pass_rate = (passed_count / input_count * 100) if input_count > 0 else 0

        if pass_rate < 20:
            recommendations.append(
                "⚠️ 通过率过低（<20%），建议检查生成参数或放宽过滤标准"
            )
        elif pass_rate < 40:
            recommendations.append(
                "💡 通过率较低（<40%），建议适度调整约束条件"
            )
        elif pass_rate > 80:
            recommendations.append(
                "✅ 通过率良好（>80%），生成质量较高"
            )

        # 针对主要失败原因给出建议
        if failure_breakdown.get("MW_out_of_range", 0) > input_count * 0.2:
            recommendations.append(
                "💡 分子量超标较多，建议在生成阶段限制重原子数"
            )

        if failure_breakdown.get("cLogP_out_of_range", 0) > input_count * 0.2:
            recommendations.append(
                "💡 脂溶性超标较多，建议增加极性取代基或减少芳香环"
            )

        if failure_breakdown.get("SA_score_too_high", 0) > input_count * 0.15:
            recommendations.append(
                "💡 合成难度过高的分子较多，建议限制复杂度或使用更简单的起始骨架"
            )

        if failure_breakdown.get("pains", 0) > input_count * 0.1:
            recommendations.append(
                "⚠️ PAINS干扰结构较多，建议在生成时添加PAINS过滤"
            )

        return recommendations

    def get_filter_statistics(
        self,
        project: Project,
    ) -> dict[str, Any]:
        """
        获取项目的过滤统计信息

        Args:
            project: 项目

        Returns:
            统计信息
        """
        total_molecules = self.db.query(Molecule).filter(
            Molecule.project_id == project.project_id
        ).count()

        passed_molecules = self.db.query(Molecule).filter(
            Molecule.project_id == project.project_id,
            Molecule.status == "passed_filter",
        ).count()

        failed_molecules = self.db.query(Molecule).filter(
            Molecule.project_id == project.project_id,
            Molecule.status == "failed_filter",
        ).count()

        return {
            "total_molecules": total_molecules,
            "passed_molecules": passed_molecules,
            "failed_molecules": failed_molecules,
            "pass_rate": (passed_molecules / total_molecules * 100) if total_molecules > 0 else 0,
        }
