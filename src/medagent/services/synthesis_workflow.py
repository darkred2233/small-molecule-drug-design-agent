"""
合成可及性评估模块

提供分子合成可及性评估：
1. SA Score (Synthetic Accessibility Score)
2. 可购买砌块检查
3. 逆合成分析（如果有工具）
4. 合成复杂度评估

依赖：
- RDKit (必需，用于SA Score)
- AiZynthFinder (可选，用于逆合成分析)
"""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from medagent.db.models import Molecule, Project, SynthesisRoute
from medagent.services.ids import new_id


@dataclass
class SAScoreResult:
    """SA Score计算结果"""
    success: bool
    sa_score: float | None
    complexity_level: str | None  # easy, medium, hard, very_hard
    warnings: list[str] = field(default_factory=list)


@dataclass
class BuildingBlockCheck:
    """可购买砌块检查结果"""
    smiles: str
    is_available: bool
    vendor: str | None
    catalog_id: str | None
    price_range: str | None


@dataclass
class RetrosynthesisResult:
    """逆合成分析结果"""
    success: bool
    route_found: bool
    num_steps: int | None
    building_blocks: list[BuildingBlockCheck] = field(default_factory=list)
    route_score: float | None = None
    route_summary: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class SynthesisWorkflowResult:
    """合成可及性工作流完整结果"""
    success: bool
    molecule_id: str
    synthesis_route_id: str | None
    sa_score_result: SAScoreResult | None
    retrosynthesis_result: RetrosynthesisResult | None
    overall_assessment: str  # easy, feasible, difficult, very_difficult
    labels: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    runtime_seconds: float = 0.0


def calculate_sa_score(smiles: str) -> SAScoreResult:
    """
    计算SA Score（合成可及性评分）

    SA Score范围：1-10
    - 1-3: 容易合成
    - 3-5: 中等难度
    - 5-7: 困难
    - 7-10: 非常困难

    使用RDKit Contrib中的sascorer模块
    """
    warnings: list[str] = []

    try:
        from rdkit import Chem
        from rdkit.Chem import RDConfig
        import os
        import sys

        # 尝试加载SA scorer
        try:
            sys.path.append(os.path.join(RDConfig.RDContribDir, 'SA_Score'))
            import sascorer
        except (ImportError, AttributeError):
            return SAScoreResult(
                success=False,
                sa_score=None,
                complexity_level=None,
                warnings=["sa_scorer_not_available", "rdkit_contrib_missing"],
            )

    except ImportError:
        return SAScoreResult(
            success=False,
            sa_score=None,
            complexity_level=None,
            warnings=["rdkit_not_available"],
        )

    # 解析SMILES
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return SAScoreResult(
            success=False,
            sa_score=None,
            complexity_level=None,
            warnings=["invalid_smiles"],
        )

    # 计算SA Score
    try:
        sa_score = sascorer.calculateScore(mol)
        sa_score = round(sa_score, 2)

        # 分类复杂度
        if sa_score <= 3.0:
            complexity_level = "easy"
        elif sa_score <= 5.0:
            complexity_level = "medium"
        elif sa_score <= 7.0:
            complexity_level = "hard"
        else:
            complexity_level = "very_hard"

        return SAScoreResult(
            success=True,
            sa_score=sa_score,
            complexity_level=complexity_level,
            warnings=warnings,
        )

    except Exception as e:
        warnings.append(f"sa_score_calculation_error: {str(e)}")
        return SAScoreResult(
            success=False,
            sa_score=None,
            complexity_level=None,
            warnings=warnings,
        )


def estimate_sa_score_from_descriptors(
    mw: float,
    logp: float,
    rotatable_bonds: int,
    rings: int,
    stereocenters: int = 0,
) -> SAScoreResult:
    """
    基于分子描述符估算SA Score

    当SA scorer不可用时的回退方案
    """
    warnings = ["sa_score_estimated_from_descriptors"]

    # 简化的评分规则
    score = 1.0

    # 分子量影响
    if mw > 500:
        score += (mw - 500) / 200
    if mw < 150:
        score += (150 - mw) / 50

    # LogP影响
    if abs(logp) > 5:
        score += abs(logp - 2.5) / 3

    # 旋转键影响
    if rotatable_bonds > 10:
        score += (rotatable_bonds - 10) / 5

    # 环系统影响
    if rings > 4:
        score += (rings - 4) / 2

    # 立体中心影响
    score += stereocenters * 0.5

    # 限制范围
    sa_score = min(max(score, 1.0), 10.0)
    sa_score = round(sa_score, 2)

    # 分类复杂度
    if sa_score <= 3.0:
        complexity_level = "easy"
    elif sa_score <= 5.0:
        complexity_level = "medium"
    elif sa_score <= 7.0:
        complexity_level = "hard"
    else:
        complexity_level = "very_hard"

    return SAScoreResult(
        success=True,
        sa_score=sa_score,
        complexity_level=complexity_level,
        warnings=warnings,
    )


def check_building_block_availability(smiles: str) -> BuildingBlockCheck:
    """
    检查分子是否为可购买砌块

    实际应用中应连接到：
    - ZINC数据库
    - eMolecules
    - Mcule
    - 其他商业化合物库

    这里提供简化版本：基于分子大小和复杂度判断
    """
    try:
        from rdkit import Chem
        from rdkit.Chem import Descriptors, Lipinski
    except ImportError:
        return BuildingBlockCheck(
            smiles=smiles,
            is_available=False,
            vendor=None,
            catalog_id=None,
            price_range=None,
        )

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return BuildingBlockCheck(
            smiles=smiles,
            is_available=False,
            vendor=None,
            catalog_id=None,
            price_range=None,
        )

    # 简化的可购买性判断
    mw = Descriptors.MolWt(mol)
    heavy_atoms = mol.GetNumHeavyAtoms()
    rings = Lipinski.RingCount(mol)

    # 小分子、简单结构更可能可购买
    is_likely_available = (
        mw < 300 and
        heavy_atoms < 20 and
        rings <= 2
    )

    if is_likely_available:
        return BuildingBlockCheck(
            smiles=smiles,
            is_available=True,
            vendor="estimated",
            catalog_id=None,
            price_range="< $100/g",
        )
    else:
        return BuildingBlockCheck(
            smiles=smiles,
            is_available=False,
            vendor=None,
            catalog_id=None,
            price_range=None,
        )


def run_retrosynthesis_analysis(
    smiles: str,
    max_steps: int = 6,
) -> RetrosynthesisResult:
    """
    运行逆合成分析

    尝试使用：
    1. AiZynthFinder (如果可用)
    2. 简化的基于规则的分析

    实际应用中应集成：
    - AiZynthFinder
    - ASKCOS
    - IBM RXN
    - Molecular Transformer
    """
    import os
    from pathlib import Path

    from medagent.services.aizynthfinder_adapter import (
        AiZynthFinderRequest,
        run_aizynthfinder_retrosynthesis,
    )

    warnings: list[str] = []
    config_file = os.environ.get("AIZYNTHFINDER_CONFIG") or os.environ.get(
        "MEDAGENT_AIZYNTHFINDER_CONFIG"
    )
    external_result = run_aizynthfinder_retrosynthesis(
        AiZynthFinderRequest(
            smiles=smiles,
            output_dir=str(Path(".local") / "retrosynthesis"),
            config_file=config_file,
            max_steps=max_steps,
        )
    )
    if external_result.success:
        return RetrosynthesisResult(
            success=True,
            route_found=external_result.route_found,
            num_steps=external_result.num_steps,
            building_blocks=[],
            route_score=external_result.route_score,
            route_summary=external_result.route_summary,
            warnings=external_result.warnings,
        )

    warnings.extend(external_result.warnings)

    # 回退到简化分析
    return _simple_retrosynthesis_estimate(smiles, max_steps, warnings)


def _simple_retrosynthesis_estimate(
    smiles: str,
    max_steps: int,
    warnings: list[str],
) -> RetrosynthesisResult:
    """
    简化的逆合成估算

    基于分子复杂度和官能团判断合成步数
    """
    try:
        from rdkit import Chem
        from rdkit.Chem import Fragments, Lipinski
    except ImportError:
        warnings.append("rdkit_not_available")
        return RetrosynthesisResult(
            success=False,
            route_found=False,
            num_steps=None,
            warnings=warnings,
        )

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        warnings.append("invalid_smiles")
        return RetrosynthesisResult(
            success=False,
            route_found=False,
            num_steps=None,
            warnings=warnings,
        )

    # 计算复杂度指标
    heavy_atoms = mol.GetNumHeavyAtoms()
    rings = Lipinski.RingCount(mol)
    stereocenters = len(Chem.FindMolChiralCenters(mol, includeUnassigned=True))

    # 估算合成步数
    estimated_steps = 1  # 基础步数

    # 重原子数影响
    estimated_steps += heavy_atoms // 8

    # 环系统影响
    estimated_steps += rings // 2

    # 立体中心影响
    estimated_steps += stereocenters

    # 官能团复杂度
    functional_groups = (
        Fragments.fr_Ar_NH(mol) +
        Fragments.fr_Ar_OH(mol) +
        Fragments.fr_COO(mol) +
        Fragments.fr_C_O(mol)
    )
    estimated_steps += functional_groups // 3

    # 限制在合理范围
    estimated_steps = min(max(estimated_steps, 1), 10)

    # 判断是否可行
    route_found = estimated_steps <= max_steps

    # 生成简要说明
    if route_found:
        route_summary = f"估算需要约{estimated_steps}步合成，基于{heavy_atoms}个重原子和{rings}个环"
    else:
        route_summary = f"估算需要{estimated_steps}步，超过最大步数限制{max_steps}"

    # 评分（步数越少越好）
    route_score = max(0, 100 - (estimated_steps * 10))

    warnings.append("retrosynthesis_estimated_not_actual")

    return RetrosynthesisResult(
        success=True,
        route_found=route_found,
        num_steps=estimated_steps,
        building_blocks=[],  # 简化版本不分析砌块
        route_score=round(route_score, 1),
        route_summary=route_summary,
        warnings=warnings,
    )


def run_synthesis_workflow(
    db: Session,
    project: Project,
    molecule: Molecule,
    run_retrosynthesis: bool = False,
    max_synthesis_steps: int = 6,
) -> SynthesisWorkflowResult:
    """
    运行完整合成可及性评估工作流

    参数：
        db: 数据库会话
        project: 项目对象
        molecule: 分子对象
        run_retrosynthesis: 是否运行逆合成分析
        max_synthesis_steps: 最大允许合成步数

    返回：
        SynthesisWorkflowResult
    """
    import time
    start_time = time.monotonic()

    warnings: list[str] = []
    labels: list[str] = []

    # 步骤1: 计算SA Score
    sa_result = calculate_sa_score(molecule.smiles)

    if not sa_result.success:
        # 尝试从分子性质估算
        warnings.extend(sa_result.warnings)

        # 获取分子性质
        from medagent.db.models import MoleculeProperty
        mol_prop = db.query(MoleculeProperty).filter_by(
            molecule_id=molecule.molecule_id
        ).one_or_none()

        if mol_prop:
            sa_result = estimate_sa_score_from_descriptors(
                mw=mol_prop.mw or 0,
                logp=mol_prop.logp or 0,
                rotatable_bonds=mol_prop.tool_metadata.get("rotatable_bond_count", 0),
                rings=mol_prop.tool_metadata.get("ring_count", 0),
            )

    # 步骤2: 逆合成分析（可选）
    retro_result = None
    if run_retrosynthesis:
        retro_result = run_retrosynthesis_analysis(
            molecule.smiles,
            max_steps=max_synthesis_steps,
        )
        warnings.extend(retro_result.warnings)

    # 步骤3: 综合评估
    if sa_result.sa_score:
        if sa_result.sa_score <= 3.0:
            overall_assessment = "easy"
            labels.append("easy_to_synthesize")
        elif sa_result.sa_score <= 5.0:
            overall_assessment = "feasible"
            labels.append("feasible_synthesis")
        elif sa_result.sa_score <= 7.0:
            overall_assessment = "difficult"
            labels.append("difficult_synthesis")
        else:
            overall_assessment = "very_difficult"
            labels.append("very_difficult_synthesis")
    else:
        overall_assessment = "unknown"
        labels.append("synthesis_assessment_failed")

    # 如果有逆合成结果，可以调整评估
    if retro_result and retro_result.success:
        if not retro_result.route_found:
            overall_assessment = "very_difficult"
            labels.append("no_synthesis_route_found")

    # 步骤4: 保存到数据库
    synthesis_route = SynthesisRoute(
        synthesis_route_id=new_id("SYNTH"),
        project_id=project.project_id,
        molecule_id=molecule.molecule_id,
        route_found=retro_result.route_found if retro_result else None,
        num_steps=retro_result.num_steps if retro_result else None,
        route_score=retro_result.route_score if retro_result else None,
        sa_score=sa_result.sa_score,
        complexity_level=sa_result.complexity_level,
        route_summary=retro_result.route_summary if retro_result else None,
        labels=labels,
        warnings=list(set(warnings)),  # 去重
    )

    db.add(synthesis_route)
    db.commit()

    return SynthesisWorkflowResult(
        success=True,
        molecule_id=molecule.molecule_id,
        synthesis_route_id=synthesis_route.synthesis_route_id,
        sa_score_result=sa_result,
        retrosynthesis_result=retro_result,
        overall_assessment=overall_assessment,
        labels=labels,
        warnings=warnings,
        runtime_seconds=time.monotonic() - start_time,
    )


def batch_synthesis_assessment(
    db: Session,
    project: Project,
    molecules: list[Molecule],
    run_retrosynthesis: bool = False,
) -> dict[str, Any]:
    """
    批量合成可及性评估

    参数：
        db: 数据库会话
        project: 项目对象
        molecules: 分子列表
        run_retrosynthesis: 是否运行逆合成分析

    返回：
        评估统计信息
    """
    import time
    start_time = time.monotonic()

    results = []
    easy_count = 0
    feasible_count = 0
    difficult_count = 0
    very_difficult_count = 0

    for molecule in molecules:
        result = run_synthesis_workflow(
            db=db,
            project=project,
            molecule=molecule,
            run_retrosynthesis=run_retrosynthesis,
        )
        results.append(result)

        # 统计
        if result.overall_assessment == "easy":
            easy_count += 1
        elif result.overall_assessment == "feasible":
            feasible_count += 1
        elif result.overall_assessment == "difficult":
            difficult_count += 1
        elif result.overall_assessment == "very_difficult":
            very_difficult_count += 1

    return {
        "total_molecules": len(molecules),
        "easy_count": easy_count,
        "feasible_count": feasible_count,
        "difficult_count": difficult_count,
        "very_difficult_count": very_difficult_count,
        "easy_molecules": [r.molecule_id for r in results if r.overall_assessment == "easy"][:10],
        "recommendations": _generate_synthesis_recommendations(
            easy_count, feasible_count, difficult_count, very_difficult_count, len(molecules)
        ),
        "runtime_seconds": time.monotonic() - start_time,
    }


def _generate_synthesis_recommendations(
    easy: int,
    feasible: int,
    difficult: int,
    very_difficult: int,
    total: int,
) -> list[str]:
    """生成合成可及性建议"""
    recommendations = []

    easy_pct = (easy / total * 100) if total > 0 else 0
    difficult_pct = ((difficult + very_difficult) / total * 100) if total > 0 else 0

    if easy_pct > 30:
        recommendations.append(
            f"{easy_pct:.1f}%的分子易于合成，建议优先推进这些候选物"
        )

    if difficult_pct > 50:
        recommendations.append(
            f"{difficult_pct:.1f}%的分子合成困难，建议简化结构或寻找类似物"
        )

    if feasible > 0:
        recommendations.append(
            f"{feasible}个分子具有可行的合成路线，可作为备选候选物"
        )

    return recommendations
