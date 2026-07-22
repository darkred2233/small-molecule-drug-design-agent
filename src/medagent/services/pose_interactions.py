"""Geometric interaction analysis for docking poses.

The calculation intentionally reports distance-derived contacts, not a force-field
or MD-derived interaction energy.  This distinction is retained in the returned
metadata so reports do not overstate the evidence from a docking pose.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


_HETEROATOMS = {"N", "O", "S"}
_VDW_RADII = {
    "B": 1.92,
    "C": 1.70,
    "N": 1.55,
    "O": 1.52,
    "F": 1.47,
    "P": 1.80,
    "S": 1.80,
    "CL": 1.75,
    "BR": 1.85,
    "I": 1.98,
}
_MAX_REPORTED_CONTACTS = 50


def analyze_pose_interactions(
    *,
    pose_file: str | Path | None,
    receptor_file: str | Path | None,
    key_residues: list[str] | None = None,
) -> dict[str, Any]:
    """Return reproducible distance-based contacts for a docking pose.

    GNINA writes SDF poses and Vina writes PDBQT poses.  Both formats are
    supported.  A hydrogen-bond contact is a donor/acceptor heavy-atom pair at
    most 3.5 A; no angle criterion is claimed because docking output normally
    does not retain reliable hydrogen positions.  A clash is a heavy-atom pair
    closer than the sum of van der Waals radii minus 0.75 A.
    """
    pose_path = _path_or_none(pose_file)
    receptor_path = _path_or_none(receptor_file)
    if pose_path is None:
        return _unavailable("pose_file_not_found")
    if receptor_path is None:
        return _unavailable("receptor_file_not_found")

    try:
        ligand_atoms = _load_ligand_atoms(pose_path)
        receptor_atoms = _load_pdb_atoms(receptor_path)
    except ValueError as exc:
        return _unavailable(str(exc))
    except Exception as exc:  # Keep a reportable docking result if parsing fails.
        return _unavailable(f"pose_interaction_parser_error:{type(exc).__name__}")

    if not ligand_atoms:
        return _unavailable("pose_has_no_heavy_atoms")
    if not receptor_atoms:
        return _unavailable("receptor_has_no_heavy_atoms")

    normalized_keys = {_normalize_residue(value) for value in key_residues or []}
    hbond_contacts: list[dict[str, Any]] = []
    clash_contacts: list[dict[str, Any]] = []
    key_contacts: list[dict[str, Any]] = []
    seen_key_contacts: set[tuple[str, int, int]] = set()

    for ligand in ligand_atoms:
        for receptor in receptor_atoms:
            distance = _distance(ligand["coord"], receptor["coord"])
            residue = receptor["residue"]
            is_key_residue = not normalized_keys or _normalize_residue(residue) in normalized_keys

            if _is_hbond_pair(ligand, receptor, distance):
                contact = {
                    "interaction_type": "hydrogen_bond_geometry_contact",
                    "residue": residue,
                    "chain": receptor["chain"],
                    "distance_angstrom": round(distance, 3),
                    "ligand_atom_index": ligand["index"],
                    "ligand_element": ligand["element"],
                    "receptor_atom": receptor["atom_name"],
                    "receptor_element": receptor["element"],
                    "key_residue": is_key_residue,
                }
                hbond_contacts.append(contact)
                if is_key_residue:
                    identity = (residue, ligand["index"], receptor["index"])
                    if identity not in seen_key_contacts:
                        key_contacts.append(contact)
                        seen_key_contacts.add(identity)

            if _is_clash_pair(ligand, receptor, distance):
                clash_contacts.append(
                    {
                        "interaction_type": "steric_clash_geometry_contact",
                        "residue": residue,
                        "chain": receptor["chain"],
                        "distance_angstrom": round(distance, 3),
                        "ligand_atom_index": ligand["index"],
                        "ligand_element": ligand["element"],
                        "receptor_atom": receptor["atom_name"],
                        "receptor_element": receptor["element"],
                        "key_residue": is_key_residue,
                    }
                )

    labels = ["pose_interactions_computed", "pose_interaction_geometry_estimated"]
    labels.append("key_interaction_present" if key_contacts else "key_interaction_missing")
    if clash_contacts:
        labels.append("steric_clash")
    if len(clash_contacts) >= 2:
        labels.append("bad_pose")

    return {
        "computed": True,
        "method": "rdkit_distance_geometry_v1",
        "hbond_count": len(hbond_contacts),
        "key_hbond_count": len(key_contacts),
        "clash_count": len(clash_contacts),
        "key_residue_interactions": key_contacts[:_MAX_REPORTED_CONTACTS],
        "hbond_contacts": hbond_contacts[:_MAX_REPORTED_CONTACTS],
        "clash_contacts": clash_contacts[:_MAX_REPORTED_CONTACTS],
        "labels": labels,
        "warnings": [],
    }


def _path_or_none(value: str | Path | None) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    return path if path.is_file() else None


def _load_ligand_atoms(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() in {".pdb", ".pdbqt"}:
        return _load_pdb_atoms(path, include_residue=False)
    try:
        from rdkit import Chem
    except ImportError as exc:
        raise ValueError("rdkit_required_for_sdf_pose_interactions") from exc

    molecule = Chem.MolFromMolFile(str(path), removeHs=False, sanitize=False)
    if molecule is None or molecule.GetNumConformers() == 0:
        raise ValueError("sdf_pose_parse_failed")
    conformer = molecule.GetConformer()
    atoms: list[dict[str, Any]] = []
    for atom in molecule.GetAtoms():
        element = atom.GetSymbol().upper()
        if element == "H":
            continue
        position = conformer.GetAtomPosition(atom.GetIdx())
        atoms.append(
            {
                "index": atom.GetIdx() + 1,
                "element": element,
                "coord": (float(position.x), float(position.y), float(position.z)),
                "atom_name": element,
                "residue": "LIG",
                "chain": "",
            }
        )
    return atoms


def _load_pdb_atoms(path: Path, *, include_residue: bool = True) -> list[dict[str, Any]]:
    atoms: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        try:
            coord = (float(line[30:38]), float(line[38:46]), float(line[46:54]))
        except ValueError:
            continue
        atom_name = line[12:16].strip() or "UNK"
        element = _atom_element(line, atom_name)
        if element == "H":
            continue
        residue_name = line[17:20].strip().upper() or "UNK"
        residue_number = line[22:26].strip()
        residue = f"{residue_name}{residue_number}" if include_residue else "LIG"
        atoms.append(
            {
                "index": line_number,
                "element": element,
                "coord": coord,
                "atom_name": atom_name,
                "residue": residue,
                "chain": line[21].strip(),
            }
        )
    return atoms


def _atom_element(line: str, atom_name: str) -> str:
    explicit = line[76:78].strip().upper()
    if explicit:
        return explicit
    letters = "".join(character for character in atom_name if character.isalpha()).upper()
    if letters.startswith("CL"):
        return "CL"
    if letters.startswith("BR"):
        return "BR"
    return letters[:1] or "C"


def _is_hbond_pair(ligand: dict[str, Any], receptor: dict[str, Any], distance: float) -> bool:
    return (
        distance <= 3.5
        and ligand["element"] in _HETEROATOMS
        and receptor["element"] in _HETEROATOMS
    )


def _is_clash_pair(ligand: dict[str, Any], receptor: dict[str, Any], distance: float) -> bool:
    ligand_radius = _VDW_RADII.get(ligand["element"], 1.70)
    receptor_radius = _VDW_RADII.get(receptor["element"], 1.70)
    return distance < max(1.2, ligand_radius + receptor_radius - 0.75)


def _distance(left: tuple[float, float, float], right: tuple[float, float, float]) -> float:
    return sum((a - b) ** 2 for a, b in zip(left, right)) ** 0.5


def _normalize_residue(value: str) -> str:
    return "".join(character for character in value.upper() if character.isalnum())


def _unavailable(warning: str) -> dict[str, Any]:
    return {
        "computed": False,
        "method": "rdkit_distance_geometry_v1",
        "hbond_count": None,
        "key_hbond_count": None,
        "clash_count": None,
        "key_residue_interactions": [],
        "hbond_contacts": [],
        "clash_contacts": [],
        "labels": ["pose_interactions_unavailable"],
        "warnings": [warning],
    }
