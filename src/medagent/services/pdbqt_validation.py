from pathlib import Path


_RIGID_RECEPTOR_FORBIDDEN_TAGS = {
    "ROOT",
    "ENDROOT",
    "BRANCH",
    "ENDBRANCH",
    "TORSDOF",
}

_LIGAND_REQUIRED_TAGS = {
    "ROOT",
    "ENDROOT",
    "TORSDOF",
}


def is_valid_vina_receptor_pdbqt(path: Path) -> bool:
    """Return whether a PDBQT file is a rigid receptor accepted by Vina."""
    if path.suffix.lower() != ".pdbqt" or not path.is_file():
        return False

    has_atom = False
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                stripped = line.lstrip()
                if not stripped:
                    continue
                tag = stripped.split(maxsplit=1)[0].upper()
                if tag in _RIGID_RECEPTOR_FORBIDDEN_TAGS:
                    return False
                if tag in {"ATOM", "HETATM"}:
                    has_atom = True
    except OSError:
        return False
    return has_atom


def is_valid_vina_ligand_pdbqt(path: Path) -> bool:
    """Return whether a PDBQT file contains a Vina ligand torsion tree."""
    if path.suffix.lower() != ".pdbqt" or not path.is_file():
        return False

    has_atom = False
    seen_tags: set[str] = set()
    branch_count = 0
    end_branch_count = 0
    torsdof_value: int | None = None

    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                stripped = line.lstrip()
                if not stripped:
                    continue
                parts = stripped.split()
                tag = parts[0].upper()
                if tag in _LIGAND_REQUIRED_TAGS:
                    if tag in seen_tags:
                        return False
                    seen_tags.add(tag)
                if tag in {"ATOM", "HETATM"}:
                    has_atom = True
                elif tag == "BRANCH":
                    branch_count += 1
                elif tag == "ENDBRANCH":
                    end_branch_count += 1
                elif tag == "TORSDOF":
                    if len(parts) != 2:
                        return False
                    try:
                        torsdof_value = int(parts[1])
                    except ValueError:
                        return False
    except OSError:
        return False

    return (
        has_atom
        and seen_tags == _LIGAND_REQUIRED_TAGS
        and branch_count == end_branch_count
        and torsdof_value is not None
        and torsdof_value >= 0
    )
