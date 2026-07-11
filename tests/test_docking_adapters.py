from pathlib import Path

from medagent.services import docking_adapters
from medagent.services.docking_adapters import DockingToolRequest


def test_parse_vina_output_reads_best_affinity_from_table():
    stdout = """
mode |   affinity | dist from best mode
-----+------------+----------+----------
   1        -8.7      0.000      0.000
   2        -7.9      1.221      2.442
"""

    parsed = docking_adapters.parse_vina_output(stdout)

    assert parsed["vina_score"] == -8.7


def test_parse_gnina_output_reads_affinity_and_cnn_scores():
    stdout = """
Affinity: -9.1
CNNscore: 0.78
CNNaffinity: -8.3
"""

    parsed = docking_adapters.parse_gnina_output(stdout)

    assert parsed["vina_score"] == -9.1
    assert parsed["cnn_score"] == 0.78
    assert parsed["cnn_affinity"] == -8.3


def test_gnina_command_uses_receptor_ligand_grid_and_output(tmp_path):
    request = DockingToolRequest(
        receptor_file=str(tmp_path / "protein.pdb"),
        ligand_file=str(tmp_path / "ligand.sdf"),
        output_dir=str(tmp_path / "poses"),
        grid_center=[1.0, 2.0, 3.0],
        grid_size=[18.0, 19.0, 20.0],
        molecule_id="MOL-1",
    )

    command, pose_file = docking_adapters.build_gnina_command("gnina", request)

    assert command[:5] == [
        "gnina",
        "-r",
        str(tmp_path / "protein.pdb"),
        "-l",
        str(tmp_path / "ligand.sdf"),
    ]
    assert command[command.index("--center_x") + 1] == "1.0"
    assert command[command.index("--size_z") + 1] == "20.0"
    assert pose_file == str(Path(tmp_path / "poses" / "MOL-1_gnina_pose.sdf"))


def test_external_docking_prefers_gnina_and_parses_success(tmp_path, monkeypatch):
    calls: list[list[str]] = []
    receptor_file = tmp_path / "protein.pdb"
    ligand_file = tmp_path / "ligand.sdf"
    receptor_file.write_text("HEADER    TEST RECEPTOR\n", encoding="utf-8")
    ligand_file.write_text("test ligand\n$$$$\n", encoding="utf-8")

    class CompletedProcess:
        returncode = 0
        stdout = "Affinity: -7.5\nCNNscore: 0.62\nCNNaffinity: -7.1\n"
        stderr = ""

    def fake_run(command, capture_output, text, timeout, check):
        calls.append(command)
        return CompletedProcess()

    monkeypatch.setattr(docking_adapters.subprocess, "run", fake_run)

    request = DockingToolRequest(
        receptor_file=str(receptor_file),
        ligand_file=str(ligand_file),
        output_dir=str(tmp_path / "poses"),
        grid_center=[1.0, 2.0, 3.0],
        grid_size=[18.0, 18.0, 18.0],
        molecule_id="MOL-2",
    )
    tool_status = {
        "gnina": {"available": True, "path": "gnina"},
        "vina": {"available": True, "path": "vina"},
    }

    result = docking_adapters.run_external_docking(request, tool_status)

    assert result is not None
    assert result.success is True
    assert result.adapter_mode == "gnina_external_docking"
    assert result.vina_score == -7.5
    assert result.cnn_score == 0.62
    assert calls[0][0] == "gnina"


def test_external_docking_uses_vina_for_prepared_pdbqt_inputs(tmp_path, monkeypatch):
    calls: list[list[str]] = []
    receptor_file = tmp_path / "protein.pdbqt"
    ligand_file = tmp_path / "ligand.pdbqt"
    receptor_file.write_text("RECEPTOR\n", encoding="utf-8")
    ligand_file.write_text("LIGAND\n", encoding="utf-8")

    class CompletedProcess:
        returncode = 0
        stdout = """
mode |   affinity | dist from best mode
-----+------------+----------+----------
   1        -6.9      0.000      0.000
"""
        stderr = ""

    def fake_run(command, capture_output, text, timeout, check):
        calls.append(command)
        return CompletedProcess()

    monkeypatch.setattr(docking_adapters.subprocess, "run", fake_run)

    request = DockingToolRequest(
        receptor_file=str(receptor_file),
        ligand_file=str(ligand_file),
        output_dir=str(tmp_path / "poses"),
        grid_center=[1.0, 2.0, 3.0],
        grid_size=[18.0, 18.0, 18.0],
        molecule_id="MOL-3",
    )
    tool_status = {
        "gnina": {"available": False, "path": None},
        "vina": {"available": True, "path": "vina"},
    }

    result = docking_adapters.run_external_docking(request, tool_status)

    assert result is not None
    assert result.success is True
    assert result.adapter_mode == "vina_external_docking"
    assert result.vina_score == -6.9
    assert calls[0][0] == "vina"
