"""
Ranker Agent

负责综合所有评估结果对候选分子进行排序和优先级分配。

功能：
1. 多维度评分：结构、ADMET、对接、合成
2. 权重配置：根据项目目标调整权重
3. 综合排序：生成最终排名
4. 分层推荐：优秀/良好/可接受/淘汰
5. 集成 LLM 质询结果（从 Critique 表）
"""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from medagent.db.models import (
    ADMETResult,
    Critique,
    DockingResult,
    Molecule,
    MoleculeProperty,
    Project,
    SynthesisRoute,
)


@dataclass
class RankingWeights:
    """排序权重配置"""
    structure_weight: float = 0.2
    admet_weight: float = 0.3
    docking_weight: float = 0.35
    synthesis_weight: float = 0.15

    def normalize(self) -> None:
        """归一化权重"""
        total = (
            self.structure_weight +
            self.admet_weight +
            self.docking_weight +
            self.synthesis_weight
        )
        if total > 0:
            self.structure_weight /= total
            self.admet_weight /= total
            self.docking_weight /= total
            self.synthesis_weight /= total


@dataclass
class MoleculeScore:
    """分子评分"""
    molecule_id: str
    structure_score: float = 0.0
    admet_score: float = 0.0
    docking_score: float = 0.0
    synthesis_score: float = 0.0
    weighted_score: float = 0.0
    critique_con_score: float = 0.0  # 从 Critique 表读取
    final_score: float = 0.0
    rank: int = 0
    tier: str = "unranked"  # excellent, good, acceptable, poor
    critique_decision: str | None = None  # pass, reserve, reject
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class RankingResult:
    """排序结果"""
    project_id: str
    total_molecules: int
    ranked_molecules: list[MoleculeScore]
    excellent_count: int = 0
    good_count: int = 0
    acceptable_count: int = 0
    poor_count: int = 0
    weights_used: RankingWeights | None = None
    ranking_summary: str = ""


class RankerAgent:
    """排序Agent - 直接读取 Critique 表"""

    def __init__(self, db: Session):
        self.db = db

    def rank_molecules(
        self,
        project: Project,
        molecules: list[Molecule],
        weights: RankingWeights | None = None,
        use_critique: bool = True,
        use_refutation: bool | None = None,
    ) -> RankingResult:
        """
        对分子进行综合排序

        Args:
            project: 项目
            molecules: 待排序的分子列表
            weights: 权重配置（None使用默认）
            use_critique: 是否使用 Critique 表的反驳评分
            use_refutation: 旧参数名，保留为 use_critique 的兼容别名

        Returns:
            RankingResult
        """
        if use_refutation is not None:
            use_critique = use_refutation

        if not molecules:
            return RankingResult(
                project_id=project.project_id,
                total_molecules=0,
                ranked_molecules=[],
            )

        # 使用默认权重或归一化自定义权重
        if weights is None:
            weights = RankingWeights()
        else:
            weights.normalize()

        # 从 Critique 表读取反驳结果（包含 LLM 质询）
        critique_map: dict[str, Critique] = {}
        if use_critique:
            molecule_ids = [m.molecule_id for m in molecules]
            critiques = self.db.query(Critique).filter(
                Critique.molecule_id.in_(molecule_ids)
            ).all()
            critique_map = {c.molecule_id: c for c in critiques}

        # 计算每个分子的评分
        molecule_scores: list[MoleculeScore] = []
        for molecule in molecules:
            critique = critique_map.get(molecule.molecule_id)
            score = self._calculate_molecule_score(molecule, weights, critique)
            molecule_scores.append(score)

        # 排序
        molecule_scores.sort(key=lambda x: x.final_score, reverse=True)

        # 分配排名和分层
        excellent_count = 0
        good_count = 0
        acceptable_count = 0
        poor_count = 0

        for rank, score in enumerate(molecule_scores, start=1):
            score.rank = rank

            # 分层
            if score.final_score >= 80:
                score.tier = "excellent"
                excellent_count += 1
            elif score.final_score >= 65:
                score.tier = "good"
                good_count += 1
            elif score.final_score >= 50:
                score.tier = "acceptable"
                acceptable_count += 1
            else:
                score.tier = "poor"
                poor_count += 1

        # 生成排序总结
        ranking_summary = self._generate_ranking_summary(
            len(molecules),
            excellent_count,
            good_count,
            acceptable_count,
            poor_count,
        )

        return RankingResult(
            project_id=project.project_id,
            total_molecules=len(molecules),
            ranked_molecules=molecule_scores,
            excellent_count=excellent_count,
            good_count=good_count,
            acceptable_count=acceptable_count,
            poor_count=poor_count,
            weights_used=weights,
            ranking_summary=ranking_summary,
        )

    def _calculate_molecule_score(
        self,
        molecule: Molecule,
        weights: RankingWeights,
        critique: Critique | None,
    ) -> MoleculeScore:
        """计算单个分子的综合评分"""

        # 获取评估数据
        mol_property = self.db.query(MoleculeProperty).filter_by(
            molecule_id=molecule.molecule_id
        ).first()

        admet_result = self.db.query(ADMETResult).filter_by(
            molecule_id=molecule.molecule_id
        ).first()

        docking_result = self.db.query(DockingResult).filter_by(
            molecule_id=molecule.molecule_id
        ).first()

        synthesis_route = self.db.query(SynthesisRoute).filter_by(
            molecule_id=molecule.molecule_id
        ).first()

        # 计算各维度评分 (0-100)
        structure_score = self._score_structure(mol_property)
        admet_score = self._score_admet(admet_result)
        docking_score = self._score_docking(docking_result)
        synthesis_score = self._score_synthesis(synthesis_route)

        # 加权综合评分
        weighted_score = (
            structure_score * weights.structure_weight +
            admet_score * weights.admet_weight +
            docking_score * weights.docking_weight +
            synthesis_score * weights.synthesis_weight
        )

        # 使用 Critique 表的 con_score（包含 LLM 质询结果）
        critique_con_score = 0.0
        critique_decision = None
        final_score = weighted_score

        if critique:
            critique_con_score = critique.con_score or 0.0
            critique_decision = critique.refutation_decision

            # 根据 con_score 和 refutation_decision 调整最终分数
            # con_score 越高，扣分越多
            if critique_decision == "reject":
                # 强烈建议淘汰
                final_score = min(weighted_score * 0.3, 40)
            elif critique_decision == "reserve":
                # 进入备选，适度惩罚
                penalty = min(critique_con_score * 0.5, 30)
                final_score = weighted_score - penalty
            elif critique_decision == "pass":
                # 通过，轻度或不惩罚
                if critique_con_score > 20:
                    penalty = (critique_con_score - 20) * 0.3
                    final_score = weighted_score - penalty
                # 否则不扣分

            # 确保最终分数在合理范围
            final_score = max(0.0, min(100.0, final_score))

        return MoleculeScore(
            molecule_id=molecule.molecule_id,
            structure_score=round(structure_score, 2),
            admet_score=round(admet_score, 2),
            docking_score=round(docking_score, 2),
            synthesis_score=round(synthesis_score, 2),
            weighted_score=round(weighted_score, 2),
            critique_con_score=round(critique_con_score, 2),
            final_score=round(final_score, 2),
            critique_decision=critique_decision,
            details={
                "smiles": molecule.smiles,
                "mol_name": molecule.mol_name,
                "critique_risk_level": critique.risk_level if critique else None,
                "critique_reason": critique.reason if critique else None,
                "llm_provider": critique.llm_provider if critique else None,
            },
        )

    def _score_structure(self, mol_property: MoleculeProperty | None) -> float:
        """结构评分 (0-100)"""
        if not mol_property:
            return 0.0

        score = 50.0  # 基础分

        # Lipinski合规性 (30分)
        if mol_property.lipinski_compliant:
            score += 30
        else:
            # 根据违规数量扣分
            violations = mol_property.lipinski_violations or 0
            score += max(0, 30 - violations * 10)

        # QED评分 (30分)
        if mol_property.qed:
            score += mol_property.qed * 30

        # 结构警报 (扣分)
        if "pains_alert" in mol_property.labels:
            score -= 30
        elif "structural_alert" in mol_property.labels:
            score -= 15

        # 分子量适中性 (10分)
        if mol_property.mw and 200 <= mol_property.mw <= 500:
            score += 10
        elif mol_property.mw and 150 <= mol_property.mw <= 600:
            score += 5

        return max(0.0, min(100.0, score))

    def _score_admet(self, admet_result: ADMETResult | None) -> float:
        """ADMET评分 (0-100)"""
        if not admet_result:
            return 0.0

        score = 0.0

        # hERG (25分)
        if admet_result.hERG_risk == "low_risk":
            score += 25
        elif admet_result.hERG_risk == "medium_risk":
            score += 12
        # high_risk: 0分

        # Ames (25分)
        if admet_result.Ames_risk == "low_risk":
            score += 25
        elif admet_result.Ames_risk == "medium_risk":
            score += 12

        # DILI (20分)
        if admet_result.DILI_risk == "low_risk":
            score += 20
        elif admet_result.DILI_risk == "medium_risk":
            score += 10

        # 溶解度 (15分)
        if admet_result.solubility == "high":
            score += 15
        elif admet_result.solubility == "medium":
            score += 10
        elif admet_result.solubility == "low":
            score += 5

        # 渗透性 (15分)
        if admet_result.permeability == "high":
            score += 15
        elif admet_result.permeability == "medium":
            score += 10
        elif admet_result.permeability == "low":
            score += 5

        return score

    def _score_docking(self, docking_result: DockingResult | None) -> float:
        """对接评分 (0-100)"""
        if not docking_result or not docking_result.vina_score:
            return 0.0

        score = 0.0
        vina_score = docking_result.vina_score

        # Vina评分转换 (70分)
        # -12.0以下: 70分
        # -6.0以上: 0分
        # 线性插值
        if vina_score <= -12.0:
            score += 70
        elif vina_score <= -6.0:
            score += 70 * ((-6.0 - vina_score) / 6.0)

        # CNN评分 (30分，如果有）
        if docking_result.cnn_score:
            score += docking_result.cnn_score * 30

        return min(100.0, score)

    def _score_synthesis(self, synthesis_route: SynthesisRoute | None) -> float:
        """合成评分 (0-100)"""
        if not synthesis_route or not synthesis_route.sa_score:
            return 0.0

        sa_score = synthesis_route.sa_score

        # SA Score转换
        # 1.0: 100分
        # 10.0: 0分
        # 线性插值
        score = max(0, 100 - (sa_score - 1.0) * 11.11)

        # 如果找到了合成路线，额外加分
        if synthesis_route.route_found:
            score = min(100, score + 10)

        return score

    def _generate_ranking_summary(
        self,
        total: int,
        excellent: int,
        good: int,
        acceptable: int,
        poor: int,
    ) -> str:
        """生成排序总结"""
        lines = [
            f"共评估{total}个候选分子：",
            f"  - 优秀（≥80分）: {excellent}个",
            f"  - 良好（65-79分）: {good}个",
            f"  - 可接受（50-64分）: {acceptable}个",
            f"  - 较差（<50分）: {poor}个",
        ]

        if excellent > 0:
            lines.append(f"\n推荐优先推进前{excellent}个优秀候选物")
        elif good > 0:
            lines.append(f"\n建议重点关注{good}个良好候选物")
        elif acceptable > 0:
            lines.append(f"\n可考虑{acceptable}个可接受候选物，但需要进一步优化")
        else:
            lines.append("\n所有候选物评分较低，建议重新设计或生成新的候选物")

        return "\n".join(lines)

    def get_top_molecules(
        self,
        ranking_result: RankingResult,
        n: int = 10,
        min_tier: str = "acceptable",
    ) -> list[MoleculeScore]:
        """
        获取Top N分子

        Args:
            ranking_result: 排序结果
            n: 数量
            min_tier: 最低层级（excellent/good/acceptable）

        Returns:
            Top N分子列表
        """
        tier_order = {"excellent": 0, "good": 1, "acceptable": 2, "poor": 3}
        min_tier_value = tier_order.get(min_tier, 2)

        filtered = [
            score for score in ranking_result.ranked_molecules
            if tier_order.get(score.tier, 3) <= min_tier_value
        ]

        return filtered[:n]

    def compare_molecules(
        self,
        molecule_score1: MoleculeScore,
        molecule_score2: MoleculeScore,
    ) -> dict[str, Any]:
        """
        比较两个分子

        Returns:
            比较结果字典
        """
        comparison = {
            "molecule1": molecule_score1.molecule_id,
            "molecule2": molecule_score2.molecule_id,
            "winner": None,
            "differences": {},
        }

        # 比较各维度
        dimensions = [
            ("structure", "结构"),
            ("admet", "ADMET"),
            ("docking", "对接"),
            ("synthesis", "合成"),
        ]

        for dim_key, dim_name in dimensions:
            score1 = getattr(molecule_score1, f"{dim_key}_score")
            score2 = getattr(molecule_score2, f"{dim_key}_score")
            diff = score1 - score2

            comparison["differences"][dim_name] = {
                "molecule1": score1,
                "molecule2": score2,
                "difference": round(diff, 2),
                "winner": "molecule1" if diff > 0 else "molecule2" if diff < 0 else "tie",
            }

        # 最终胜者
        if molecule_score1.final_score > molecule_score2.final_score:
            comparison["winner"] = "molecule1"
        elif molecule_score2.final_score > molecule_score1.final_score:
            comparison["winner"] = "molecule2"
        else:
            comparison["winner"] = "tie"

        return comparison
