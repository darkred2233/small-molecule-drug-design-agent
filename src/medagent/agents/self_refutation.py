"""
Self-Refutation Agent

负责质疑和验证分子推荐的合理性，从批判性角度审查候选分子。

功能：
1. 对推荐分子提出质疑和反驳
2. 识别潜在的风险和问题
3. 验证评估逻辑的合理性
4. 提供改进建议
"""

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from medagent.db.models import (
    ADMETResult,
    DockingResult,
    Molecule,
    MoleculeProperty,
    Project,
    SynthesisRoute,
)


@dataclass
class RefutationPoint:
    """反驳点"""
    category: str  # structure, admet, docking, synthesis, logic
    severity: str  # critical, high, medium, low
    title: str
    description: str
    evidence: list[str] = field(default_factory=list)
    recommendation: str | None = None


@dataclass
class RefutationResult:
    """反驳结果"""
    molecule_id: str
    overall_assessment: str  # rejected, questionable, acceptable, recommended
    refutation_points: list[RefutationPoint] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    confidence_score: float = 0.0  # 0-1
    recommendation: str | None = None


class SelfRefutationAgent:
    """自我反驳Agent"""

    def __init__(self, db: Session):
        self.db = db

    def refute_molecule(
        self,
        project: Project,
        molecule: Molecule,
        strict_mode: bool = False,
    ) -> RefutationResult:
        """
        对单个分子进行批判性审查

        Args:
            project: 项目
            molecule: 分子
            strict_mode: 严格模式（提高标准）

        Returns:
            RefutationResult
        """
        refutation_points: list[RefutationPoint] = []
        strengths: list[str] = []
        weaknesses: list[str] = []

        # 获取分子的所有评估数据
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

        # 1. 结构质疑
        structure_refutations = self._refute_structure(
            molecule, mol_property, strict_mode
        )
        refutation_points.extend(structure_refutations)

        # 2. ADMET质疑
        admet_refutations = self._refute_admet(
            molecule, admet_result, strict_mode
        )
        refutation_points.extend(admet_refutations)

        # 3. 对接质疑
        docking_refutations = self._refute_docking(
            molecule, docking_result, strict_mode
        )
        refutation_points.extend(docking_refutations)

        # 4. 合成质疑
        synthesis_refutations = self._refute_synthesis(
            molecule, synthesis_route, strict_mode
        )
        refutation_points.extend(synthesis_refutations)

        # 5. 逻辑一致性检查
        logic_refutations = self._check_logical_consistency(
            molecule, mol_property, admet_result, docking_result, synthesis_route
        )
        refutation_points.extend(logic_refutations)

        # 识别优势和劣势
        strengths = self._identify_strengths(
            mol_property, admet_result, docking_result, synthesis_route
        )
        weaknesses = self._identify_weaknesses(refutation_points)

        # 综合评估
        overall_assessment, confidence_score, recommendation = self._overall_assessment(
            refutation_points, strengths, weaknesses, strict_mode
        )

        return RefutationResult(
            molecule_id=molecule.molecule_id,
            overall_assessment=overall_assessment,
            refutation_points=refutation_points,
            strengths=strengths,
            weaknesses=weaknesses,
            confidence_score=confidence_score,
            recommendation=recommendation,
        )

    def _refute_structure(
        self,
        molecule: Molecule,
        mol_property: MoleculeProperty | None,
        strict_mode: bool,
    ) -> list[RefutationPoint]:
        """质疑分子结构"""
        refutations: list[RefutationPoint] = []

        if not mol_property:
            refutations.append(RefutationPoint(
                category="structure",
                severity="high",
                title="缺失分子性质数据",
                description="无法获取分子的基础性质信息",
                evidence=["mol_property_missing"],
                recommendation="重新计算分子描述符",
            ))
            return refutations

        # Lipinski规则违规
        if not mol_property.lipinski_compliant:
            severity = "high" if strict_mode else "medium"
            refutations.append(RefutationPoint(
                category="structure",
                severity=severity,
                title="Lipinski五规则违规",
                description=f"分子违反了{mol_property.lipinski_violations}条Lipinski规则",
                evidence=[
                    f"MW: {mol_property.mw} ({'违规' if mol_property.mw > 500 else '合规'})",
                    f"LogP: {mol_property.logp} ({'违规' if mol_property.logp > 5 else '合规'})",
                    f"HBD: {mol_property.hbd} ({'违规' if mol_property.hbd > 5 else '合规'})",
                    f"HBA: {mol_property.hba} ({'违规' if mol_property.hba > 10 else '合规'})",
                ],
                recommendation="考虑结构简化或增加极性基团以改善成药性",
            ))

        # 结构警报
        if "pains_alert" in mol_property.labels:
            refutations.append(RefutationPoint(
                category="structure",
                severity="critical",
                title="PAINS结构警报",
                description="分子包含泛干扰化合物（PAINS）结构",
                evidence=mol_property.warnings or [],
                recommendation="移除或替换含PAINS的子结构",
            ))

        # QED评分过低
        if mol_property.qed and mol_property.qed < 0.3:
            severity = "high" if strict_mode else "medium"
            refutations.append(RefutationPoint(
                category="structure",
                severity=severity,
                title="QED药物相似性评分过低",
                description=f"QED评分为{mol_property.qed:.3f}，远低于药物标准",
                evidence=[f"QED: {mol_property.qed:.3f} (推荐 >0.5)"],
                recommendation="优化分子结构以提高QED评分",
            ))

        # 分子量异常
        if mol_property.mw > 600:
            refutations.append(RefutationPoint(
                category="structure",
                severity="medium",
                title="分子量过大",
                description=f"分子量{mol_property.mw:.1f}可能影响口服吸收",
                evidence=[f"MW: {mol_property.mw:.1f} Da"],
                recommendation="考虑去除非必需的官能团以降低分子量",
            ))
        elif mol_property.mw < 200:
            refutations.append(RefutationPoint(
                category="structure",
                severity="low",
                title="分子量过小",
                description=f"分子量{mol_property.mw:.1f}可能缺乏足够的特异性",
                evidence=[f"MW: {mol_property.mw:.1f} Da"],
                recommendation="考虑增加功能性基团以提高特异性",
            ))

        return refutations

    def _refute_admet(
        self,
        molecule: Molecule,
        admet_result: ADMETResult | None,
        strict_mode: bool,
    ) -> list[RefutationPoint]:
        """质疑ADMET预测"""
        refutations: list[RefutationPoint] = []

        if not admet_result:
            refutations.append(RefutationPoint(
                category="admet",
                severity="high",
                title="缺失ADMET预测数据",
                description="无法评估分子的ADMET风险",
                evidence=["admet_result_missing"],
                recommendation="运行ADMET预测",
            ))
            return refutations

        # hERG心脏毒性
        if admet_result.hERG_risk == "high_risk":
            refutations.append(RefutationPoint(
                category="admet",
                severity="critical",
                title="hERG心脏毒性风险高",
                description=f"hERG阻断概率为{admet_result.hERG_probability:.3f}",
                evidence=[
                    f"hERG概率: {admet_result.hERG_probability:.3f}",
                    f"风险等级: {admet_result.hERG_risk}",
                ],
                recommendation="降低碱性、减少疏水性或增加极性基团",
            ))
        elif admet_result.hERG_risk == "medium_risk" and strict_mode:
            refutations.append(RefutationPoint(
                category="admet",
                severity="high",
                title="hERG心脏毒性风险中等",
                description="在严格模式下，中等风险不可接受",
                evidence=[f"hERG概率: {admet_result.hERG_probability:.3f}"],
                recommendation="优化结构以降低hERG风险",
            ))

        # Ames致突变性
        if admet_result.Ames_risk == "high_risk":
            refutations.append(RefutationPoint(
                category="admet",
                severity="critical",
                title="Ames致突变性风险高",
                description=f"Ames阳性概率为{admet_result.Ames_probability:.3f}",
                evidence=[
                    f"Ames概率: {admet_result.Ames_probability:.3f}",
                    f"风险等级: {admet_result.Ames_risk}",
                ],
                recommendation="去除芳香胺、硝基等警报结构",
            ))

        # DILI肝毒性
        if admet_result.DILI_risk == "high_risk":
            refutations.append(RefutationPoint(
                category="admet",
                severity="high",
                title="DILI肝毒性风险高",
                description=f"肝损伤风险概率为{admet_result.DILI_probability:.3f}",
                evidence=[f"DILI概率: {admet_result.DILI_probability:.3f}"],
                recommendation="优化结构以降低肝毒性风险",
            ))

        # CYP抑制
        if (admet_result.CYP3A4_risk == "high_risk" or
            admet_result.CYP2D6_risk == "high_risk"):
            refutations.append(RefutationPoint(
                category="admet",
                severity="medium",
                title="CYP酶抑制风险",
                description="可能影响药物代谢和药物相互作用",
                evidence=[
                    f"CYP3A4: {admet_result.CYP3A4_risk}",
                    f"CYP2D6: {admet_result.CYP2D6_risk}",
                ],
                recommendation="降低脂溶性或调整芳香环系统",
            ))

        # 溶解度问题
        if admet_result.solubility == "low":
            severity = "high" if strict_mode else "medium"
            refutations.append(RefutationPoint(
                category="admet",
                severity=severity,
                title="溶解度低",
                description="低溶解度可能影响生物利用度",
                evidence=[f"溶解度: {admet_result.solubility}"],
                recommendation="增加极性基团或引入可电离基团",
            ))

        return refutations

    def _refute_docking(
        self,
        molecule: Molecule,
        docking_result: DockingResult | None,
        strict_mode: bool,
    ) -> list[RefutationPoint]:
        """质疑对接结果"""
        refutations: list[RefutationPoint] = []

        if not docking_result:
            refutations.append(RefutationPoint(
                category="docking",
                severity="high",
                title="缺失对接数据",
                description="无法评估分子与靶点的结合能力",
                evidence=["docking_result_missing"],
                recommendation="运行分子对接",
            ))
            return refutations

        # Vina评分过高（结合差）
        if docking_result.vina_score and docking_result.vina_score > -6.0:
            severity = "high" if strict_mode else "medium"
            refutations.append(RefutationPoint(
                category="docking",
                severity=severity,
                title="对接评分差",
                description=f"Vina评分为{docking_result.vina_score:.2f}，结合亲和力不足",
                evidence=[
                    f"Vina评分: {docking_result.vina_score:.2f} kcal/mol",
                    "推荐阈值: < -7.0 kcal/mol",
                ],
                recommendation="优化结构以增强与靶点的相互作用",
            ))

        # CNN评分低（如果有）
        if docking_result.cnn_score and docking_result.cnn_score < 0.5:
            refutations.append(RefutationPoint(
                category="docking",
                severity="medium",
                title="CNN评分低",
                description=f"CNN预测的结合概率为{docking_result.cnn_score:.3f}",
                evidence=[f"CNN评分: {docking_result.cnn_score:.3f}"],
                recommendation="考虑结构优化以改善结合姿态",
            ))

        # 对接警告
        if docking_result.warnings:
            refutations.append(RefutationPoint(
                category="docking",
                severity="medium",
                title="对接过程警告",
                description="对接过程中出现异常或警告",
                evidence=docking_result.warnings,
                recommendation="检查对接参数或重新运行",
            ))

        return refutations

    def _refute_synthesis(
        self,
        molecule: Molecule,
        synthesis_route: SynthesisRoute | None,
        strict_mode: bool,
    ) -> list[RefutationPoint]:
        """质疑合成可及性"""
        refutations: list[RefutationPoint] = []

        if not synthesis_route:
            refutations.append(RefutationPoint(
                category="synthesis",
                severity="medium",
                title="缺失合成评估",
                description="无法评估分子的合成可及性",
                evidence=["synthesis_route_missing"],
                recommendation="运行合成可及性评估",
            ))
            return refutations

        # SA Score过高（难以合成）
        if synthesis_route.sa_score and synthesis_route.sa_score > 6.0:
            severity = "high" if strict_mode else "medium"
            refutations.append(RefutationPoint(
                category="synthesis",
                severity=severity,
                title="合成难度高",
                description=f"SA Score为{synthesis_route.sa_score:.2f}，合成非常困难",
                evidence=[
                    f"SA Score: {synthesis_route.sa_score:.2f}",
                    f"复杂度: {synthesis_route.complexity_level}",
                ],
                recommendation="简化分子结构或寻找更易合成的类似物",
            ))
        elif synthesis_route.sa_score and synthesis_route.sa_score > 5.0 and strict_mode:
            refutations.append(RefutationPoint(
                category="synthesis",
                severity="medium",
                title="合成难度偏高",
                description=f"SA Score为{synthesis_route.sa_score:.2f}",
                evidence=[f"SA Score: {synthesis_route.sa_score:.2f}"],
                recommendation="考虑结构简化",
            ))

        # 未找到合成路线
        if synthesis_route.route_found is False:
            refutations.append(RefutationPoint(
                category="synthesis",
                severity="high",
                title="未找到合成路线",
                description="逆合成分析未找到可行的合成路线",
                evidence=["no_synthesis_route"],
                recommendation="重新设计分子或使用更简单的结构",
            ))

        return refutations

    def _check_logical_consistency(
        self,
        molecule: Molecule,
        mol_property: MoleculeProperty | None,
        admet_result: ADMETResult | None,
        docking_result: DockingResult | None,
        synthesis_route: SynthesisRoute | None,
    ) -> list[RefutationPoint]:
        """检查逻辑一致性"""
        refutations: list[RefutationPoint] = []

        # 检查：高对接分数 vs 高ADMET风险
        if (docking_result and docking_result.vina_score and docking_result.vina_score < -8.0 and
            admet_result and (admet_result.hERG_risk == "high_risk" or
                             admet_result.Ames_risk == "high_risk")):
            refutations.append(RefutationPoint(
                category="logic",
                severity="high",
                title="结合强但ADMET风险高",
                description="虽然对接评分优秀，但存在严重的安全性问题",
                evidence=[
                    f"Vina评分: {docking_result.vina_score:.2f}",
                    f"hERG风险: {admet_result.hERG_risk}",
                    f"Ames风险: {admet_result.Ames_risk}",
                ],
                recommendation="优先解决ADMET问题，即使可能牺牲部分结合亲和力",
            ))

        # 检查：优秀的性质 vs 合成困难
        if (mol_property and mol_property.lipinski_compliant and
            mol_property.qed and mol_property.qed > 0.7 and
            synthesis_route and synthesis_route.sa_score and synthesis_route.sa_score > 7.0):
            refutations.append(RefutationPoint(
                category="logic",
                severity="medium",
                title="性质优秀但合成困难",
                description="分子性质良好，但合成难度很高，可能难以实际应用",
                evidence=[
                    f"QED: {mol_property.qed:.3f}",
                    f"SA Score: {synthesis_route.sa_score:.2f}",
                ],
                recommendation="寻找合成更简单的类似物",
            ))

        # 检查：评估数据不完整
        missing_data = []
        if not mol_property:
            missing_data.append("分子性质")
        if not admet_result:
            missing_data.append("ADMET预测")
        if not docking_result:
            missing_data.append("对接评分")
        if not synthesis_route:
            missing_data.append("合成评估")

        if len(missing_data) >= 2:
            refutations.append(RefutationPoint(
                category="logic",
                severity="high",
                title="评估数据不完整",
                description=f"缺少{len(missing_data)}项关键评估数据",
                evidence=[f"缺失: {', '.join(missing_data)}"],
                recommendation="完成所有必需的评估后再做决策",
            ))

        return refutations

    def _identify_strengths(
        self,
        mol_property: MoleculeProperty | None,
        admet_result: ADMETResult | None,
        docking_result: DockingResult | None,
        synthesis_route: SynthesisRoute | None,
    ) -> list[str]:
        """识别分子优势"""
        strengths: list[str] = []

        if mol_property:
            if mol_property.lipinski_compliant:
                strengths.append("符合Lipinski五规则")
            if mol_property.qed and mol_property.qed > 0.7:
                strengths.append(f"QED评分优秀({mol_property.qed:.3f})")
            if "pains_clean" in mol_property.labels:
                strengths.append("无结构警报")

        if admet_result:
            if admet_result.hERG_risk == "low_risk":
                strengths.append("hERG心脏毒性风险低")
            if admet_result.Ames_risk == "low_risk":
                strengths.append("Ames致突变性风险低")
            if admet_result.solubility in ["high", "medium"]:
                strengths.append("溶解度良好")

        if docking_result:
            if docking_result.vina_score and docking_result.vina_score < -8.0:
                strengths.append(f"对接评分优秀({docking_result.vina_score:.2f} kcal/mol)")
            if docking_result.cnn_score and docking_result.cnn_score > 0.7:
                strengths.append(f"CNN预测置信度高({docking_result.cnn_score:.3f})")

        if synthesis_route:
            if synthesis_route.sa_score and synthesis_route.sa_score < 3.0:
                strengths.append(f"易于合成(SA Score: {synthesis_route.sa_score:.2f})")

        return strengths

    def _identify_weaknesses(
        self,
        refutation_points: list[RefutationPoint],
    ) -> list[str]:
        """识别分子劣势"""
        weaknesses: list[str] = []

        critical_points = [p for p in refutation_points if p.severity == "critical"]
        high_points = [p for p in refutation_points if p.severity == "high"]

        if critical_points:
            weaknesses.append(f"存在{len(critical_points)}个致命问题")
        if high_points:
            weaknesses.append(f"存在{len(high_points)}个高风险问题")

        # 按类别统计
        categories = {}
        for point in refutation_points:
            categories[point.category] = categories.get(point.category, 0) + 1

        for category, count in categories.items():
            if count >= 2:
                category_name = {
                    "structure": "结构",
                    "admet": "ADMET",
                    "docking": "对接",
                    "synthesis": "合成",
                    "logic": "逻辑",
                }.get(category, category)
                weaknesses.append(f"{category_name}方面存在{count}个问题")

        return weaknesses

    def _overall_assessment(
        self,
        refutation_points: list[RefutationPoint],
        strengths: list[str],
        weaknesses: list[str],
        strict_mode: bool,
    ) -> tuple[str, float, str]:
        """综合评估"""

        # 统计各级别问题
        critical_count = sum(1 for p in refutation_points if p.severity == "critical")
        high_count = sum(1 for p in refutation_points if p.severity == "high")
        medium_count = sum(1 for p in refutation_points if p.severity == "medium")
        low_count = sum(1 for p in refutation_points if p.severity == "low")

        # 计算置信度分数
        total_issues = len(refutation_points)
        if total_issues == 0:
            confidence_score = 0.9
        else:
            # 加权扣分
            penalty = (
                critical_count * 0.3 +
                high_count * 0.15 +
                medium_count * 0.05 +
                low_count * 0.02
            )
            confidence_score = max(0.0, 1.0 - penalty)

        # 优势加分
        confidence_score += len(strengths) * 0.02
        confidence_score = min(1.0, confidence_score)

        # 决策逻辑
        if critical_count > 0:
            assessment = "rejected"
            recommendation = f"分子存在{critical_count}个致命问题，不推荐继续"
        elif high_count >= 3 or (strict_mode and high_count >= 2):
            assessment = "rejected"
            recommendation = f"分子存在{high_count}个高风险问题，建议淘汰"
        elif high_count >= 2 or (strict_mode and high_count >= 1):
            assessment = "questionable"
            recommendation = f"分子存在{high_count}个高风险问题，需要优化后重新评估"
        elif high_count == 1 or medium_count >= 3:
            assessment = "questionable"
            recommendation = "分子存在一些问题，建议优化或作为备选"
        elif medium_count >= 1 or low_count >= 2:
            assessment = "acceptable"
            recommendation = "分子基本可接受，但仍有改进空间"
        else:
            assessment = "recommended"
            recommendation = "分子表现优秀，强烈推荐"

        return assessment, confidence_score, recommendation

    def batch_refute(
        self,
        project: Project,
        molecules: list[Molecule],
        strict_mode: bool = False,
    ) -> list[RefutationResult]:
        """批量反驳"""
        return [
            self.refute_molecule(project, molecule, strict_mode)
            for molecule in molecules
        ]
