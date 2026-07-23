from medagent.services.wsl_runtime import build_wsl_command, windows_path_to_wsl


def test_windows_path_to_wsl_maps_drive_and_preserves_linux_paths():
    assert windows_path_to_wsl(r"C:\Users\zhihong\work item\input.sdf") == (
        "/mnt/c/Users/zhihong/work item/input.sdf"
    )
    assert windows_path_to_wsl("/opt/medagent/envs/tool/bin/python") == (
        "/opt/medagent/envs/tool/bin/python"
    )


def test_build_wsl_command_quotes_workdir_environment_and_arguments():
    command = build_wsl_command(
        ["/opt/tool/bin/python", "/mnt/c/work item/run.py", "--value", "a b"],
        distribution="Ubuntu",
        user="root",
        cwd="/mnt/c/work item",
        environment={"PYTHONPATH": "/mnt/c/work item"},
    )

    assert command[:7] == ["wsl", "-d", "Ubuntu", "-u", "root", "--", "bash"]
    assert command[7] == "-lc"
    assert "cd '/mnt/c/work item'" in command[8]
    assert "PYTHONPATH=/mnt/c/work item" in command[8]
    assert "'/mnt/c/work item/run.py'" in command[8]
    assert "'a b'" in command[8]
