from dataclasses import dataclass
from typing import Any


@dataclass
class RdkitValidation:
    available: bool
    valid: bool
    labels: list[str]
    reason: str | None = None
    descriptors: dict[str, Any] | None = None


@dataclass
class RdkitCatalogMatch:
    catalog: str
    description: str


def validate_smiles_with_rdkit(smiles: str) -> RdkitValidation:
    modules = _load_rdkit_modules()
    if modules is None:
        return RdkitValidation(
            available=False,
            valid=False,
            labels=["rdkit_unavailable"],
            reason="rdkit_unavailable",
        )

    chem = modules["Chem"]
    mol = chem.MolFromSmiles(smiles)
    if mol is None:
        return RdkitValidation(
            available=True,
            valid=False,
            labels=["invalid_smiles", "rdkit_parse_failed"],
            reason="rdkit_parse_failed",
        )

    try:
        chem.SanitizeMol(mol)
    except Exception:
        return RdkitValidation(
            available=True,
            valid=False,
            labels=["invalid_smiles", "rdkit_sanitize_failed"],
            reason="rdkit_sanitize_failed",
        )

    return RdkitValidation(
        available=True,
        valid=True,
        labels=["rdkit_validation_passed", "structure_standardized"],
        descriptors=_calculate_descriptors(mol, modules),
    )


def find_rdkit_filter_matches(smiles: str) -> tuple[bool, list[RdkitCatalogMatch]]:
    modules = _load_rdkit_modules()
    if modules is None:
        return False, []

    chem = modules["Chem"]
    filter_catalog = modules["FilterCatalog"]
    mol = chem.MolFromSmiles(smiles)
    if mol is None:
        return True, []

    matches: list[RdkitCatalogMatch] = []
    seen: set[tuple[str, str]] = set()
    for catalog_name in ("PAINS_A", "PAINS_B", "PAINS_C", "BRENK"):
        catalog = getattr(filter_catalog.FilterCatalogParams.FilterCatalogs, catalog_name, None)
        if catalog is None:
            continue
        params = filter_catalog.FilterCatalogParams()
        params.AddCatalog(catalog)
        catalog_filter = filter_catalog.FilterCatalog(params)
        for match in catalog_filter.GetMatches(mol):
            description = match.GetDescription()
            key = (catalog_name, description)
            if key in seen:
                continue
            seen.add(key)
            matches.append(RdkitCatalogMatch(catalog=catalog_name, description=description))
    return True, matches


def _load_rdkit_modules() -> dict[str, Any] | None:
    try:
        from rdkit import Chem
        from rdkit.Chem import Crippen, Descriptors, FilterCatalog, Lipinski, QED, rdMolDescriptors
        from rdkit.Chem.Scaffolds import MurckoScaffold
    except ImportError:
        return None

    return {
        "Chem": Chem,
        "Crippen": Crippen,
        "Descriptors": Descriptors,
        "FilterCatalog": FilterCatalog,
        "Lipinski": Lipinski,
        "MurckoScaffold": MurckoScaffold,
        "QED": QED,
        "rdMolDescriptors": rdMolDescriptors,
    }


def _calculate_descriptors(mol: Any, modules: dict[str, Any]) -> dict[str, Any]:
    chem = modules["Chem"]
    crippen = modules["Crippen"]
    descriptors = modules["Descriptors"]
    lipinski = modules["Lipinski"]
    murcko_scaffold = modules["MurckoScaffold"]
    qed = modules["QED"]
    rd_mol_descriptors = modules["rdMolDescriptors"]

    canonical_smiles = chem.MolToSmiles(mol, canonical=True)
    isomeric_smiles = chem.MolToSmiles(mol, canonical=True, isomericSmiles=True)
    scaffold = murcko_scaffold.MurckoScaffoldSmiles(mol=mol) or None
    ring_info = mol.GetRingInfo()

    inchi_key = None
    try:
        inchi_key = chem.MolToInchiKey(mol)
    except Exception:
        inchi_key = None

    atom_counts: dict[str, int] = {}
    for atom in mol.GetAtoms():
        symbol = atom.GetSymbol()
        atom_counts[symbol] = atom_counts.get(symbol, 0) + 1

    return {
        "validator": "rdkit",
        "mw": round(float(descriptors.MolWt(mol)), 3),
        "exact_mw": round(float(rd_mol_descriptors.CalcExactMolWt(mol)), 6),
        "logp": round(float(crippen.MolLogP(mol)), 3),
        "tpsa": round(float(rd_mol_descriptors.CalcTPSA(mol)), 3),
        "hbd": int(lipinski.NumHDonors(mol)),
        "hba": int(lipinski.NumHAcceptors(mol)),
        "heavy_atom_count": int(mol.GetNumHeavyAtoms()),
        "rotatable_bond_count": int(lipinski.NumRotatableBonds(mol)),
        "qed": round(float(qed.qed(mol)), 3),
        "ring_count": int(ring_info.NumRings()),
        "aromatic_ring_count": int(rd_mol_descriptors.CalcNumAromaticRings(mol)),
        "formula": rd_mol_descriptors.CalcMolFormula(mol),
        "canonical_smiles": canonical_smiles,
        "isomeric_smiles": isomeric_smiles,
        "inchi_key": inchi_key,
        "scaffold": scaffold,
        "element_counts": dict(sorted(atom_counts.items())),
    }
