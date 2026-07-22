from medagent.services.pose_interactions import analyze_pose_interactions


def test_pose_interactions_records_hydrogen_bonds_clashes_and_key_residue_contacts(tmp_path):
    receptor = tmp_path / "receptor.pdb"
    receptor.write_text(
        "ATOM      1  N   MET A 793       0.000   0.000   0.000  1.00 20.00           N\n"
        "ATOM      2  C   MET A 793       0.400   0.000   0.000  1.00 20.00           C\n"
        "END\n",
        encoding="utf-8",
    )
    pose = tmp_path / "pose.sdf"
    pose.write_text(
        "pose\n"
        "  medagent\n"
        "\n"
        "  2  1  0  0  0  0            999 V2000\n"
        "    0.0000    0.0000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0\n"
        "    2.9000    0.0000    0.0000 O   0  0  0  0  0  0  0  0  0  0  0  0\n"
        "  1  2  1  0  0  0  0\n"
        "M  END\n"
        "$$$$\n",
        encoding="utf-8",
    )

    result = analyze_pose_interactions(
        pose_file=pose,
        receptor_file=receptor,
        key_residues=["Met793"],
    )

    assert result["computed"] is True
    assert result["hbond_count"] >= 1
    assert result["key_hbond_count"] >= 1
    assert result["clash_count"] >= 1
    assert result["key_residue_interactions"][0]["residue"] == "MET793"
    assert result["method"] == "rdkit_distance_geometry_v1"
