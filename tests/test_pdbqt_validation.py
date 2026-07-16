from medagent.services.pdbqt_validation import is_valid_vina_ligand_pdbqt


def test_vina_ligand_requires_torsion_tree(tmp_path):
    ligand = tmp_path / "ligand.pdbqt"
    ligand.write_text(
        "ATOM      1  C   LIG     1       0.000   0.000   0.000  0.00  0.00  0.000 C\n",
        encoding="utf-8",
    )

    assert is_valid_vina_ligand_pdbqt(ligand) is False


def test_vina_ligand_accepts_rigid_zero_torsion_tree(tmp_path):
    ligand = tmp_path / "ligand.pdbqt"
    ligand.write_text(
        "ROOT\n"
        "ATOM      1  C   LIG     1       0.000   0.000   0.000  0.00  0.00  0.000 C\n"
        "ENDROOT\n"
        "TORSDOF 0\n",
        encoding="utf-8",
    )

    assert is_valid_vina_ligand_pdbqt(ligand) is True
