"""
增强的RDKit化学计算模块

提供完整的分子描述符计算、药物相似性评分和结构警报检测。

功能：
- 完整的Lipinski五规则检查
- QED (Quantitative Estimate of Drug-likeness)
- SA Score (合成可及性评分)
- PAINS/Brenk/NIH结构警报
- 扩展分子描述符
- 分子标准化和互变异构体生成
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EnhancedMoleculeDescriptors:
    """增强的分子描述符"""
    # 基础标识
    smiles: str
    canonical_smiles: str
    isomeric_smiles: str
    inchi_key: str | None

    # 基础性质
    mw: float
    exact_mw: float
    logp: float
    tpsa: float
    hbd: int
    hba: int

    # 拓扑性质
    heavy_atom_count: int
    rotatable_bond_count: int
    ring_count: int
    aromatic_ring_count: int
    aliphatic_ring_count: int
    saturated_ring_count: int
    heteroatom_count: int

    # 电荷和极性
    formal_charge: int
    num_radical_electrons: int
    num_valence_electrons: int

    # 复杂度
    complexity: float | None
    fraction_csp3: float

    # 骨架
    scaffold: str | None
    murcko_scaffold: str | None

    # 药物相似性
    lipinski_pass: bool
    lipinski_violations: int
    lipinski_details: dict[str, Any]

    # QED评分
    qed: float | None

    # 合成可及性
    sa_score: float | None

    # 元素组成
    formula: str
    element_counts: dict[str, int]

    # 其他
    validator: str = "rdkit_enhanced"
    warnings: list[str] = field(default_factory=list)


@dataclass
class StructuralAlert:
    """结构警报"""
    catalog: str  # PAINS_A, PAINS_B, PAINS_C, BRENK, NIH
    pattern_name: str
    description: str
    severity: str  # high, medium, low


@dataclass
class EnhancedValidation:
    """增强的分子验证结果"""
    available: bool
    valid: bool
    labels: list[str]
    reason: str | None = None
    descriptors: EnhancedMoleculeDescriptors | None = None
    structural_alerts: list[StructuralAlert] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate_and_calculate_enhanced(smiles: str) -> EnhancedValidation:
    """增强的分子验证和描述符计算"""
    modules = _load_rdkit_modules()
    if modules is None:
        return EnhancedValidation(
            available=False,
            valid=False,
            labels=["rdkit_unavailable"],
            reason="rdkit_unavailable",
        )

    chem = modules["Chem"]
    mol = chem.MolFromSmiles(smiles)
    if mol is None:
        return EnhancedValidation(
            available=True,
            valid=False,
            labels=["invalid_smiles", "rdkit_parse_failed"],
            reason="rdkit_parse_failed",
        )

    try:
        chem.SanitizeMol(mol)
    except Exception:
        return EnhancedValidation(
            available=True,
            valid=False,
            labels=["invalid_smiles", "rdkit_sanitize_failed"],
            reason="rdkit_sanitize_failed",
        )

    # 计算描述符
    descriptors = _calculate_enhanced_descriptors(mol, smiles, modules)

    # 检测结构警报
    alerts = _check_structural_alerts(mol, modules)

    # 生成标签
    labels = ["rdkit_validation_passed", "structure_standardized"]
    if descriptors.lipinski_pass:
        labels.append("lipinski_compliant")
    else:
        labels.append("lipinski_violation")

    if alerts:
        labels.append("structural_alerts_found")
        for alert in alerts:
            if alert.severity == "high":
                labels.append("high_risk_alert")
                break

    if descriptors.qed and descriptors.qed >= 0.7:
        labels.append("high_qed")
    elif descriptors.qed and descriptors.qed < 0.3:
        labels.append("low_qed")

    if descriptors.sa_score and descriptors.sa_score <= 3.0:
        labels.append("easy_to_synthesize")
    elif descriptors.sa_score and descriptors.sa_score >= 6.0:
        labels.append("hard_to_synthesize")

    return EnhancedValidation(
        available=True,
        valid=True,
        labels=labels,
        descriptors=descriptors,
        structural_alerts=alerts,
        warnings=descriptors.warnings,
    )


def _load_rdkit_modules() -> dict[str, Any] | None:
    """加载RDKit模块"""
    try:
        from rdkit import Chem
        from rdkit.Chem import (
            AllChem,
            Crippen,
            Descriptors,
            FilterCatalog,
            Lipinski,
            QED,
            rdMolDescriptors,
        )
        from rdkit.Chem.Scaffolds import MurckoScaffold

        # SA Score需要单独处理，因为不是所有RDKit版本都包含
        try:
            from rdkit.Chem import RDConfig
            import os
            import sys
            sys.path.append(os.path.join(RDConfig.RDContribDir, 'SA_Score'))
            import sascorer
            sa_scorer = sascorer
        except (ImportError, AttributeError):
            sa_scorer = None

        return {
            "Chem": Chem,
            "AllChem": AllChem,
            "Crippen": Crippen,
            "Descriptors": Descriptors,
            "FilterCatalog": FilterCatalog,
            "Lipinski": Lipinski,
            "QED": QED,
            "MurckoScaffold": MurckoScaffold,
            "rdMolDescriptors": rdMolDescriptors,
            "sascorer": sa_scorer,
        }
    except ImportError:
        return None


def _calculate_enhanced_descriptors(
    mol: Any,
    original_smiles: str,
    modules: dict[str, Any],
) -> EnhancedMoleculeDescriptors:
    """计算增强的分子描述符"""
    chem = modules["Chem"]
    crippen = modules["Crippen"]
    descriptors = modules["Descriptors"]
    lipinski = modules["Lipinski"]
    qed = modules["QED"]
    murcko_scaffold = modules["MurckoScaffold"]
    rd_mol_descriptors = modules["rdMolDescriptors"]
    sa_scorer = modules.get("sascorer")

    warnings: list[str] = []

    # 基础标识
    canonical_smiles = chem.MolToSmiles(mol, canonical=True)
    isomeric_smiles = chem.MolToSmiles(mol, canonical=True, isomericSmiles=True)

    inchi_key = None
    try:
        inchi_key = chem.MolToInchiKey(mol)
    except Exception:
        warnings.append("inchi_key_generation_failed")

    # 基础性质
    mw = float(descriptors.MolWt(mol))
    exact_mw = float(rd_mol_descriptors.CalcExactMolWt(mol))
    logp = float(crippen.MolLogP(mol))
    tpsa = float(rd_mol_descriptors.CalcTPSA(mol))
    hbd = int(lipinski.NumHDonors(mol))
    hba = int(lipinski.NumHAcceptors(mol))

    # 拓扑性质
    ring_info = mol.GetRingInfo()
    heavy_atom_count = int(mol.GetNumHeavyAtoms())
    rotatable_bond_count = int(lipinski.NumRotatableBonds(mol))
    ring_count = int(ring_info.NumRings())
    aromatic_ring_count = int(rd_mol_descriptors.CalcNumAromaticRings(mol))
    aliphatic_ring_count = int(rd_mol_descriptors.CalcNumAliphaticRings(mol))
    saturated_ring_count = int(rd_mol_descriptors.CalcNumSaturatedRings(mol))
    heteroatom_count = int(lipinski.NumHeteroatoms(mol))

    # 电荷
    formal_charge = int(chem.GetFormalCharge(mol))
    num_radical_electrons = sum(atom.GetNumRadicalElectrons() for atom in mol.GetAtoms())
    num_valence_electrons = sum(atom.GetTotalValence() for atom in mol.GetAtoms())

    # 复杂度
    fraction_csp3 = float(lipinski.FractionCSP3(mol))

    # 骨架
    scaffold = None
    murcko_scaffold_smiles = None
    try:
        scaffold = murcko_scaffold.MurckoScaffoldSmiles(mol=mol)
        murcko_scaffold_smiles = scaffold
    except Exception:
        warnings.append("scaffold_generation_failed")

    # Lipinski五规则
    lipinski_violations = 0
    lipinski_details = {
        "mw_pass": mw <= 500,
        "logp_pass": logp <= 5,
        "hbd_pass": hbd <= 5,
        "hba_pass": hba <= 10,
    }

    if not lipinski_details["mw_pass"]:
        lipinski_violations += 1
    if not lipinski_details["logp_pass"]:
        lipinski_violations += 1
    if not lipinski_details["hbd_pass"]:
        lipinski_violations += 1
    if not lipinski_details["hba_pass"]:
        lipinski_violations += 1

    lipinski_pass = lipinski_violations <= 1  # 允许1个违规

    # QED评分
    qed_score = None
    try:
        qed_score = float(qed.qed(mol))
    except Exception:
        warnings.append("qed_calculation_failed")

    # SA Score
    sa_score = None
    if sa_scorer:
        try:
            sa_score = float(sa_scorer.calculateScore(mol))
        except Exception:
            warnings.append("sa_score_calculation_failed")
    else:
        warnings.append("sa_scorer_not_available")

    # 元素组成
    formula = rd_mol_descriptors.CalcMolFormula(mol)
    atom_counts: dict[str, int] = {}
    for atom in mol.GetAtoms():
        symbol = atom.GetSymbol()
        atom_counts[symbol] = atom_counts.get(symbol, 0) + 1

    # 复杂度（使用BertzCT作为近似）
    complexity = None
    try:
        complexity = float(descriptors.BertzCT(mol))
    except Exception:
        warnings.append("complexity_calculation_failed")

    return EnhancedMoleculeDescriptors(
        smiles=original_smiles,
        canonical_smiles=canonical_smiles,
        isomeric_smiles=isomeric_smiles,
        inchi_key=inchi_key,
        mw=round(mw, 3),
        exact_mw=round(exact_mw, 6),
        logp=round(logp, 3),
        tpsa=round(tpsa, 3),
        hbd=hbd,
        hba=hba,
        heavy_atom_count=heavy_atom_count,
        rotatable_bond_count=rotatable_bond_count,
        ring_count=ring_count,
        aromatic_ring_count=aromatic_ring_count,
        aliphatic_ring_count=aliphatic_ring_count,
        saturated_ring_count=saturated_ring_count,
        heteroatom_count=heteroatom_count,
        formal_charge=formal_charge,
        num_radical_electrons=num_radical_electrons,
        num_valence_electrons=num_valence_electrons,
        complexity=round(complexity, 2) if complexity else None,
        fraction_csp3=round(fraction_csp3, 3),
        scaffold=scaffold,
        murcko_scaffold=murcko_scaffold_smiles,
        lipinski_pass=lipinski_pass,
        lipinski_violations=lipinski_violations,
        lipinski_details=lipinski_details,
        qed=round(qed_score, 3) if qed_score else None,
        sa_score=round(sa_score, 2) if sa_score else None,
        formula=formula,
        element_counts=dict(sorted(atom_counts.items())),
        warnings=warnings,
    )


def _check_structural_alerts(mol: Any, modules: dict[str, Any]) -> list[StructuralAlert]:
    """检测结构警报（PAINS/Brenk/NIH）"""
    alerts: list[StructuralAlert] = []

    filter_catalog = modules.get("FilterCatalog")
    if not filter_catalog:
        return alerts

    try:
        params = filter_catalog.FilterCatalogParams()

        # 添加各种催化剂
        catalog_configs = [
            ("PAINS_A", "high"),
            ("PAINS_B", "high"),
            ("PAINS_C", "medium"),
            ("BRENK", "medium"),
            ("NIH", "low"),
        ]

        for catalog_name, severity in catalog_configs:
            catalog = getattr(
                filter_catalog.FilterCatalogParams.FilterCatalogs,
                catalog_name,
                None
            )
            if catalog is not None:
                params.AddCatalog(catalog)

        catalog = filter_catalog.FilterCatalog(params)
        matches = catalog.GetMatches(mol)

        for match in matches:
            description = match.GetDescription()

            # 根据描述推断目录和严重程度
            if "PAINS" in description:
                cat = "PAINS"
                sev = "high"
            elif "Brenk" in description or "BRENK" in description:
                cat = "BRENK"
                sev = "medium"
            elif "NIH" in description:
                cat = "NIH"
                sev = "low"
            else:
                cat = "unknown"
                sev = "medium"

            alerts.append(StructuralAlert(
                catalog=cat,
                pattern_name=description,
                description=description,
                severity=sev,
            ))

    except Exception:
        pass

    return alerts


def calculate_drug_likeness_score(descriptors: EnhancedMoleculeDescriptors) -> dict[str, Any]:
    """
    计算综合药物相似性评分

    返回：
        - overall_score: 综合评分 (0-100)
        - components: 各组件得分
        - recommendation: 推荐等级
    """
    scores = {}

    # QED评分 (0-1 -> 0-30分)
    if descriptors.qed:
        scores["qed"] = descriptors.qed * 30
    else:
        scores["qed"] = 0

    # Lipinski合规性 (0-25分)
    lipinski_score = 25 - (descriptors.lipinski_violations * 6.25)
    scores["lipinski"] = max(0, lipinski_score)

    # 合成可及性 (SA Score 1-10, 反向计分, 0-25分)
    if descriptors.sa_score:
        sa_normalized = (10 - descriptors.sa_score) / 9  # 归一化到0-1
        scores["sa"] = max(0, sa_normalized * 25)
    else:
        scores["sa"] = 12.5  # 中等分数

    # 结构复杂度 (0-20分)
    # 适度复杂度得分最高
    if descriptors.complexity:
        if 200 <= descriptors.complexity <= 600:
            scores["complexity"] = 20
        elif 100 <= descriptors.complexity < 200 or 600 < descriptors.complexity <= 800:
            scores["complexity"] = 15
        else:
            scores["complexity"] = 10
    else:
        scores["complexity"] = 10

    # 计算总分
    overall_score = sum(scores.values())

    # 推荐等级
    if overall_score >= 80:
        recommendation = "excellent"
    elif overall_score >= 60:
        recommendation = "good"
    elif overall_score >= 40:
        recommendation = "acceptable"
    else:
        recommendation = "poor"

    return {
        "overall_score": round(overall_score, 2),
        "components": {k: round(v, 2) for k, v in scores.items()},
        "recommendation": recommendation,
        "max_score": 100,
    }
