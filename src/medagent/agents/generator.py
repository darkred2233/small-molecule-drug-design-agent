"""
Molecule Generator Agent

负责配置和执行分子生成任务，调用REINVENT4、AutoGrow4等生成工具。

功能：
1. 根据种子配体和SAR规则配置生成参数
2. 调用分子生成工具
3. 记录生成过程和决策依据
4. 生成可解释的推理轨迹
"""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from medagent.db.models import (
    Project,
    SeedLigand,
)
from medagent.services.molecule_generation import (
    generate_project_molecules,
)


@dataclass
class GenerationStrategy:
    """生成策略"""
    method: str  # reinvent4, autogrow4, crem
    seed_ligands: list[str]
    target_count: int
    constraints: dict[str, Any]
    keep_core: bool = True
    min_similarity: float = 0.35
    max_similarity: float = 0.85
    reasoning: str = ""


@dataclass
class GenerationResult:
    """生成结果"""
    project_id: str
    strategy: GenerationStrategy
    generated_count: int
    valid_count: int
    molecule_ids: list[str]
    failures: dict[str, int] = field(default_factory=dict)
    reasoning_trace: dict[str, Any] | None = None
    recommendations: list[str] = field(default_factory=list)


class GeneratorAgent:
    """分子生成Agent"""

    def __init__(self, db: Session, llm_client: Any = None):
        self.db = db
        self.llm = llm_client

    def plan_generation(
        self,
        project: Project,
        seed_ligands: list[SeedLigand],
        sar_rules: list[dict],
        user_constraints: dict[str, Any],
    ) -> GenerationStrategy:
        """
        规划分子生成策略

        Args:
            project: 项目
            seed_ligands: 种子配体列表
            sar_rules: SAR规则
            user_constraints: 用户约束

        Returns:
            GenerationStrategy
        """
        # 选择生成方法
        method = self._select_generation_method(project, user_constraints)

        # 确定生成数量
        target_count = user_constraints.get("generation_size", 20000)

        # 提取种子SMILES
        seed_smiles = [lig.smiles for lig in seed_ligands if lig.smiles]

        # 构建约束
        constraints = self._build_constraints(sar_rules, user_constraints)

        # 确定相似度范围
        keep_core = user_constraints.get("keep_core", True)
        min_sim = user_constraints.get("min_tanimoto_to_seed", 0.35)
        max_sim = user_constraints.get("max_tanimoto_to_seed", 0.85)

        # 生成推理
        reasoning = self._generate_planning_reasoning(
            method=method,
            seed_count=len(seed_smiles),
            target_count=target_count,
            sar_rules=sar_rules,
            constraints=constraints,
        )

        return GenerationStrategy(
            method=method,
            seed_ligands=seed_smiles,
            target_count=target_count,
            constraints=constraints,
            keep_core=keep_core,
            min_similarity=min_sim,
            max_similarity=max_sim,
            reasoning=reasoning,
        )

    def execute_generation(
        self,
        project: Project,
        strategy: GenerationStrategy,
    ) -> GenerationResult:
        """
        执行分子生成

        Args:
            project: 项目
            strategy: 生成策略

        Returns:
            GenerationResult
        """
        try:
            generation_constraints = {
                **strategy.constraints,
                "keep_core": strategy.keep_core,
                "min_tanimoto_to_seed": strategy.min_similarity,
                "max_tanimoto_to_seed": strategy.max_similarity,
            }
            generation_result = generate_project_molecules(
                db=self.db,
                project=project,
                generation_size=strategy.target_count,
                strategies=[strategy.method],
                strategy_counts={strategy.method: strategy.target_count},
                constraints=generation_constraints,
                agent_run_name="generator_agent",
            )

            # 统计结果
            generated_count = generation_result.get("generated_count", 0)
            valid_count = generation_result.get("stored_count", 0)
            molecule_ids = generation_result.get("molecule_ids", [])
            failures = generation_result.get("failed_reason_summary", {})

            # 生成推理轨迹
            reasoning_trace = self._create_reasoning_trace(
                project=project,
                strategy=strategy,
                generated_count=generated_count,
                valid_count=valid_count,
                failures=failures,
            )

            # 生成建议
            recommendations = self._generate_recommendations(
                strategy=strategy,
                generated_count=generated_count,
                valid_count=valid_count,
                failures=failures,
            )

            return GenerationResult(
                project_id=project.project_id,
                strategy=strategy,
                generated_count=generated_count,
                valid_count=valid_count,
                molecule_ids=molecule_ids,
                failures=failures,
                reasoning_trace=reasoning_trace,
                recommendations=recommendations,
            )

        except Exception:
            raise

    def _select_generation_method(
        self,
        project: Project,
        user_constraints: dict[str, Any],
    ) -> str:
        """选择生成方法"""
        # 用户指定
        if "generation_method" in user_constraints:
            return user_constraints["generation_method"]

        # 默认使用REINVENT4
        return "reinvent4"

    def _build_constraints(
        self,
        sar_rules: list[dict],
        user_constraints: dict[str, Any],
    ) -> dict[str, Any]:
        """构建约束条件"""
        constraints = {}

        # 分子性质约束
        if "MW" in user_constraints:
            constraints["MW"] = user_constraints["MW"]
        if "cLogP" in user_constraints:
            constraints["cLogP"] = user_constraints["cLogP"]
        if "TPSA" in user_constraints:
            constraints["TPSA"] = user_constraints["TPSA"]

        # SAR规则转换为约束
        protected_motifs = []
        forbidden_motifs = []

        for rule in sar_rules:
            if rule.get("rule_type") == "keep":
                protected_motifs.append(rule.get("smarts", ""))
            elif rule.get("rule_type") == "avoid":
                forbidden_motifs.append(rule.get("smarts", ""))

        if protected_motifs:
            constraints["protected_motifs"] = protected_motifs
        if forbidden_motifs:
            constraints["forbidden_motifs"] = forbidden_motifs

        return constraints

    def _generate_planning_reasoning(
        self,
        method: str,
        seed_count: int,
        target_count: int,
        sar_rules: list[dict],
        constraints: dict[str, Any],
    ) -> str:
        """生成规划推理"""
        reasoning_parts = [
            f"选择{method}作为生成方法，基于{seed_count}个种子配体生成{target_count}个候选分子。"
        ]

        if sar_rules:
            reasoning_parts.append(
                f"应用{len(sar_rules)}条SAR规则以保持结构合理性。"
            )

        if constraints:
            reasoning_parts.append(
                f"施加{len(constraints)}项约束条件以满足药化要求。"
            )

        return " ".join(reasoning_parts)

    def _create_reasoning_trace(
        self,
        project: Project,
        strategy: GenerationStrategy,
        generated_count: int,
        valid_count: int,
        failures: dict[str, int],
    ) -> dict[str, Any]:
        """创建推理轨迹"""
        success_rate = (valid_count / generated_count * 100) if generated_count > 0 else 0

        supporting_factors = [
            f"成功生成{generated_count}个分子结构",
            f"其中{valid_count}个通过基本验证（{success_rate:.1f}%）",
        ]

        if strategy.keep_core:
            supporting_factors.append("保留了核心骨架以维持关键相互作用")

        opposing_factors = []
        if failures:
            total_failed = sum(failures.values())
            opposing_factors.append(
                f"{total_failed}个分子未通过验证（{total_failed/generated_count*100:.1f}%）"
            )
            for reason, count in sorted(failures.items(), key=lambda x: x[1], reverse=True)[:3]:
                opposing_factors.append(f"{reason}: {count}个")

        return {
            "trace_id": f"TRACE-GEN-{project.project_id}",
            "agent_name": "generator_agent",
            "claim": f"使用{strategy.method}生成了{valid_count}个有效候选分子",
            "confidence": min(success_rate / 100, 1.0),
            "supporting_factors": supporting_factors,
            "opposing_factors": opposing_factors,
            "uncertainties": [
                "生成分子的实际活性需要实验验证",
                "相似度评分基于2D指纹，不能完全反映3D结构差异",
            ],
        }

    def _generate_recommendations(
        self,
        strategy: GenerationStrategy,
        generated_count: int,
        valid_count: int,
        failures: dict[str, int],
    ) -> list[str]:
        """生成建议"""
        recommendations = []

        success_rate = (valid_count / generated_count * 100) if generated_count > 0 else 0

        if success_rate < 30:
            recommendations.append(
                "⚠️ 生成成功率较低，建议放宽约束条件或调整种子配体"
            )

        if "duplicate" in failures and failures["duplicate"] > generated_count * 0.1:
            recommendations.append(
                "💡 重复分子较多，建议增加diversity参数"
            )

        if "invalid_smiles" in failures and failures["invalid_smiles"] > generated_count * 0.05:
            recommendations.append(
                "⚠️ 无效SMILES较多，可能需要调整生成模型参数"
            )

        if success_rate > 60:
            recommendations.append(
                "✅ 生成质量良好，可以继续进行后续评估"
            )

        return recommendations

    def batch_generate(
        self,
        project: Project,
        strategies: list[GenerationStrategy],
    ) -> list[GenerationResult]:
        """
        批量生成（多策略）

        Args:
            project: 项目
            strategies: 多个生成策略

        Returns:
            生成结果列表
        """
        results = []
        for strategy in strategies:
            result = self.execute_generation(project, strategy)
            results.append(result)
        return results
