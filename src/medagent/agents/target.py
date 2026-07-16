"""
Target Agent - 靶点分析智能体

功能：
1. 靶点验证和可成药性分析
2. 疾病关联分析
3. 结合位点预测
4. 靶点文献分析
5. 竞争药物分析
"""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from medagent.db.models import Project
from medagent.llm import LLMMessage, get_llm_client


@dataclass
class TargetValidationResult:
    """靶点验证结果"""
    target_name: str
    is_druggable: bool
    druggability_score: float  # 0-1
    druggability_reasons: list[str] = field(default_factory=list)
    known_inhibitors: list[str] = field(default_factory=list)
    structural_info: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    druggability_score_semantics: str = "heuristic_not_probability"


@dataclass
class DiseaseAssociation:
    """疾病关联"""
    disease: str
    association_strength: str  # strong, moderate, weak
    evidence_level: str  # clinical, preclinical, computational
    description: str
    references: list[str] = field(default_factory=list)


@dataclass
class BindingSitePrediction:
    """结合位点预测"""
    site_id: str
    site_name: str
    residues: list[str]
    center_coordinates: list[float] | None
    volume: float | None
    druggability_score: float  # 0-1
    description: str
    druggability_score_semantics: str = "llm_or_rule_based_heuristic_not_probability"


@dataclass
class CompetitiveDrug:
    """竞争药物"""
    drug_name: str
    drug_type: str  # approved, clinical_trial, preclinical
    phase: str | None  # Phase I/II/III/Approved
    mechanism: str
    company: str | None


@dataclass
class TargetAnalysisReport:
    """靶点分析报告"""
    target_protein: str
    validation_result: TargetValidationResult
    disease_associations: list[DiseaseAssociation] = field(default_factory=list)
    binding_sites: list[BindingSitePrediction] = field(default_factory=list)
    competitive_drugs: list[CompetitiveDrug] = field(default_factory=list)
    literature_summary: str = ""
    recommendations: list[str] = field(default_factory=list)
    risk_assessment: str = ""
    target_support_score: float = 0.0
    score_semantics: str = "heuristic_not_probability"


class TargetAgent:
    """靶点分析Agent"""

    def __init__(self, db: Session):
        self.db = db
        self._llm_client: Any | None = None

    @property
    def llm_client(self) -> Any:
        if self._llm_client is None:
            self._llm_client = get_llm_client()
        return self._llm_client

    def analyze_target(
        self,
        project: Project,
        use_llm: bool = True,
    ) -> TargetAnalysisReport:
        """
        分析靶点

        Args:
            project: 项目对象
            use_llm: 是否使用LLM进行深度分析

        Returns:
            TargetAnalysisReport
        """
        target_protein = getattr(project, "target_protein", None) or project.target_id or project.name
        disease_area = getattr(project, "disease_area", None) or project.objective or "unknown"

        # 1. 靶点验证
        validation_result = self._validate_target(target_protein, disease_area, use_llm)

        # 2. 疾病关联分析
        disease_associations = self._analyze_disease_associations(
            target_protein, disease_area, use_llm
        )

        # 3. 结合位点预测
        binding_sites = self._predict_binding_sites(target_protein, use_llm)

        # 4. 竞争药物分析
        competitive_drugs = self._analyze_competitive_drugs(
            target_protein, disease_area, use_llm
        )

        # 5. 文献总结
        literature_summary = self._summarize_literature(
            target_protein, disease_area, use_llm
        ) if use_llm else ""

        # 6. 生成建议
        recommendations = self._generate_recommendations(
            validation_result,
            disease_associations,
            competitive_drugs,
        )

        # 7. 风险评估
        risk_assessment = self._assess_risks(
            validation_result,
            disease_associations,
            competitive_drugs,
        )

        # 8. 靶点支持度启发式评分；不是项目成功概率
        target_support_score = self._estimate_target_support_score(
            validation_result,
            disease_associations,
            competitive_drugs,
        )

        return TargetAnalysisReport(
            target_protein=target_protein,
            validation_result=validation_result,
            disease_associations=disease_associations,
            binding_sites=binding_sites,
            competitive_drugs=competitive_drugs,
            literature_summary=literature_summary,
            recommendations=recommendations,
            risk_assessment=risk_assessment,
            target_support_score=target_support_score,
        )

    def _validate_target(
        self,
        target_protein: str,
        disease_area: str,
        use_llm: bool,
    ) -> TargetValidationResult:
        """验证靶点可成药性"""

        if use_llm:
            # 使用LLM分析
            prompt = f"""
作为一名药物靶点专家，请分析以下靶点的可成药性：

靶点蛋白：{target_protein}
疾病领域：{disease_area}

请从以下方面进行分析：
1. 靶点是否具有可成药性（druggable）
2. 可成药性评分（0-1分）
3. 可成药性原因（结构特征、配体结合口袋、已知抑制剂等）
4. 已知的抑制剂或调节剂
5. 结构信息（如PDB ID）
6. 潜在的挑战和警告

请以JSON格式返回结果：
{{
    "is_druggable": true/false,
    "druggability_score": 0-1,
    "reasons": ["原因1", "原因2"],
    "known_inhibitors": ["抑制剂1", "抑制剂2"],
    "pdb_ids": ["PDB_ID1"],
    "warnings": ["警告1"]
}}
"""

            messages = [LLMMessage(role="user", content=prompt)]

            try:
                response = self.llm_client.complete(
                    messages=messages,
                    provider="qwen",
                    model="qwen-max",
                    temperature=0.3,
                    max_tokens=2000,
                )

                # 解析JSON响应
                import json
                import re

                # 提取JSON
                content = response.content
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    result_data = json.loads(json_match.group())

                    return TargetValidationResult(
                        target_name=target_protein,
                        is_druggable=result_data.get("is_druggable", False),
                        druggability_score=result_data.get("druggability_score", 0.5),
                        druggability_reasons=result_data.get("reasons", []),
                        known_inhibitors=result_data.get("known_inhibitors", []),
                        structural_info={"pdb_ids": result_data.get("pdb_ids", [])},
                        warnings=result_data.get("warnings", []),
                    )

            except Exception as e:
                print(f"LLM分析失败: {e}")

        # 基于规则的简单验证
        return self._rule_based_target_validation(target_protein)

    def _rule_based_target_validation(self, target_protein: str) -> TargetValidationResult:
        """基于规则的靶点验证"""

        # 简化的验证逻辑
        known_druggable = [
            "kinase", "EGFR", "VEGFR", "BCR-ABL", "JAK", "BRAF",
            "protease", "GPCR", "receptor", "channel", "transporter"
        ]

        is_druggable = any(term.lower() in target_protein.lower() for term in known_druggable)

        druggability_score = 0.7 if is_druggable else 0.4

        reasons = []
        if is_druggable:
            reasons.append("靶点属于已知可成药蛋白家族")
        else:
            reasons.append("需要进一步验证靶点可成药性")

        return TargetValidationResult(
            target_name=target_protein,
            is_druggable=is_druggable,
            druggability_score=druggability_score,
            druggability_reasons=reasons,
            known_inhibitors=[],
            structural_info={},
            warnings=[] if is_druggable else ["靶点可成药性存在不确定性"],
        )

    def _analyze_disease_associations(
        self,
        target_protein: str,
        disease_area: str,
        use_llm: bool,
    ) -> list[DiseaseAssociation]:
        """分析疾病关联"""

        if use_llm:
            prompt = f"""
作为疾病生物学专家，请分析靶点 {target_protein} 与疾病 {disease_area} 的关联：

请列出：
1. 与该靶点相关的疾病
2. 关联强度（strong/moderate/weak）
3. 证据水平（clinical/preclinical/computational）
4. 简要描述

返回JSON数组格式：
[
  {{
    "disease": "疾病名称",
    "association_strength": "strong/moderate/weak",
    "evidence_level": "clinical/preclinical/computational",
    "description": "简要描述",
    "references": []
  }}
]
"""

            messages = [LLMMessage(role="user", content=prompt)]

            try:
                response = self.llm_client.complete(
                    messages=messages,
                    provider="qwen",
                    model="qwen-max",
                    temperature=0.3,
                    max_tokens=1500,
                )

                # 解析JSON响应
                import json
                import re

                content = response.content
                json_match = re.search(r'\[.*\]', content, re.DOTALL)
                if json_match:
                    results = json.loads(json_match.group())
                    return [DiseaseAssociation(**item) for item in results]

            except Exception as e:
                print(f"LLM分析失败: {e}")

        # 默认返回
        return [
            DiseaseAssociation(
                disease=disease_area,
                association_strength="moderate",
                evidence_level="preclinical",
                description=f"{target_protein}与{disease_area}的关联需要进一步验证",
                references=[],
            )
        ]

    def _predict_binding_sites(
        self,
        target_protein: str,
        use_llm: bool,
    ) -> list[BindingSitePrediction]:
        """预测结合位点"""

        if use_llm:
            prompt = f"""
作为结构生物学专家，请分析靶点 {target_protein} 的潜在结合位点：

请列出：
1. 结合位点ID和名称
2. 关键残基（如果已知）
3. 中心坐标（如果已知PDB结构）
4. 位点体积（单位：Å³）
5. 可成药性评分（0-1）
6. 位点描述

返回JSON数组格式：
[
  {{
    "site_id": "site1",
    "site_name": "Active Site",
    "residues": ["TYR123", "ASP456"],
    "center_coordinates": [x, y, z],
    "volume": 500.0,
    "druggability_score": 0.8,
    "description": "主要活性位点"
  }}
]
"""

            messages = [LLMMessage(role="user", content=prompt)]

            try:
                response = self.llm_client.complete(
                    messages=messages,
                    provider="qwen",
                    model="qwen-max",
                    temperature=0.3,
                    max_tokens=1500,
                )

                import json
                import re

                content = response.content
                json_match = re.search(r'\[.*\]', content, re.DOTALL)
                if json_match:
                    results = json.loads(json_match.group())
                    return [BindingSitePrediction(**item) for item in results]

            except Exception as e:
                print(f"LLM预测失败: {e}")

        # 默认返回
        return [
            BindingSitePrediction(
                site_id="site1",
                site_name="Active Site",
                residues=[],
                center_coordinates=None,
                volume=None,
                druggability_score=0.7,
                description="主要活性位点，推荐用于小分子设计",
            )
        ]

    def _analyze_competitive_drugs(
        self,
        target_protein: str,
        disease_area: str,
        use_llm: bool,
    ) -> list[CompetitiveDrug]:
        """分析竞争药物"""

        if use_llm:
            prompt = f"""
作为药物市场分析专家，请列出针对 {target_protein} 靶点在 {disease_area} 领域的竞争药物：

请列出：
1. 药物名称
2. 药物类型（approved/clinical_trial/preclinical）
3. 临床阶段（Phase I/II/III/Approved）
4. 作用机制
5. 开发公司

返回JSON数组格式：
[
  {{
    "drug_name": "药物名称",
    "drug_type": "approved/clinical_trial/preclinical",
    "phase": "Phase III",
    "mechanism": "作用机制",
    "company": "公司名称"
  }}
]
"""

            messages = [LLMMessage(role="user", content=prompt)]

            try:
                response = self.llm_client.complete(
                    messages=messages,
                    provider="qwen",
                    model="qwen-max",
                    temperature=0.3,
                    max_tokens=1500,
                )

                import json
                import re

                content = response.content
                json_match = re.search(r'\[.*\]', content, re.DOTALL)
                if json_match:
                    results = json.loads(json_match.group())
                    return [CompetitiveDrug(**item) for item in results]

            except Exception as e:
                print(f"LLM分析失败: {e}")

        # 默认返回空列表
        return []

    def _summarize_literature(
        self,
        target_protein: str,
        disease_area: str,
        use_llm: bool,
    ) -> str:
        """文献总结"""

        if use_llm:
            prompt = f"""
请总结靶点 {target_protein} 在 {disease_area} 领域的最新研究进展（200字以内）。
"""

            messages = [LLMMessage(role="user", content=prompt)]

            try:
                response = self.llm_client.complete(
                    messages=messages,
                    provider="qwen",
                    temperature=0.5,
                    max_tokens=500,
                )

                return response.content

            except Exception as e:
                print(f"文献总结失败: {e}")

        return f"{target_protein}是{disease_area}领域的重要靶点，相关研究正在进行中。"

    def _generate_recommendations(
        self,
        validation_result: TargetValidationResult,
        disease_associations: list[DiseaseAssociation],
        competitive_drugs: list[CompetitiveDrug],
    ) -> list[str]:
        """生成建议"""

        recommendations = []

        if validation_result.is_druggable:
            recommendations.append("靶点具有良好的可成药性，建议继续推进")
        else:
            recommendations.append("建议进一步验证靶点可成药性")

        if validation_result.known_inhibitors:
            recommendations.append("可参考已知抑制剂进行结构优化")

        strong_associations = [
            a for a in disease_associations
            if a.association_strength == "strong"
        ]
        if strong_associations:
            recommendations.append("靶点与疾病关联强，临床前景良好")

        if len(competitive_drugs) > 5:
            recommendations.append("竞争激烈，需要差异化策略")

        return recommendations

    def _assess_risks(
        self,
        validation_result: TargetValidationResult,
        disease_associations: list[DiseaseAssociation],
        competitive_drugs: list[CompetitiveDrug],
    ) -> str:
        """评估风险"""

        risks = []

        if not validation_result.is_druggable:
            risks.append("靶点可成药性不确定")

        if validation_result.warnings:
            risks.extend(validation_result.warnings)

        weak_associations = [
            a for a in disease_associations
            if a.association_strength == "weak"
        ]
        if weak_associations:
            risks.append("部分疾病关联证据较弱")

        approved_competitors = [
            d for d in competitive_drugs
            if d.phase == "Approved"
        ]
        if approved_competitors:
            risks.append(f"已有{len(approved_competitors)}个获批竞品")

        if risks:
            return "主要风险：" + "；".join(risks)
        else:
            return "风险可控"

    def _estimate_target_support_score(
        self,
        validation_result: TargetValidationResult,
        disease_associations: list[DiseaseAssociation],
        competitive_drugs: list[CompetitiveDrug],
    ) -> float:
        """计算靶点证据支持度启发式评分；该值不是校准概率。"""

        score = 0.0

        # 可成药性贡献
        score += validation_result.druggability_score * 0.4

        # 疾病关联贡献
        strong_count = sum(
            1 for a in disease_associations
            if a.association_strength == "strong"
        )
        if strong_count > 0:
            score += min(0.3, strong_count * 0.15)

        # 已知抑制剂加分
        if validation_result.known_inhibitors:
            score += 0.1

        # 竞争扣分
        if len(competitive_drugs) > 3:
            score -= 0.1

        return max(0.0, min(1.0, score))
