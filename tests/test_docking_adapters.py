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
    assert parsed["selected_pose_rank"] == 1
    assert parsed["pose_count"] == 2
    assert parsed["pose_selection_method"] == "vina_lowest_affinity_mode_1"


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


def test_parse_gnina_1_3_3_output_with_intramol_column():
    stdout = """
mode |  affinity  |  intramol  |    CNN     |   CNN
     | (kcal/mol) | (kcal/mol) | pose score | affinity
-----+------------+------------+------------+----------
    1       -5.73       -0.16       0.8596      4.520
    2       -0.77       -0.15       0.7724      4.539
"""

    parsed = docking_adapters.parse_gnina_output(stdout)

    assert parsed["vina_score"] == -5.73
    assert parsed["cnn_score"] == 0.86
    assert parsed["cnn_affinity"] == 4.52
    assert parsed["selected_pose_rank"] == 1
    assert parsed["pose_count"] == 2
    assert parsed["pose_selection_method"] == "gnina_output_mode_1"


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


def test_select_docking_tool_uses_vina_when_docker_gnina_has_no_gpu(tmp_path):
    request = DockingToolRequest(
        receptor_file=str(tmp_path / "protein.pdbqt"),
        ligand_file=str(tmp_path / "ligand.pdbqt"),
        output_dir=str(tmp_path / "poses"),
        grid_center=[1.0, 2.0, 3.0],
        grid_size=[18.0, 19.0, 20.0],
        molecule_id="MOL-GPU-FALLBACK",
    )

    selected = docking_adapters.select_docking_tool(
        request,
        {
            "gnina": {"available": True, "mode": "docker", "gpu_available": False},
            "vina": {"available": True, "mode": "docker"},
        },
    )

    assert selected == "vina"


def test_gnina_command_uses_receptor_ligand_grid_and_output(tmp_path, monkeypatch):
    # Mock GPU check to return False (CPU mode)
    monkeypatch.setattr(docking_adapters, "_check_gpu_available", lambda: False)

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
        Path(command[command.index("-o") + 1]).write_text("pose\n$$$$\n", encoding="utf-8")
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
        Path(command[command.index("--out") + 1]).write_text("POSE\n", encoding="utf-8")
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
        pose_file = tmp_path / "poses" / "MOL-DOCKER_gnina_pose.sdf"
        pose_file.parent.mkdir(parents=True, exist_ok=True)
        pose_file.write_text("pose\n$$$$\n", encoding="utf-8")
        return CompletedProcess()

    # Mock GPU check to return False
    monkeypatch.setattr(docking_adapters, "_check_gpu_available", lambda: False)
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
    assert "--name" in command
    assert "gnina/gnina:latest" in command
    assert command[command.index("gnina/gnina:latest") + 1] == "gnina"
    assert "/data/receptor/protein.pdb" in command
    assert "/data/ligand/ligand.sdf" in command
    # Should have CPU mode flag
    assert "--cnn_scoring" in command
    assert "none" in command


def test_gnina_result_does_not_confirm_missing_pose_file(tmp_path, monkeypatch):
    monkeypatch.setattr(
        docking_adapters,
        "_run_command",
        lambda command, timeout: (
            0,
            "Affinity: -8.2\nCNNscore: 0.73\nCNNaffinity: -7.6\n",
            "",
            0.1,
        ),
    )

    result = docking_adapters.run_gnina_docking(
        "gnina",
        DockingToolRequest(
            receptor_file=str(tmp_path / "protein.pdb"),
            ligand_file=str(tmp_path / "ligand.sdf"),
            output_dir=str(tmp_path / "poses"),
            grid_center=[1.0, 2.0, 3.0],
            grid_size=[18.0, 18.0, 18.0],
            molecule_id="MOL-MISSING-POSE",
        ),
    )

    assert result.success is False
    assert result.pose_file is None
    assert result.best_pose_confirmed is False
    assert "external_docking_pose_file_missing" in result.warnings


def test_diffdock_command_uses_model_directories_from_settings(tmp_path, monkeypatch):
    score_dir = tmp_path / "score_model"
    confidence_dir = tmp_path / "confidence_model"
    score_dir.mkdir()
    confidence_dir.mkdir()

    monkeypatch.delenv("DIFFDOCK_MODEL_DIR", raising=False)
    monkeypatch.delenv("DIFFDOCK_CONFIDENCE_MODEL_DIR", raising=False)
    monkeypatch.setattr(
        docking_adapters,
        "get_settings",
        lambda: type(
            "SettingsStub",
            (),
            {
                "diffdock_model_dir": str(score_dir),
                "diffdock_confidence_model_dir": str(confidence_dir),
            },
        )(),
    )

    request = DockingToolRequest(
        receptor_file=str(tmp_path / "protein.pdb"),
        ligand_file=str(tmp_path / "ligand.sdf"),
        output_dir=str(tmp_path / "poses"),
        molecule_id="MOL-1",
    )

    command = docking_adapters.build_diffdock_docker_command(
        "diffdock:latest",
        request,
        data_dir=tmp_path,
        use_gpu=False,
    )

    assert f"{score_dir.resolve()}:/models/score:ro" in command
    assert f"{confidence_dir.resolve()}:/models/confidence:ro" in command
    assert command[command.index("--model_dir") + 1] == "/models/score"
    assert command[command.index("--ckpt") + 1] == "best_ema_inference_epoch_model.pt"
    assert command[command.index("--confidence_model_dir") + 1] == "/models/confidence"
    assert command[command.index("--confidence_ckpt") + 1] == "best_model_epoch75.pt"


def test_diffdock_model_configuration_requires_parameters_and_checkpoints(
    tmp_path, monkeypatch
):
    score_dir = tmp_path / "score_model"
    confidence_dir = tmp_path / "confidence_model"
    score_dir.mkdir()
    confidence_dir.mkdir()
    (score_dir / "best_ema_inference_epoch_model.pt").write_bytes(b"score")
    (confidence_dir / "best_model_epoch75.pt").write_bytes(b"confidence")

    monkeypatch.setenv("DIFFDOCK_MODEL_DIR", str(score_dir))
    monkeypatch.setenv("DIFFDOCK_CONFIDENCE_MODEL_DIR", str(confidence_dir))

    assert docking_adapters._diffdock_models_configured() is False

    (score_dir / "model_parameters.yml").write_text("model: score\n", encoding="utf-8")
    (confidence_dir / "model_parameters.yml").write_text(
        "model: confidence\n", encoding="utf-8"
    )

    assert docking_adapters._diffdock_models_configured() is True


def test_diffdock_image_probe_checks_only_upstream_default_model_files(monkeypatch):
    commands = []

    def fake_probe(command, timeout=10):
        commands.append(command)
        return type("CompletedProcess", (), {"returncode": 2})()

    monkeypatch.setattr(docking_adapters, "_run_probe", fake_probe)

    assert docking_adapters._diffdock_image_has_default_models("diffdock:latest") is False
    probe_script = commands[0][commands[0].index("-c") + 1]
    assert "paper_score_model" in probe_script
    assert "paper_confidence_model" in probe_script
    assert "model_parameters.yml" in probe_script
    assert "rglob" not in probe_script


def test_diffdock_status_keeps_model_configuration_when_runtime_is_missing(monkeypatch):
    monkeypatch.setattr(docking_adapters, "_run_probe", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        docking_adapters,
        "_first_existing_docker_image",
        lambda images: None,
    )
    monkeypatch.setattr(
        docking_adapters,
        "_diffdock_configured_model_artifacts",
        lambda: {"score_checkpoint": {"path": "score.pt", "size_bytes": 1}},
    )

    status = docking_adapters.check_diffdock_available()

    assert status["runtime_available"] is False
    assert status["model_configured"] is True


def test_gnina_status_detects_docker_image_when_binary_is_missing(monkeypatch):
    def fake_which(command):
        assert command == "gnina"
        return None

    commands = []

    def fake_run(command, capture_output, text, timeout, check=False):
        commands.append(command)
        if command[:3] == ["docker", "image", "inspect"]:
            return type("CompletedProcess", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        if "--version" in command:
            return type(
                "CompletedProcess",
                (),
                {"returncode": 0, "stdout": "gnina v1.3.3\n", "stderr": ""},
            )()
        if "nvidia-smi" in command:
            return type(
                "CompletedProcess",
                (),
                {"returncode": 0, "stdout": "GPU 0: NVIDIA RTX\n", "stderr": ""},
            )()
        raise AssertionError(command)

    monkeypatch.setattr(docking_adapters.shutil, "which", fake_which)
    monkeypatch.setattr(docking_adapters.subprocess, "run", fake_run)

    status = docking_adapters.check_gnina_available()

    assert status["available"] is True
    assert status["mode"] == "docker"
    assert status["docker_image"] == "gnina/gnina:latest"
    assert status["version"] == "gnina v1.3.3"
    assert status["gpu_available"] is True
    assert any("--version" in command for command in commands)


def test_gpu_probe_requires_successful_nvidia_smi(monkeypatch):
    def fake_run(*_args, **_kwargs):
        return type(
            "CompletedProcess",
            (),
            {"returncode": 125, "stdout": b"", "stderr": b"could not select device driver"},
        )()

    monkeypatch.setattr(docking_adapters.subprocess, "run", fake_run)

    assert docking_adapters._check_gpu_available("gnina/gnina:latest") is False


def test_vina_status_runs_python_import_probe(monkeypatch):
    commands = []
    monkeypatch.setattr(docking_adapters.shutil, "which", lambda _command: None)

    def fake_run(command, capture_output, text, timeout, check=False):
        commands.append(command)
        if command[:3] == ["docker", "image", "inspect"]:
            return type("CompletedProcess", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        return type(
            "CompletedProcess",
            (),
            {"returncode": 0, "stdout": "vina-python-ok\n", "stderr": ""},
        )()

    monkeypatch.setattr(docking_adapters.subprocess, "run", fake_run)

    status = docking_adapters.check_vina_available()

    assert status["available"] is True
    assert status["mode"] == "docker"
    assert any("from vina import Vina" in " ".join(command) for command in commands)


def test_tool_warnings_classifies_invalid_receptor_pdbqt():
    warnings = docking_adapters._tool_warnings(
        1,
        None,
        "PDBQT parsing error: Unknown or inappropriate tag found in rigid receptor. > ROOT",
    )

    assert "external_docking_invalid_receptor_pdbqt" in warnings
    assert "external_docking_tool_failed" in warnings


def test_vina_docker_command_uses_python_vina_package_with_pdbqt_inputs(tmp_path, monkeypatch):
    # Mock GPU check to return False
    monkeypatch.setattr(docking_adapters, "_check_gpu_available", lambda: False)

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
    assert "--name" in command
    assert "vina:latest" in command
    assert command[command.index("vina:latest") + 1] == "-c"
    script = command[-1]
    assert "from vina import Vina" in script
    assert "v.set_receptor('/data/receptor/protein.pdbqt')" in script
    assert "v.set_ligand_from_file('/data/ligand/ligand.pdbqt')" in script
    assert "REMARK VINA RESULT" in script
    assert pose_file == str(tmp_path / "poses" / "MOL-VINA_vina_pose.pdbqt")


def test_gnina_docker_includes_gpu_flag_when_available(tmp_path, monkeypatch):
    # Mock GPU check to return True
    monkeypatch.setattr(docking_adapters, "_check_gpu_available", lambda: True)

    request = DockingToolRequest(
        receptor_file=str(tmp_path / "protein.pdb"),
        ligand_file=str(tmp_path / "ligand.sdf"),
        output_dir=str(tmp_path / "poses"),
        grid_center=[1.0, 2.0, 3.0],
        grid_size=[18.0, 18.0, 18.0],
        molecule_id="MOL-GPU",
    )

    command, _ = docking_adapters.build_gnina_docker_command(
        "gnina/gnina:latest", request, use_gpu=True, cpu_mode=False
    )

    assert "--gpus" in command
    assert "all" in command
    # Should NOT have CPU mode flag when GPU is available
    assert "--cnn_scoring" not in command or "none" not in command


def test_gnina_cpu_mode_disables_cnn_scoring(tmp_path, monkeypatch):
    # Mock GPU check to return False
    monkeypatch.setattr(docking_adapters, "_check_gpu_available", lambda: False)

    request = DockingToolRequest(
        receptor_file=str(tmp_path / "protein.pdb"),
        ligand_file=str(tmp_path / "ligand.sdf"),
        output_dir=str(tmp_path / "poses"),
        grid_center=[1.0, 2.0, 3.0],
        grid_size=[18.0, 18.0, 18.0],
        molecule_id="MOL-CPU",
    )

    command, _ = docking_adapters.build_gnina_docker_command(
        "gnina/gnina:latest", request, use_gpu=False, cpu_mode=True
    )

    assert "--cnn_scoring" in command
    assert "none" in command
    # Should NOT have GPU flag in CPU mode
    assert "--gpus" not in command


def test_timeout_cleanup_removes_docker_container(tmp_path, monkeypatch):
    import subprocess

    cleanup_calls = []

    def fake_run(command, capture_output, text, timeout, check=False):
        # Simulate timeout
        raise subprocess.TimeoutExpired(command, timeout)

    def fake_cleanup_run(command, capture_output, timeout, check):
        cleanup_calls.append(command)
        class FakeResult:
            returncode = 0
        return FakeResult()

    monkeypatch.setattr(docking_adapters.subprocess, "run", fake_run)
    monkeypatch.setattr(docking_adapters, "_cleanup_docker_container", lambda name: cleanup_calls.append(["docker", "rm", "-f", name]))

    command = ["docker", "run", "--rm", "--name", "test_container", "gnina/gnina:latest", "gnina"]

    exit_code, stdout, stderr, runtime = docking_adapters._run_command(command, 10)

    assert exit_code is None
    assert "timeout" in stderr.lower()
    assert len(cleanup_calls) > 0
    assert "test_container" in cleanup_calls[0]


def test_diffdock_docker_command_uses_upstream_inference_arguments(tmp_path):
    request = DockingToolRequest(
        receptor_file=str(tmp_path / "protein.pdb"),
        ligand_file=str(tmp_path / "ligand.sdf"),
        output_dir=str(tmp_path / "poses"),
        grid_center=[1.0, 2.0, 3.0],
        grid_size=[18.0, 18.0, 18.0],
        molecule_id="MOL-DIFFDOCK",
    )

    command = docking_adapters.build_diffdock_docker_command(
        "diffdock:latest",
        request,
        data_dir=tmp_path,
        use_gpu=True,
    )

    assert "/app/diffdock/inference.py" in command
    assert "--ligand_description" in command
    assert "--out_dir" in command
    assert "--ligand_path" not in command
    assert "--output_dir" not in command
    assert command[command.index("--complex_name") + 1] == "MOL-DIFFDOCK"
    assert command[command.index("--gpus") + 1] == "all"


def test_parse_diffdock_output_reads_confidence_from_pose_filename(tmp_path):
    pose = tmp_path / "MOL-DIFFDOCK_rank1_confidence-1.234.sdf"
    pose.write_text("pose\n$$$$\n", encoding="utf-8")
    second_pose = tmp_path / "MOL-DIFFDOCK_rank2_confidence-2.345.sdf"
    second_pose.write_text("pose\n$$$$\n", encoding="utf-8")

    parsed = docking_adapters.parse_diffdock_output("", tmp_path, "MOL-DIFFDOCK")

    assert parsed["confidence_score"] == -1.234
    assert parsed["pose_file"] == str(pose)
    assert parsed["selected_pose_rank"] == 1
    assert parsed["pose_count"] == 2
    assert parsed["pose_selection_method"] == "diffdock_rank_1_by_confidence"
    assert parsed["best_pose_confirmed"] is True


def test_parse_diffdock_output_does_not_claim_rank_two_is_best(tmp_path):
    pose = tmp_path / "MOL-DIFFDOCK_rank2_confidence-0.750.sdf"
    pose.write_text("pose\n$$$$\n", encoding="utf-8")

    parsed = docking_adapters.parse_diffdock_output(
        "rank_1: 9.999", tmp_path, "MOL-DIFFDOCK"
    )

    assert parsed["confidence_score"] == -0.75
    assert parsed["pose_file"] == str(pose)
    assert parsed["selected_pose_rank"] == 2
    assert parsed["pose_count"] == 1
    assert (
        parsed["pose_selection_method"]
        == "lowest_available_diffdock_rank_best_not_confirmed"
    )
    assert parsed["best_pose_confirmed"] is False


def test_diffdock_result_keeps_confidence_separate_from_gnina_cnn_score(tmp_path, monkeypatch):
    output_dir = tmp_path / "poses"
    output_dir.mkdir()

    def fake_run(command, timeout):
        assert command[command.index("--complex_name") + 1] == "MOL-DIFFDOCK"
        assert "--complex_id" not in command
        run_output_dir = Path(command[command.index("--out_dir") + 1])
        pose = run_output_dir / "MOL-DIFFDOCK_rank1_confidence-1.234.sdf"
        pose.write_text("pose\n$$$$\n", encoding="utf-8")
        return 0, "", "", 0.1

    monkeypatch.setattr(docking_adapters, "_run_command", fake_run)

    result = docking_adapters.run_diffdock_docking(
        DockingToolRequest(
            receptor_file=str(tmp_path / "protein.pdb"),
            ligand_file=str(tmp_path / "ligand.sdf"),
            output_dir=str(output_dir),
            grid_center=[1.0, 2.0, 3.0],
            grid_size=[18.0, 18.0, 18.0],
            molecule_id="MOL-DIFFDOCK",
        ),
        {"mode": "local"},
    )

    assert result.success is True
    assert result.tool_name == "diffdock"
    assert result.cnn_score is None
    assert result.diffdock_confidence == -1.234
    assert result.pose_file is not None
    assert Path(result.pose_file).parent != output_dir
