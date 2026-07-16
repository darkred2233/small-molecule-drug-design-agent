"""
SAR Agent - 构效关系分析智能体

功能：
1. 分析分子结构与活性关系
2. 识别关键药效团
3. 预测结构修饰的影响
4. 提供结构优化建议
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from medagent.db.models import DockingResult, Molecule, Project
from medagent.llm import LLMMessage, get_llm_client


@dataclass
class SARPattern:
    """SAR模式"""
    pattern_type: str  # docking_score_shift, scaffold_similarity, bioisostere_hypothesis
    description: str
    molecules: list[str]  # molecule_ids
    activity_range: tuple[float, float] | None  # 仅用于同一实验终点的真实活性数据
    structural_change: str
    score_range: tuple[float, float] | None = None
    score_type: str | None = None
    evidence_kind: str = "hypothesis"
    caveats: list[str] = field(default_factory=list)


@dataclass
class Pharmacophore:
    """药效团"""
    features: list[str]  # HBD, HBA, Hydrophobic, Aromatic
    description: str
    importance_score: float  # 0-1
    score_semantics: str = "heuristic_not_probability"
    evidence_kind: str = "hypothesis"


@dataclass
class OptimizationSuggestion:
    """优化建议"""
    modification_type: str  # add_group, remove_group, replace_group, change_scaffold
    target_position: str
    rationale: str
    expected_improvement: str
    predicted_effect: str  # improve_docking_score, worsen_docking_score, uncertain
    evidence_kind: str = "hypothesis"


@dataclass
class SARAnalysisReport:
    """SAR分析报告"""
    project_id: str
    molecules_analyzed: int
    sar_patterns: list[SARPattern] = field(default_factory=list)
    pharmacophores: list[Pharmacophore] = field(default_factory=list)
    optimization_suggestions: list[OptimizationSuggestion] = field(default_factory=list)
    key_findings: list[str] = field(default_factory=list)
    evidence_scope: str = "computational_docking_hypotheses"
    warnings: list[str] = field(
        default_factory=lambda: ["docking_scores_are_not_experimental_activity"]
    )


class SARAgent:
    """构效关系分析Agent"""

    def __init__(self, db: Session):
        self.db = db
        self._llm_client: Any | None = None

    @property
    def llm_client(self) -> Any:
        if self._llm_client is None:
            self._llm_client = get_llm_client()
        return self._llm_client

    def analyze_sar(
        self,
        project: Project,
        use_llm: bool = True,
    ) -> SARAnalysisReport:
        """分析构效关系"""

        molecules = self.db.query(Molecule).filter_by(
            project_id=project.project_id
        ).all()

        # 获取对接数据
        docking_data = {
            m.molecule_id: self.db.query(DockingResult).filter_by(
                molecule_id=m.molecule_id
            ).first()
            for m in molecules
        }

        # 1. 识别SAR模式
        sar_patterns = self._identify_sar_patterns(molecules, docking_data, use_llm)

        # 2. 提取药效团
        pharmacophores = self._extract_pharmacophores(molecules, docking_data, use_llm)

        # 3. 生成优化建议
        optimization_suggestions = self._generate_optimization_suggestions(
            molecules, sar_patterns, pharmacophores, use_llm
        )

        # 4. 关键发现
        key_findings = self._summarize_key_findings(
            sar_patterns, pharmacophores, optimization_suggestions
        )

        return SARAnalysisReport(
            project_id=project.project_id,
            molecules_analyzed=len(molecules),
            sar_patterns=sar_patterns,
            pharmacophores=pharmacophores,
            optimization_suggestions=optimization_suggestions,
            key_findings=key_findings,
        )

    def _identify_sar_patterns(
        self,
        molecules: list[Molecule],
        docking_data: dict,
        use_llm: bool,
    ) -> list[SARPattern]:
        """识别SAR模式"""
        if not use_llm or not molecules:
            return self._rule_based_sar_patterns(molecules, docking_data)

        # 构建分子对比表
        mol_table = self._build_molecule_table(molecules, docking_data)

        prompt = f"""作为计算药物化学专家，请分析以下分子的结构与对接评分关系。

## 分子数据
{mol_table}

这些分数来自 Vina 对接，不是实验活性、IC50、Ki 或 Kd。不得输出 activity_cliff，
不得把较优对接分数称为高活性。所有结论只能作为待实验验证的计算假设。

请识别：
1. **对接评分显著变化**：相似结构之间的 Vina 分数差异
2. **骨架相似性假设**：不同骨架但计算评分接近
3. **生物电子等排体假设**：可能可互换、但尚未实验验证的官能团

以 JSON 数组返回：
[
  {{
    "pattern_type": "docking_score_shift/scaffold_similarity/bioisostere_hypothesis",
    "description": "描述",
    "molecules": ["molecule_id1", "molecule_id2"],
    "structural_change": "结构变化描述",
    "score_range": [min_score, max_score]
  }}
]
"""

        try:
            response = self.llm_client.complete(
                messages=[LLMMessage(role="user", content=prompt)],
                provider="qwen",
                model="qwen-max",
                temperature=0.3,
                max_tokens=2000,
            )

            return self._parse_sar_patterns(response.content)
        except Exception as e:
            print(f"LLM识别SAR模式失败: {e}")
            return self._rule_based_sar_patterns(molecules, docking_data)

    def _extract_pharmacophores(
        self,
        molecules: list[Molecule],
        docking_data: dict,
        use_llm: bool,
    ) -> list[Pharmacophore]:
        """提取药效团"""
        if not use_llm or not molecules:
            return self._rule_based_pharmacophores(molecules, docking_data)

        # 获取对接评分较优分子；该分组不代表实验活性
        best_docked_mols = self._get_best_docking_molecules(molecules, docking_data)

        smi_list = "\n".join(
            (
                "- "
                f"{m.smiles} "
                "(Vina docking score: "
                f"{self._format_optional_number(getattr(docking_data[m.molecule_id], 'vina_score', None))})"
            )
            for m in best_docked_mols[:10]
            if docking_data.get(m.molecule_id)
        )

        prompt = f"""基于以下对接评分较优分子，提出候选药效团假设。

## 对接评分较优分子
{smi_list}

Vina 对接分数不是实验活性。以下结果必须表述为待实验验证的结构假设，
不得宣称已经识别出真实药效团。

请以 JSON 数组返回药效团：
[
  {{
    "features": ["HBD", "HBA", "Aromatic", "Hydrophobic", "Positive", "Negative"],
    "description": "药效团描述",
    "importance_score": 0.0-1.0
  }}
]
"""

        try:
            response = self.llm_client.complete(
                messages=[LLMMessage(role="user", content=prompt)],
                provider="qwen",
                model="qwen-max",
                temperature=0.3,
                max_tokens=1500,
            )

            return self._parse_pharmacophores(response.content)
        except Exception as e:
            print(f"LLM提取药效团失败: {e}")
            return self._rule_based_pharmacophores(molecules, docking_data)

    def _generate_optimization_suggestions(
        self,
        molecules: list[Molecule],
        sar_patterns: list[SARPattern],
        pharmacophores: list[Pharmacophore],
        use_llm: bool,
    ) -> list[OptimizationSuggestion]:
        """生成优化建议"""
        if not use_llm or not molecules:
            return []

        # 构建上下文
        sar_summary = "\n".join(
            f"- {p.pattern_type}: {p.description}" for p in sar_patterns[:5]
        )
        pharm_summary = "\n".join(
            (
                f"- {p.description} "
                f"(importance: {self._format_optional_number(p.importance_score)})"
            )
            for p in pharmacophores[:3]
        )

        prompt = f"""基于以下计算评分关系和药效团假设，提供分子优化假设。

## SAR模式
{sar_summary or '无'}

## 药效团
{pharm_summary or '无'}

请以 JSON 数组返回优化建议：
[
  {{
    "modification_type": "add_group/remove_group/replace_group/change_scaffold",
    "target_position": "目标位置描述",
    "rationale": "理由",
    "expected_improvement": "预期改进",
    "predicted_effect": "improve_docking_score/worsen_docking_score/uncertain"
  }}
]
"""

        try:
            response = self.llm_client.complete(
                messages=[LLMMessage(role="user", content=prompt)],
                provider="qwen",
                model="qwen-max",
                temperature=0.3,
                max_tokens=1500,
            )

            return self._parse_optimization_suggestions(response.content)
        except Exception as e:
            print(f"LLM生成优化建议失败: {e}")
            return []

    def _summarize_key_findings(
        self,
        sar_patterns: list[SARPattern],
        pharmacophores: list[Pharmacophore],
        optimization_suggestions: list[OptimizationSuggestion],
    ) -> list[str]:
        """总结关键发现"""
        findings = []
        findings.append(f"识别了{len(sar_patterns)}个计算评分关系假设")
        findings.append(f"提出了{len(pharmacophores)}个候选药效团假设")
        findings.append(f"生成了{len(optimization_suggestions)}条待验证优化假设")
        findings.append("Vina 对接评分未被解释为实验活性")
        return findings

    # 辅助方法

    def _build_molecule_table(
        self, molecules: list[Molecule], docking_data: dict
    ) -> str:
        """构建分子对比表"""
        lines = ["ID | SMILES | Vina Docking Score (computed, not assay activity)"]
        lines.append("---|--------|-----------------------------------------------")
        for m in molecules[:20]:  # 限制20个分子以避免token过多
            result = docking_data.get(m.molecule_id)
            score_str = self._format_optional_number(
                getattr(result, "vina_score", None)
            )
            lines.append(f"{m.molecule_id} | {m.smiles[:50]} | {score_str}")
        return "\n".join(lines)

    @staticmethod
    def _format_optional_number(value: Any, missing: str = "N/A") -> str:
        if value is None:
            return missing
        try:
            return f"{float(value):.2f}"
        except (TypeError, ValueError):
            return missing

    def _get_best_docking_molecules(
        self, molecules: list[Molecule], docking_data: dict
    ) -> list[Molecule]:
        """获取 Vina 对接评分较优分子；不推断实验活性。"""
        best_docked = []
        for m in molecules:
            result = docking_data.get(m.molecule_id)
            if result and result.vina_score is not None and result.vina_score < -7.0:
                best_docked.append(m)
        best_docked.sort(key=lambda m: docking_data[m.molecule_id].vina_score)
        return best_docked

    def _parse_sar_patterns(self, content: str) -> list[SARPattern]:
        """解析LLM返回的SAR模式"""
        try:
            json_match = re.search(r'\[.*\]', content, re.DOTALL)
            if json_match:
                results = json.loads(json_match.group())
                patterns = []
                for item in results:
                    score_range = item.get("score_range") or item.get("activity_range")
                    if score_range and len(score_range) == 2:
                        score_range = tuple(score_range)
                    else:
                        score_range = None

                    pattern_type = str(item.get("pattern_type") or "docking_score_shift")
                    if pattern_type == "activity_cliff":
                        pattern_type = "docking_score_shift"

                    patterns.append(
                        SARPattern(
                            pattern_type=pattern_type,
                            description=item["description"],
                            molecules=item["molecules"],
                            structural_change=item["structural_change"],
                            activity_range=None,
                            score_range=score_range,
                            score_type="vina_docking_score",
                            evidence_kind="computational_docking",
                            caveats=["not_experimental_activity"],
                        )
                    )
                return patterns
        except Exception as e:
            print(f"解析SAR模式失败: {e}")
        return []

    def _parse_pharmacophores(self, content: str) -> list[Pharmacophore]:
        """解析LLM返回的药效团"""
        try:
            json_match = re.search(r'\[.*\]', content, re.DOTALL)
            if json_match:
                results = json.loads(json_match.group())
                return [Pharmacophore(**item) for item in results]
        except Exception as e:
            print(f"解析药效团失败: {e}")
        return []

    def _parse_optimization_suggestions(self, content: str) -> list[OptimizationSuggestion]:
        """解析LLM返回的优化建议"""
        try:
            json_match = re.search(r'\[.*\]', content, re.DOTALL)
            if json_match:
                results = json.loads(json_match.group())
                suggestions = []
                for item in results:
                    predicted_effect = item.get("predicted_effect")
                    if predicted_effect is None:
                        legacy_effect = item.get("predicted_activity_change", "uncertain")
                        predicted_effect = {
                            "increase": "improve_docking_score",
                            "decrease": "worsen_docking_score",
                            "maintain": "uncertain",
                        }.get(legacy_effect, "uncertain")
                    suggestions.append(
                        OptimizationSuggestion(
                            modification_type=item["modification_type"],
                            target_position=item["target_position"],
                            rationale=item["rationale"],
                            expected_improvement=item["expected_improvement"],
                            predicted_effect=predicted_effect,
                        )
                    )
                return suggestions
        except Exception as e:
            print(f"解析优化建议失败: {e}")
        return []

    def _rule_based_sar_patterns(
        self, molecules: list[Molecule], docking_data: dict
    ) -> list[SARPattern]:
        """基于规则的SAR模式识别（回退方案）"""
        # 简化实现：基于Tanimoto相似度聚类
        try:
            from rdkit import Chem
            from rdkit.Chem import AllChem, DataStructs

            patterns = []
            mol_objs = []
            for m in molecules:
                mol = Chem.MolFromSmiles(m.smiles)
                if mol:
                    mol_objs.append((m, mol))

            # 寻找相似结构之间的对接评分显著变化；不得称为活性悬崖
            for i, (m1, mol1) in enumerate(mol_objs):
                for m2, mol2 in mol_objs[i + 1:]:
                    fp1 = AllChem.GetMorganFingerprintAsBitVect(mol1, 2)
                    fp2 = AllChem.GetMorganFingerprintAsBitVect(mol2, 2)
                    similarity = DataStructs.TanimotoSimilarity(fp1, fp2)

                    result1 = docking_data.get(m1.molecule_id)
                    result2 = docking_data.get(m2.molecule_id)

                    if (
                        similarity > 0.8
                        and result1
                        and result1.vina_score is not None
                        and result2
                        and result2.vina_score is not None
                    ):
                        score_diff = abs(result1.vina_score - result2.vina_score)
                        if score_diff > 2.0:
                            patterns.append(
                                SARPattern(
                                    pattern_type="docking_score_shift",
                                    description=(
                                        "相似结构的 Vina 对接评分差异显著；"
                                        "该现象不是实验活性悬崖"
                                    ),
                                    molecules=[m1.molecule_id, m2.molecule_id],
                                    structural_change="微小结构变化",
                                    activity_range=None,
                                    score_range=(
                                        min(result1.vina_score, result2.vina_score),
                                        max(result1.vina_score, result2.vina_score),
                                    ),
                                    score_type="vina_docking_score",
                                    evidence_kind="computational_docking",
                                    caveats=["not_experimental_activity"],
                                )
                            )

            return patterns[:10]  # 限制返回数量
        except ImportError:
            return []

    def _rule_based_pharmacophores(
        self, molecules: list[Molecule], docking_data: dict
    ) -> list[Pharmacophore]:
        """基于规则的药效团提取（回退方案）"""
        return [
            Pharmacophore(
                features=["HBD", "Aromatic", "Hydrophobic"],
                description="基于结构规则提出的候选药效团假设，未经实验验证",
                importance_score=0.8,
            )
        ]
