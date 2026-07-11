"""
完整的ADMET预测工作流

提供端到端的ADMET预测流程：
1. 批量分子ADMET预测
2. 结果解析和风险评估
3. 数据库存储
4. 基于RDKit的代理预测（当Chemprop不可用时）

支持的ADMET性质：
- hERG心脏毒性
- Ames致突变性
- CYP3A4/CYP2D6抑制
- 溶解度
- 渗透性
- DILI肝毒性
- Pgp底物
- BBB穿透
"""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from medagent.db.models import ADMETResult, Molecule, Project
from medagent.services.admet_adapter import (
    ChempropADMETRequest,
    SingleADMETResult,
    check_chemprop_available,
    run_chemprop_admet,
)
from medagent.services.ids import new_id


@dataclass
class ADMETWorkflowResult:
    """ADMET工作流完整结果"""
    success: bool
    evaluated_count: int
    stored_count: int
    adapter_mode: str
    tool_name: str
    admet_result_ids: list[str] = field(default_factory=list)
    high_risk_molecules: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    runtime_seconds: float = 0.0


def predict_molecule_admet_rdkit_surrogate(smiles: str, molecule_id: str) -> SingleADMETResult:
    """
    使用RDKit代理预测ADMET性质

    当Chemprop不可用时的回退方案，基于简单的分子描述符规则。
    注意：这是粗略估计，不应用于实际决策。
    """
    try:
        from rdkit import Chem
        from rdkit.Chem import Crippen, Descriptors, rdMolDescriptors
    except ImportError:
        return SingleADMETResult(
            molecule_id=molecule_id,
            smiles=smiles,
            labels=["rdkit_surrogate_failed"],
            warnings=["rdkit_not_available"],
        )

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return SingleADMETResult(
            molecule_id=molecule_id,
            smiles=smiles,
            labels=["rdkit_surrogate_failed", "invalid_smiles"],
            warnings=["smiles_parsing_failed"],
        )

    # 计算描述符
    mw = Descriptors.MolWt(mol)
    logp = Crippen.MolLogP(mol)
    tpsa = rdMolDescriptors.CalcTPSA(mol)
    aromatic_rings = rdMolDescriptors.CalcNumAromaticRings(mol)

    # 简单的基于规则的风险评估
    warnings = ["rdkit_surrogate_used", "predictions_are_approximate"]

    # hERG风险：高LogP + 芳香环 + 碱性
    herg_risk_score = 0.0
    if logp > 3:
        herg_risk_score += 0.3
    if aromatic_rings >= 2:
        herg_risk_score += 0.3
    # 检测碱性氮
    basic_n_count = sum(1 for atom in mol.GetAtoms()
                        if atom.GetAtomicNum() == 7 and atom.GetTotalDegree() <= 3)
    if basic_n_count > 0:
        herg_risk_score += 0.2

    herg_prob = min(herg_risk_score, 0.9)
    herg_risk = "low_risk" if herg_prob < 0.3 else ("medium_risk" if herg_prob < 0.6 else "high_risk")

    # Ames风险：芳香胺、硝基、卤素芳香等
    ames_risk_score = 0.0
    aromatic_amine_pattern = Chem.MolFromSmarts("c[NH2,NH1]")
    nitro_pattern = Chem.MolFromSmarts("[N+](=O)[O-]")

    if mol.HasSubstructMatch(aromatic_amine_pattern):
        ames_risk_score += 0.4
    if mol.HasSubstructMatch(nitro_pattern):
        ames_risk_score += 0.3

    ames_prob = min(ames_risk_score, 0.8)
    ames_risk = "low_risk" if ames_prob < 0.3 else ("medium_risk" if ames_prob < 0.6 else "high_risk")

    # CYP抑制：通常与高LogP和芳香性相关
    cyp_risk_score = 0.0
    if logp > 3:
        cyp_risk_score += 0.3
    if aromatic_rings >= 3:
        cyp_risk_score += 0.2

    cyp3a4_prob = min(cyp_risk_score, 0.7)
    cyp3a4_risk = "low_risk" if cyp3a4_prob < 0.3 else ("medium_risk" if cyp3a4_prob < 0.6 else "high_risk")

    cyp2d6_prob = min(cyp_risk_score * 0.8, 0.7)
    cyp2d6_risk = "low_risk" if cyp2d6_prob < 0.3 else ("medium_risk" if cyp2d6_prob < 0.6 else "high_risk")

    # 溶解度：基于LogP和TPSA
    if logp < 2 and tpsa > 40:
        solubility = "high"
        solubility_score = 0.7
    elif logp < 4 and tpsa > 20:
        solubility = "medium"
        solubility_score = 0.5
    else:
        solubility = "low"
        solubility_score = 0.3

    # 渗透性：基于LogP和TPSA (Lipinski空间)
    if 0 < logp < 5 and 20 < tpsa < 140:
        permeability = "high"
        permeability_score = 0.7
    elif -1 < logp < 6 and 10 < tpsa < 160:
        permeability = "medium"
        permeability_score = 0.5
    else:
        permeability = "low"
        permeability_score = 0.3

    # DILI风险：复杂，简化处理
    dili_prob = min((herg_risk_score + ames_risk_score) / 2, 0.7)
    dili_risk = "low_risk" if dili_prob < 0.3 else ("medium_risk" if dili_prob < 0.6 else "high_risk")

    # Pgp底物：高MW + 高LogP
    pgp_prob = 0.5 if mw > 400 and logp > 3 else 0.2
    pgp_risk = "low_risk" if pgp_prob < 0.3 else ("medium_risk" if pgp_prob < 0.6 else "high_risk")

    # BBB穿透：LogP 1-3, MW<450, TPSA<90
    if 1 < logp < 3 and mw < 450 and tpsa < 90:
        bbb_prob = 0.7
    elif 0 < logp < 5 and mw < 500 and tpsa < 120:
        bbb_prob = 0.4
    else:
        bbb_prob = 0.1
    bbb_risk = "low_risk" if bbb_prob < 0.3 else ("medium_risk" if bbb_prob < 0.6 else "high_risk")

    # 计算总体ADMET风险分数
    risk_probs = [herg_prob, ames_prob, dili_prob]
    admet_risk_score = sum(risk_probs) / len(risk_probs) if risk_probs else 0.0

    # 生成标签
    labels = ["rdkit_surrogate_admet"]
    if herg_risk == "high_risk" or ames_risk == "high_risk":
        labels.append("admet_blocker")
    elif herg_risk == "medium_risk" or ames_risk == "medium_risk":
        labels.append("admet_warning")
    else:
        labels.append("admet_clean")

    return SingleADMETResult(
        molecule_id=molecule_id,
        smiles=smiles,
        hERG_probability=round(herg_prob, 3),
        hERG_risk=herg_risk,
        Ames_probability=round(ames_prob, 3),
        Ames_risk=ames_risk,
        CYP3A4_inhibition=round(cyp3a4_prob, 3),
        CYP3A4_risk=cyp3a4_risk,
        CYP2D6_inhibition=round(cyp2d6_prob, 3),
        CYP2D6_risk=cyp2d6_risk,
        solubility=solubility,
        solubility_score=round(solubility_score, 3),
        permeability=permeability,
        permeability_score=round(permeability_score, 3),
        DILI_probability=round(dili_prob, 3),
        DILI_risk=dili_risk,
        Pgp_substrate=round(pgp_prob, 3),
        Pgp_risk=pgp_risk,
        BBB_penetration=round(bbb_prob, 3),
        BBB_risk=bbb_risk,
        admet_risk_score=round(admet_risk_score, 3),
        labels=labels,
        warnings=warnings,
    )


def run_admet_workflow(
    db: Session,
    project: Project,
    molecules: list[Molecule],
    use_chemprop: bool = True,
    batch_size: int = 100,
) -> ADMETWorkflowResult:
    """
    运行完整ADMET预测工作流

    参数：
        db: 数据库会话
        project: 项目对象
        molecules: 待预测的分子列表
        use_chemprop: 是否尝试使用Chemprop（如果不可用会自动降级）
        batch_size: 批处理大小

    返回：
        ADMETWorkflowResult
    """
    import time
    start_time = time.monotonic()

    if not molecules:
        return ADMETWorkflowResult(
            success=True,
            evaluated_count=0,
            stored_count=0,
            adapter_mode="no_molecules",
            tool_name="none",
            warnings=["no_molecules_to_predict"],
        )

    # 检查Chemprop可用性
    chemprop_status = check_chemprop_available() if use_chemprop else {"available": False}
    use_chemprop = chemprop_status.get("available", False)

    adapter_mode = "unknown"
    tool_name = "unknown"
    warnings: list[str] = []
    admet_result_ids: list[str] = []
    high_risk_molecules: list[str] = []

    # 分批处理
    for i in range(0, len(molecules), batch_size):
        batch = molecules[i:i + batch_size]
        smiles_list = [mol.smiles for mol in batch]
        molecule_ids = [mol.molecule_id for mol in batch]

        if use_chemprop:
            # 使用Chemprop预测
            request = ChempropADMETRequest(
                smiles_list=smiles_list,
                molecule_ids=molecule_ids,
                properties=["hERG", "Ames", "CYP3A4", "CYP2D6",
                           "solubility", "permeability", "DILI", "Pgp", "BBB"],
            )

            result = run_chemprop_admet(request, chemprop_status)
            adapter_mode = result.adapter_mode
            tool_name = result.tool_name
            warnings.extend(result.warnings)

            if result.success and result.results:
                admet_results = result.results
            else:
                # Chemprop失败，降级到RDKit代理
                warnings.append("chemprop_failed_fallback_to_rdkit")
                admet_results = [
                    predict_molecule_admet_rdkit_surrogate(smiles, mol_id)
                    for smiles, mol_id in zip(smiles_list, molecule_ids)
                ]
                adapter_mode = "rdkit_surrogate"
                tool_name = "rdkit"
        else:
            # 直接使用RDKit代理
            admet_results = [
                predict_molecule_admet_rdkit_surrogate(smiles, mol_id)
                for smiles, mol_id in zip(smiles_list, molecule_ids)
            ]
            adapter_mode = "rdkit_surrogate"
            tool_name = "rdkit"
            warnings.append("chemprop_not_available_using_rdkit_surrogate")

        # 保存结果到数据库
        for admet_result in admet_results:
            db_result = ADMETResult(
                admet_result_id=new_id("ADMET"),
                project_id=project.project_id,
                molecule_id=admet_result.molecule_id,
                tool_name=tool_name,
                hERG_probability=admet_result.hERG_probability,
                hERG_risk=admet_result.hERG_risk,
                Ames_probability=admet_result.Ames_probability,
                Ames_risk=admet_result.Ames_risk,
                CYP3A4_inhibition=admet_result.CYP3A4_inhibition,
                CYP3A4_risk=admet_result.CYP3A4_risk,
                CYP2D6_inhibition=admet_result.CYP2D6_inhibition,
                CYP2D6_risk=admet_result.CYP2D6_risk,
                solubility=admet_result.solubility,
                solubility_score=admet_result.solubility_score,
                permeability=admet_result.permeability,
                permeability_score=admet_result.permeability_score,
                DILI_probability=admet_result.DILI_probability,
                DILI_risk=admet_result.DILI_risk,
                Pgp_substrate=admet_result.Pgp_substrate,
                Pgp_risk=admet_result.Pgp_risk,
                BBB_penetration=admet_result.BBB_penetration,
                BBB_risk=admet_result.BBB_risk,
                admet_risk_score=admet_result.admet_risk_score,
                labels=admet_result.labels,
                warnings=admet_result.warnings,
            )

            db.add(db_result)
            admet_result_ids.append(db_result.admet_result_id)

            # 识别高风险分子
            if "admet_blocker" in admet_result.labels or \
               admet_result.hERG_risk == "high_risk" or \
               admet_result.Ames_risk == "high_risk":
                high_risk_molecules.append(admet_result.molecule_id)

    db.commit()

    labels = ["admet_workflow_success"]
    if use_chemprop:
        labels.append("chemprop_used")
    else:
        labels.append("rdkit_surrogate_used")

    return ADMETWorkflowResult(
        success=True,
        evaluated_count=len(molecules),
        stored_count=len(admet_result_ids),
        adapter_mode=adapter_mode,
        tool_name=tool_name,
        admet_result_ids=admet_result_ids,
        high_risk_molecules=high_risk_molecules,
        labels=labels,
        warnings=list(set(warnings)),  # 去重
        runtime_seconds=time.monotonic() - start_time,
    )


def analyze_admet_risks(
    db: Session,
    project_id: str,
    risk_threshold: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    分析项目中所有分子的ADMET风险

    参数：
        db: 数据库会话
        project_id: 项目ID
        risk_threshold: 风险阈值设置

    返回：
        风险分析报告
    """
    if risk_threshold is None:
        risk_threshold = {
            "hERG": "medium_risk",
            "Ames": "medium_risk",
            "DILI": "high_risk",
        }

    # 查询所有ADMET结果
    admet_results = db.query(ADMETResult).filter_by(project_id=project_id).all()

    if not admet_results:
        return {
            "total_molecules": 0,
            "risk_summary": {},
            "recommendations": ["No ADMET predictions found for this project"],
        }

    # 统计风险
    risk_counts = {
        "hERG": {"low": 0, "medium": 0, "high": 0, "unknown": 0},
        "Ames": {"low": 0, "medium": 0, "high": 0, "unknown": 0},
        "CYP3A4": {"low": 0, "medium": 0, "high": 0, "unknown": 0},
        "CYP2D6": {"low": 0, "medium": 0, "high": 0, "unknown": 0},
        "DILI": {"low": 0, "medium": 0, "high": 0, "unknown": 0},
    }

    high_risk_molecules = []
    clean_molecules = []

    for result in admet_results:
        # 统计每种风险
        if result.hERG_risk:
            risk_level = result.hERG_risk.replace("_risk", "")
            risk_counts["hERG"][risk_level] = risk_counts["hERG"].get(risk_level, 0) + 1

        if result.Ames_risk:
            risk_level = result.Ames_risk.replace("_risk", "")
            risk_counts["Ames"][risk_level] = risk_counts["Ames"].get(risk_level, 0) + 1

        if result.CYP3A4_risk:
            risk_level = result.CYP3A4_risk.replace("_risk", "")
            risk_counts["CYP3A4"][risk_level] = risk_counts["CYP3A4"].get(risk_level, 0) + 1

        if result.CYP2D6_risk:
            risk_level = result.CYP2D6_risk.replace("_risk", "")
            risk_counts["CYP2D6"][risk_level] = risk_counts["CYP2D6"].get(risk_level, 0) + 1

        if result.DILI_risk:
            risk_level = result.DILI_risk.replace("_risk", "")
            risk_counts["DILI"][risk_level] = risk_counts["DILI"].get(risk_level, 0) + 1

        # 识别高风险和低风险分子
        if result.hERG_risk == "high_risk" or result.Ames_risk == "high_risk":
            high_risk_molecules.append(result.molecule_id)
        elif (result.hERG_risk == "low_risk" and
              result.Ames_risk == "low_risk" and
              result.DILI_risk in ["low_risk", "medium_risk", None]):
            clean_molecules.append(result.molecule_id)

    # 生成推荐
    recommendations = []

    herg_high_pct = risk_counts["hERG"]["high"] / len(admet_results) * 100
    if herg_high_pct > 30:
        recommendations.append(
            f"高比例分子({herg_high_pct:.1f}%)有hERG风险，建议优化减少碱性中心和疏水性"
        )

    ames_high_pct = risk_counts["Ames"]["high"] / len(admet_results) * 100
    if ames_high_pct > 20:
        recommendations.append(
            f"高比例分子({ames_high_pct:.1f}%)有Ames致突变风险，建议避免芳香胺、硝基等警报结构"
        )

    if len(clean_molecules) > 0:
        recommendations.append(
            f"发现{len(clean_molecules)}个ADMET风险较低的分子，建议优先推进"
        )

    return {
        "total_molecules": len(admet_results),
        "risk_summary": risk_counts,
        "high_risk_count": len(high_risk_molecules),
        "clean_count": len(clean_molecules),
        "high_risk_molecules": high_risk_molecules[:10],  # 只返回前10个
        "clean_molecules": clean_molecules[:10],
        "recommendations": recommendations,
    }
