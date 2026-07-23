from types import SimpleNamespace

from medagent.services import docking_adapters
from medagent.services.docking_adapters import (
    DockingToolRequest,
    build_gnina_command,
    build_vina_command,
    check_gnina_available,
    parse_gnina_output,
    parse_vina_output,
    run_external_docking,
    select_docking_tool,
)


def _request(tmp_path, *, receptor_suffix=".pdb", ligand_suffix=".sdf"):
    receptor = tmp_path / f"receptor{receptor_suffix}"
    ligand = tmp_path / f"ligand{ligand_suffix}"
    receptor.write_text("receptor", encoding="utf-8")
    ligand.write_text("ligand", encoding="utf-8")
    return DockingToolRequest(
        receptor_file=str(receptor),
        ligand_file=str(ligand),
        output_dir=str(tmp_path / "poses"),
        grid_center=[1.0, 2.0, 3.0],
        grid_size=[18.0, 19.0, 20.0],
        exhaustiveness=16,
        molecule_id="MOL LOCAL/1",
    )


def test_local_command_builders_include_grid(tmp_path):
    gnina_command, gnina_pose = build_gnina_command("gnina.exe", _request(tmp_path))
    vina_command, vina_pose = build_vina_command(
        "vina.exe", _request(tmp_path, receptor_suffix=".pdbqt", ligand_suffix=".pdbqt")
    )

    assert gnina_command[:3] == ["gnina.exe", "-r", str(tmp_path / "receptor.pdb")]
    assert "--center_x" in gnina_command and "1.0" in gnina_command
    assert gnina_pose.endswith("MOL_LOCAL_1_gnina_pose.sdf")
    assert vina_command[:3] == ["vina.exe", "--receptor", str(tmp_path / "receptor.pdbqt")]
    assert vina_pose.endswith("MOL_LOCAL_1_vina_pose.pdbqt")


def test_selection_prefers_gnina_and_requires_prepared_inputs_for_vina(tmp_path):
    request = _request(tmp_path)
    status = {"gnina": {"available": True}, "vina": {"available": True}}
    assert select_docking_tool(request, status) == "gnina"

    local_vina_only = {"gnina": {"available": False}, "vina": {"available": True}}
    assert select_docking_tool(request, local_vina_only) is None
    prepared_request = _request(tmp_path, receptor_suffix=".pdbqt", ligand_suffix=".pdbqt")
    assert select_docking_tool(prepared_request, local_vina_only) == "vina"


def test_external_docking_requires_a_local_score_and_pose_artifact(tmp_path, monkeypatch):
    request = _request(tmp_path)

    def fake_run(command, _timeout):
        pose = command[command.index("-o") + 1]
        with open(pose, "w", encoding="utf-8") as handle:
            handle.write("local GNINA pose\n")
        return 0, "1 | -8.3 | 0.61 | -7.1\n", "", 0.01

    monkeypatch.setattr(docking_adapters, "_run_command", fake_run)
    result = run_external_docking(request, {"gnina": {"available": True, "path": "gnina.exe"}})

    assert result is not None and result.success is True
    assert result.adapter_mode == "gnina_local_docking"
    assert result.vina_score == -8.3
    assert result.cnn_score == 0.61
    assert result.pose_file and result.command[0] == "gnina.exe"
    assert "external_docking_pose_confirmed" in result.labels


def test_successful_process_without_pose_is_not_reported_as_docking_evidence(tmp_path, monkeypatch):
    request = _request(tmp_path)
    monkeypatch.setattr(
        docking_adapters,
        "_run_command",
        lambda _command, _timeout: (0, "1 | -7.7 | 0.55 | -6.8\n", "", 0.01),
    )

    result = run_external_docking(request, {"gnina": {"available": True, "path": "gnina.exe"}})

    assert result is not None and result.success is False
    assert result.pose_file is None
    assert "external_docking_pose_file_missing" in result.warnings


def test_local_status_probes_a_host_executable_without_a_container(monkeypatch):
    monkeypatch.setenv("MEDAGENT_GNINA_RUNTIME", "host")
    monkeypatch.setattr(
        docking_adapters, "_find_local_executable", lambda _command: "C:/tools/gnina.exe"
    )
    monkeypatch.setattr(
        docking_adapters.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="GNINA 1.3\n", stderr=""),
    )

    status = check_gnina_available()

    assert status["available"] is True
    assert status["mode"] == "local_cli"
    assert status["path"] == "C:/tools/gnina.exe"


def test_gnina_wsl_execution_maps_windows_artifact_paths(tmp_path, monkeypatch):
    request = _request(tmp_path)
    captured = {}

    def fake_run(command, _timeout):
        captured["command"] = command
        pose = tmp_path / "poses" / "MOL_LOCAL_1_gnina_pose.sdf"
        pose.parent.mkdir(parents=True, exist_ok=True)
        pose.write_text("local GNINA pose\n", encoding="utf-8")
        return 0, "1 | -8.3 | 0.61 | -7.1\n", "", 0.01

    monkeypatch.setattr(docking_adapters, "_run_command", fake_run)
    result = run_external_docking(
        request,
        {
            "gnina": {
                "available": True,
                "path": "/opt/tools/gnina",
                "runtime_scope": "wsl",
                "wsl_distribution": "Ubuntu",
                "wsl_user": "root",
                "runtime_environment": {"LD_LIBRARY_PATH": "/opt/medagent/envs/gnina-runtime/lib"},
            }
        },
    )

    assert result is not None and result.success is True
    assert captured["command"][:6] == ["wsl", "-d", "Ubuntu", "-u", "root", "--"]
    shell_command = captured["command"][-1]
    assert "/mnt/" in shell_command
    assert "receptor.pdb" in shell_command and "ligand.sdf" in shell_command
    assert "LD_LIBRARY_PATH=/opt/medagent/envs/gnina-runtime/lib" in shell_command
    assert result.pose_file == str(tmp_path / "poses" / "MOL_LOCAL_1_gnina_pose.sdf")


def test_parsers_keep_gnina_and_vina_score_semantics_separate():
    gnina = parse_gnina_output("1 | -7.4 | 0.02 | 0.78 | -6.5\n")
    vina = parse_vina_output("   1       -8.1      0.0      0.0\n")

    assert gnina["vina_score"] == -7.4
    assert gnina["cnn_score"] == 0.78
    assert gnina["cnn_affinity"] == -6.5
    assert vina["vina_score"] == -8.1
