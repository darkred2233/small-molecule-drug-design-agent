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


def test_parse_gnina_output_does_not_read_cnn_affinity_as_affinity():
    stdout = """
GNINA 1.3.2 build 2023
mode |   affinity | CNNscore | CNNaffinity
-----+------------+----------+------------
   1        -8.6      0.74       -7.9
CNNaffinity: -7.7
"""

    parsed = docking_adapters.parse_gnina_output(stdout)

    assert parsed["vina_score"] == -8.6
    assert parsed["cnn_score"] == 0.74
    assert parsed["cnn_affinity"] == -7.7


def test_parse_gnina_output_ignores_implausible_affinity_values():
    stdout = """
Affinity: -2023
CNNscore: 0.71
CNNaffinity: -7.8
mode |   affinity | CNNscore | CNNaffinity
-----+------------+----------+------------
   1        -8.2      0.71       -7.8
"""

    parsed = docking_adapters.parse_gnina_output(stdout)

    assert parsed["vina_score"] == -8.2
    assert parsed["cnn_score"] == 0.71
    assert parsed["cnn_affinity"] == -7.8


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


def test_external_docking_runs_gnina_from_docker_image(tmp_path, monkeypatch):
    calls: list[list[str]] = []
    receptor_file = tmp_path / "protein.pdb"
    ligand_file = tmp_path / "ligand.sdf"
    receptor_file.write_text("HEADER    TEST RECEPTOR\n", encoding="utf-8")
    ligand_file.write_text("test ligand\n$$$$\n", encoding="utf-8")

    class CompletedProcess:
        returncode = 0
        stdout = "Affinity: -8.2\nCNNscore: 0.73\nCNNaffinity: -7.6\n"
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
        molecule_id="MOL-DOCKER",
    )
    tool_status = {
        "gnina": {
            "available": True,
            "mode": "docker",
            "path": None,
            "docker_image": "gnina/gnina:latest",
        },
        "vina": {"available": False, "path": None},
        "diffdock": {"available": False},
    }

    result = docking_adapters.run_external_docking(request, tool_status)

    assert result is not None
    assert result.success is True
    assert result.adapter_mode == "gnina_docker_docking"
    assert result.vina_score == -8.2
    command = calls[0]
    assert command[:3] == ["docker", "run", "--rm"]
    assert "gnina/gnina:latest" in command
    assert command[command.index("gnina/gnina:latest") + 1] == "gnina"
    assert "/data/receptor/protein.pdb" in command
    assert "/data/ligand/ligand.sdf" in command


def test_gnina_status_detects_docker_image_when_binary_is_missing(monkeypatch):
    def fake_which(command):
        assert command == "gnina"
        return None

    def fake_run(command, capture_output, text, timeout):
        assert command[:3] == ["docker", "image", "inspect"]

        class CompletedProcess:
            returncode = 0

        return CompletedProcess()

    monkeypatch.setattr(docking_adapters.shutil, "which", fake_which)
    monkeypatch.setattr(docking_adapters.subprocess, "run", fake_run)

    status = docking_adapters.check_gnina_available()

    assert status["available"] is True
    assert status["mode"] == "docker"
    assert status["docker_image"] == "gnina/gnina:latest"


def test_vina_docker_command_uses_python_vina_package_with_pdbqt_inputs(tmp_path):
    receptor_file = tmp_path / "protein.pdbqt"
    ligand_file = tmp_path / "ligand.pdbqt"
    receptor_file.write_text("RECEPTOR\n", encoding="utf-8")
    ligand_file.write_text("LIGAND\n", encoding="utf-8")
    request = DockingToolRequest(
        receptor_file=str(receptor_file),
        ligand_file=str(ligand_file),
        output_dir=str(tmp_path / "poses"),
        grid_center=[1.0, 2.0, 3.0],
        grid_size=[18.0, 18.0, 18.0],
        molecule_id="MOL-VINA",
    )

    command, pose_file = docking_adapters.build_vina_docker_command("vina:latest", request)

    assert command[:3] == ["docker", "run", "--rm"]
    assert "vina:latest" in command
    assert command[command.index("vina:latest") + 1] == "-c"
    script = command[-1]
    assert "from vina import Vina" in script
    assert "v.set_receptor('/data/receptor/protein.pdbqt')" in script
    assert "v.set_ligand_from_file('/data/ligand/ligand.pdbqt')" in script
    assert "REMARK VINA RESULT" in script
    assert pose_file == str(tmp_path / "poses" / "MOL-VINA_vina_pose.pdbqt")
