import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from medagent.core.config import get_settings
from medagent.services.docker_runtime import DockerMountBuilder, docker_temporary_directory


_FLOAT_PATTERN = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)"


@dataclass(frozen=True)
class DockingToolRequest:
    receptor_file: str
    ligand_file: str
    output_dir: str
    grid_center: list[float] | None = None
    grid_size: list[float] | None = None
    exhaustiveness: int = 8
    timeout_seconds: int = 300
    molecule_id: str | None = None


@dataclass(frozen=True)
class DockingToolResult:
    adapter_mode: str
    tool_name: str
    success: bool
    vina_score: float | None = None
    cnn_score: float | None = None
    cnn_affinity: float | None = None
    diffdock_confidence: float | None = None
    pose_file: str | None = None
    selected_pose_rank: int | None = None
    pose_count: int | None = None
    pose_selection_method: str | None = None
    best_pose_confirmed: bool = False
    labels: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    runtime_seconds: float = 0.0
    command: list[str] = field(default_factory=list)


def run_external_docking(
    request: DockingToolRequest,
    tool_status: dict[str, Any],
) -> DockingToolResult | None:
    validation_warnings = validate_docking_request(request)
    if validation_warnings:
        return DockingToolResult(
            adapter_mode="external_docking_unavailable",
            tool_name="external_docking",
            success=False,
            labels=["external_docking_adapter_failed"],
            warnings=validation_warnings,
        )

    selected_tool = select_docking_tool(request, tool_status)
    if selected_tool == "gnina":
        if tool_status["gnina"].get("mode") == "docker":
            return run_gnina_docker_docking(request, tool_status["gnina"])
        executable = str(tool_status["gnina"].get("path") or "gnina")
        return run_gnina_docking(executable, request)
    if selected_tool == "vina":
        if tool_status["vina"].get("mode") == "docker":
            return run_vina_docker_docking(request, tool_status["vina"])
        executable = str(tool_status["vina"].get("path") or "vina")
        return run_vina_docking(executable, request)
    if selected_tool == "diffdock":
        return run_diffdock_docking(request, tool_status.get("diffdock", {}))
    return None


def select_docking_tool(
    request: DockingToolRequest,
    tool_status: dict[str, Any],
) -> str | None:
    if tool_status.get("gnina", {}).get("available"):
        return "gnina"
    if tool_status.get("vina", {}).get("available") and _has_vina_prepared_pair(request):
        return "vina"
    if tool_status.get("diffdock", {}).get("available"):
        return "diffdock"
    return None


def validate_docking_request(request: DockingToolRequest) -> list[str]:
    warnings: list[str] = []
    if not Path(request.receptor_file).exists():
        warnings.append("receptor_file_not_found")
    if not Path(request.ligand_file).exists():
        warnings.append("ligand_file_not_found")
    if not _is_vector3(request.grid_center) or not _is_vector3(request.grid_size):
        warnings.append("grid_center_and_grid_size_required_for_external_docking")
    return warnings


def build_gnina_command(
    executable: str,
    request: DockingToolRequest,
) -> tuple[list[str], str]:
    pose_file = str(
        Path(request.output_dir) / f"{_safe_pose_prefix(request.molecule_id)}_gnina_pose.sdf"
    )
    command = [
        executable,
        "-r",
        request.receptor_file,
        "-l",
        request.ligand_file,
        "-o",
        pose_file,
        "--exhaustiveness",
        str(request.exhaustiveness),
    ]
    command.extend(_grid_args(request))
    return command, pose_file


def build_gnina_docker_command(
    docker_image: str,
    request: DockingToolRequest,
    use_gpu: bool = True,
    cpu_mode: bool = False,
) -> tuple[list[str], str]:
    receptor_file = Path(request.receptor_file).resolve()
    ligand_file = Path(request.ligand_file).resolve()
    output_dir = Path(request.output_dir).resolve()
    pose_file = output_dir / f"{_safe_pose_prefix(request.molecule_id)}_gnina_pose.sdf"
    container_name = f"gnina_{_safe_pose_prefix(request.molecule_id)}_{int(time.time() * 1000)}"
    mounts = DockerMountBuilder()
    receptor_dir = mounts.bind(receptor_file.parent, "/data/receptor", read_only=True)
    ligand_dir = mounts.bind(ligand_file.parent, "/data/ligand", read_only=True)
    output_path = mounts.bind(output_dir, "/data/output")

    command = [
        "docker",
        "run",
        "--rm",
        "--name",
        container_name,
    ]

    # Add GPU support if available and requested
    if use_gpu and not cpu_mode:
        command.extend(["--gpus", "all"])

    command.extend([*mounts.arguments,
        docker_image,
        "gnina",
        "-r",
        str(PurePosixPath(receptor_dir, receptor_file.name)),
        "-l",
        str(PurePosixPath(ligand_dir, ligand_file.name)),
        "-o",
        str(PurePosixPath(output_path, pose_file.name)),
        "--exhaustiveness",
        str(request.exhaustiveness),
    ])

    # Add CPU-friendly parameters if in CPU mode
    if cpu_mode:
        command.extend(["--cnn_scoring", "none"])

    command.extend(_grid_args(request))
    return command, str(pose_file)


def build_vina_command(
    executable: str,
    request: DockingToolRequest,
) -> tuple[list[str], str]:
    pose_file = str(
        Path(request.output_dir) / f"{_safe_pose_prefix(request.molecule_id)}_vina_pose.pdbqt"
    )
    command = [
        executable,
        "--receptor",
        request.receptor_file,
        "--ligand",
        request.ligand_file,
        "--out",
        pose_file,
        "--exhaustiveness",
        str(request.exhaustiveness),
    ]
    command.extend(_grid_args(request))
    return command, pose_file


def build_vina_docker_command(
    docker_image: str,
    request: DockingToolRequest,
    use_gpu: bool = False,
) -> tuple[list[str], str]:
    receptor_file = Path(request.receptor_file).resolve()
    ligand_file = Path(request.ligand_file).resolve()
    output_dir = Path(request.output_dir).resolve()
    pose_file = output_dir / f"{_safe_pose_prefix(request.molecule_id)}_vina_pose.pdbqt"
    container_name = f"vina_{_safe_pose_prefix(request.molecule_id)}_{int(time.time() * 1000)}"
    mounts = DockerMountBuilder()
    receptor_dir = mounts.bind(receptor_file.parent, "/data/receptor", read_only=True)
    ligand_dir = mounts.bind(ligand_file.parent, "/data/ligand", read_only=True)
    output_path = mounts.bind(output_dir, "/data/output")

    script = _vina_docker_python_script(
        receptor_path=str(PurePosixPath(receptor_dir, receptor_file.name)),
        ligand_path=str(PurePosixPath(ligand_dir, ligand_file.name)),
        pose_path=str(PurePosixPath(output_path, pose_file.name)),
        request=request,
    )
    command = [
        "docker",
        "run",
        "--rm",
        "--name",
        container_name,
    ]

    # Vina doesn't typically need GPU, but allow it if requested
    if use_gpu:
        command.extend(["--gpus", "all"])

    command.extend([*mounts.arguments,
        docker_image,
        "-c",
        script,
    ])
    return command, str(pose_file)


def run_gnina_docking(executable: str, request: DockingToolRequest) -> DockingToolResult:
    Path(request.output_dir).mkdir(parents=True, exist_ok=True)
    command, pose_file = build_gnina_command(executable, request)
    exit_code, stdout, stderr, runtime_seconds = _run_command(command, request.timeout_seconds)
    parsed = parse_gnina_output(_combined_output(stdout, stderr))
    pose_exists = pose_artifact_available(pose_file)
    success = exit_code == 0 and parsed["vina_score"] is not None and pose_exists
    warnings = _tool_warnings(exit_code, parsed["vina_score"], stderr)
    if exit_code == 0 and parsed["vina_score"] is not None and not pose_exists:
        warnings.append("external_docking_pose_file_missing")
    return DockingToolResult(
        adapter_mode="gnina_external_docking",
        tool_name="gnina",
        success=success,
        vina_score=parsed["vina_score"],
        cnn_score=parsed["cnn_score"],
        cnn_affinity=parsed["cnn_affinity"],
        pose_file=pose_file if success else None,
        selected_pose_rank=parsed["selected_pose_rank"],
        pose_count=parsed["pose_count"],
        pose_selection_method=parsed["pose_selection_method"],
        best_pose_confirmed=bool(parsed["best_pose_confirmed"] and pose_exists),
        labels=_result_labels("gnina", success),
        warnings=warnings,
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        runtime_seconds=runtime_seconds,
        command=command,
    )


def run_gnina_docker_docking(
    request: DockingToolRequest,
    gnina_status: dict[str, Any],
) -> DockingToolResult:
    Path(request.output_dir).mkdir(parents=True, exist_ok=True)
    docker_image = gnina_status.get("docker_image") or "gnina/gnina:latest"

    has_gpu = bool(gnina_status.get("gpu_available"))
    if "gpu_available" not in gnina_status:
        has_gpu = _check_gpu_available()
    cpu_mode = not has_gpu

    command, pose_file = build_gnina_docker_command(
        docker_image,
        request,
        use_gpu=has_gpu,
        cpu_mode=cpu_mode,
    )
    exit_code, stdout, stderr, runtime_seconds = _run_command(command, request.timeout_seconds)
    parsed = parse_gnina_output(_combined_output(stdout, stderr))
    pose_exists = pose_artifact_available(pose_file)
    success = exit_code == 0 and parsed["vina_score"] is not None and pose_exists
    warnings = _tool_warnings(exit_code, parsed["vina_score"], stderr)
    if exit_code == 0 and parsed["vina_score"] is not None and not pose_exists:
        warnings.append("external_docking_pose_file_missing")

    if cpu_mode:
        warnings.append("gnina_running_in_cpu_mode")

    return DockingToolResult(
        adapter_mode="gnina_docker_docking",
        tool_name="gnina",
        success=success,
        vina_score=parsed["vina_score"],
        cnn_score=parsed["cnn_score"],
        cnn_affinity=parsed["cnn_affinity"],
        pose_file=pose_file if success else None,
        selected_pose_rank=parsed["selected_pose_rank"],
        pose_count=parsed["pose_count"],
        pose_selection_method=parsed["pose_selection_method"],
        best_pose_confirmed=bool(parsed["best_pose_confirmed"] and pose_exists),
        labels=_result_labels("gnina", success),
        warnings=warnings,
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        runtime_seconds=runtime_seconds,
        command=command,
    )


def run_vina_docking(executable: str, request: DockingToolRequest) -> DockingToolResult:
    Path(request.output_dir).mkdir(parents=True, exist_ok=True)
    command, pose_file = build_vina_command(executable, request)
    exit_code, stdout, stderr, runtime_seconds = _run_command(command, request.timeout_seconds)
    parsed = parse_vina_output(_combined_output(stdout, stderr))
    pose_exists = pose_artifact_available(pose_file)
    success = exit_code == 0 and parsed["vina_score"] is not None and pose_exists
    warnings = _tool_warnings(exit_code, parsed["vina_score"], stderr)
    if exit_code == 0 and parsed["vina_score"] is not None and not pose_exists:
        warnings.append("external_docking_pose_file_missing")
    return DockingToolResult(
        adapter_mode="vina_external_docking",
        tool_name="vina",
        success=success,
        vina_score=parsed["vina_score"],
        pose_file=pose_file if success else None,
        selected_pose_rank=parsed["selected_pose_rank"],
        pose_count=parsed["pose_count"],
        pose_selection_method=parsed["pose_selection_method"],
        best_pose_confirmed=bool(parsed["best_pose_confirmed"] and pose_exists),
        labels=_result_labels("vina", success),
        warnings=warnings,
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        runtime_seconds=runtime_seconds,
        command=command,
    )


def run_vina_docker_docking(
    request: DockingToolRequest,
    vina_status: dict[str, Any],
) -> DockingToolResult:
    Path(request.output_dir).mkdir(parents=True, exist_ok=True)
    docker_image = vina_status.get("docker_image") or "vina:latest"
    command, pose_file = build_vina_docker_command(docker_image, request)
    exit_code, stdout, stderr, runtime_seconds = _run_command(command, request.timeout_seconds)
    parsed = parse_vina_output(_combined_output(stdout, stderr))
    pose_exists = pose_artifact_available(pose_file)
    success = exit_code == 0 and parsed["vina_score"] is not None and pose_exists
    warnings = _tool_warnings(exit_code, parsed["vina_score"], stderr)
    if exit_code == 0 and parsed["vina_score"] is not None and not pose_exists:
        warnings.append("external_docking_pose_file_missing")
    return DockingToolResult(
        adapter_mode="vina_docker_docking",
        tool_name="vina",
        success=success,
        vina_score=parsed["vina_score"],
        pose_file=pose_file if success else None,
        selected_pose_rank=parsed["selected_pose_rank"],
        pose_count=parsed["pose_count"],
        pose_selection_method=parsed["pose_selection_method"],
        best_pose_confirmed=bool(parsed["best_pose_confirmed"] and pose_exists),
        labels=_result_labels("vina", success),
        warnings=warnings,
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        runtime_seconds=runtime_seconds,
        command=command,
    )


def run_diffdock_docking(
    request: DockingToolRequest,
    diffdock_status: dict[str, Any],
) -> DockingToolResult:
    """Run DiffDock for molecular docking.

    DiffDock is a diffusion-based molecular docking method that predicts
    binding poses without requiring a predefined binding site grid.

    Supports:
    - Local Python package (pip install diffdock)
    - Docker container
    """
    Path(request.output_dir).mkdir(parents=True, exist_ok=True)
    mode = diffdock_status.get("mode")

    if mode == "docker":
        return _run_diffdock_docker(request, diffdock_status)
    else:
        return _run_diffdock_local(request, diffdock_status)


def _run_diffdock_local(
    request: DockingToolRequest,
    diffdock_status: dict[str, Any],
) -> DockingToolResult:
    """Run DiffDock via local Python package."""
    output_dir = Path(request.output_dir)

    # Build DiffDock command
    command = [
        "python", "-m", "diffdock",
        "--protein_path", request.receptor_file,
        "--ligand_description", request.ligand_file,
        "--out_dir", str(output_dir),
    ]

    model_dir = _configured_directory("DIFFDOCK_MODEL_DIR")
    confidence_dir = _configured_directory("DIFFDOCK_CONFIDENCE_MODEL_DIR")
    if model_dir:
        command.extend(["--model_dir", str(model_dir)])
    if confidence_dir:
        command.extend(["--confidence_model_dir", str(confidence_dir)])

    # Add complex_id if molecule_id provided
    if request.molecule_id:
        command.extend(["--complex_id", request.molecule_id])

    exit_code, stdout, stderr, runtime_seconds = _run_command(command, request.timeout_seconds)

    # Parse DiffDock output
    parsed = parse_diffdock_output(stdout, output_dir, request.molecule_id)
    success = exit_code == 0 and parsed.get("confidence_score") is not None

    warnings = []
    if exit_code != 0:
        warnings.append("diffdock_execution_failed")
    if not parsed.get("confidence_score"):
        warnings.append("diffdock_confidence_not_found")

    return DockingToolResult(
        adapter_mode="diffdock_external_docking",
        tool_name="diffdock",
        success=success,
        vina_score=parsed.get("vina_score"),
        diffdock_confidence=parsed.get("confidence_score"),
        pose_file=parsed.get("pose_file") if success else None,
        selected_pose_rank=parsed.get("selected_pose_rank"),
        pose_count=parsed.get("pose_count"),
        pose_selection_method=parsed.get("pose_selection_method"),
        best_pose_confirmed=bool(parsed.get("best_pose_confirmed")),
        labels=_result_labels("diffdock", success),
        warnings=warnings,
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        runtime_seconds=runtime_seconds,
        command=command,
    )


def _run_diffdock_docker(
    request: DockingToolRequest,
    diffdock_status: dict[str, Any],
) -> DockingToolResult:
    """Run DiffDock via Docker container."""
    output_dir = Path(request.output_dir)
    docker_image = diffdock_status.get("docker_image", "diffdock:latest")
    container_name = f"diffdock_{_safe_pose_prefix(request.molecule_id)}_{int(time.time() * 1000)}"

    # Keep Docker inputs on a shared API volume when running inside the API container.
    with docker_temporary_directory(prefix="diffdock_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        protein_link = tmp_path / "protein.pdb"
        ligand_link = tmp_path / "ligand.sdf"
        out_dir = tmp_path / "output"

        # Create symlinks or copy files
        import shutil
        shutil.copy2(request.receptor_file, protein_link)
        shutil.copy2(request.ligand_file, ligand_link)
        out_dir.mkdir()

        has_gpu = bool(diffdock_status.get("gpu_available"))
        if "gpu_available" not in diffdock_status:
            has_gpu = _check_gpu_available(docker_image)

        command = build_diffdock_docker_command(
            docker_image,
            request,
            data_dir=tmp_path,
            use_gpu=has_gpu,
            container_name=container_name,
        )

        exit_code, stdout, stderr, runtime_seconds = _run_command(command, request.timeout_seconds)

        # Copy results back
        if out_dir.exists():
            shutil.copytree(out_dir, output_dir, dirs_exist_ok=True)

        parsed = parse_diffdock_output(stdout, output_dir, request.molecule_id)
        success = exit_code == 0 and parsed.get("confidence_score") is not None

        warnings = []
        if exit_code != 0:
            warnings.append("diffdock_docker_failed")
        if not parsed.get("confidence_score"):
            warnings.append("diffdock_confidence_not_found")
        if not has_gpu:
            warnings.append("diffdock_running_without_gpu")

        return DockingToolResult(
            adapter_mode="diffdock_docker_docking",
            tool_name="diffdock",
            success=success,
            vina_score=parsed.get("vina_score"),
            diffdock_confidence=parsed.get("confidence_score"),
            pose_file=parsed.get("pose_file") if success else None,
            selected_pose_rank=parsed.get("selected_pose_rank"),
            pose_count=parsed.get("pose_count"),
            pose_selection_method=parsed.get("pose_selection_method"),
            best_pose_confirmed=bool(parsed.get("best_pose_confirmed")),
            labels=_result_labels("diffdock", success),
            warnings=warnings,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            runtime_seconds=runtime_seconds,
            command=command,
        )


def parse_diffdock_output(
    stdout: str,
    output_dir: Path,
    molecule_id: str | None,
) -> dict[str, Any]:
    """Parse DiffDock output to extract confidence score and pose file.

    DiffDock outputs:
    - confidence_score: model-specific uncalibrated score; higher is better
    - pose file in SDF format
    """
    result: dict[str, Any] = {
        "confidence_score": None,
        "vina_score": None,
        "pose_file": None,
        "selected_pose_rank": None,
        "pose_count": None,
        "pose_selection_method": None,
        "best_pose_confirmed": False,
    }

    # Parse confidence score from stdout
    confidence_pattern = re.compile(r"confidence[_\s]*score\s*[:=]\s*({_FLOAT_PATTERN})", re.IGNORECASE)
    match = confidence_pattern.search(stdout)
    if match:
        result["confidence_score"] = _rounded(float(match.group(1)))

    # Also try to find rank confidence
    rank_pattern = re.compile(r"rank[_\s]*\d+\s*[:=]\s*({_FLOAT_PATTERN})", re.IGNORECASE)
    match = rank_pattern.search(stdout)
    if match and result["confidence_score"] is None:
        result["confidence_score"] = _rounded(float(match.group(1)))

    # Find the tool-ranked best pose. Do not infer "best" from filesystem order.
    prefix = _safe_pose_prefix(molecule_id)
    all_pose_files = sorted(Path(output_dir).rglob("*.sdf"))
    ranked_pose_files: list[tuple[int, Path]] = []
    for pose_path in all_pose_files:
        rank_match = re.search(r"(?:^|[_-])rank(?P<rank>\d+)(?:[_-]|$)", pose_path.stem, re.IGNORECASE)
        if rank_match:
            ranked_pose_files.append((int(rank_match.group("rank")), pose_path))
    matching_ranked = [item for item in ranked_pose_files if prefix in item[1].stem]
    if matching_ranked:
        ranked_pose_files = matching_ranked
    ranked_pose_files.sort(key=lambda item: (item[0], str(item[1])))

    selected_pose: Path | None = None
    if ranked_pose_files:
        selected_rank, selected_pose = ranked_pose_files[0]
        result["selected_pose_rank"] = selected_rank
        result["pose_count"] = len(ranked_pose_files)
        if selected_rank == 1:
            result["pose_selection_method"] = "diffdock_rank_1_by_confidence"
            result["best_pose_confirmed"] = True
        else:
            result["pose_selection_method"] = (
                "lowest_available_diffdock_rank_best_not_confirmed"
            )
    else:
        matching_files = [path for path in all_pose_files if prefix in path.stem]
        fallback_files = matching_files or all_pose_files
        if fallback_files:
            selected_pose = fallback_files[0]
            result["pose_count"] = len(fallback_files)
            result["pose_selection_method"] = "unranked_pose_output_best_not_confirmed"

    if selected_pose is not None:
        result["pose_file"] = str(selected_pose)
        confidence_match = re.search(
            rf"confidence(?P<score>{_FLOAT_PATTERN})",
            selected_pose.stem,
            re.IGNORECASE,
        )
        if confidence_match:
            # Prefer the score encoded for the selected pose over an unrelated
            # confidence line that may appear earlier in stdout.
            result["confidence_score"] = _rounded(float(confidence_match.group("score")))

    return result


def build_diffdock_docker_command(
    docker_image: str,
    request: DockingToolRequest,
    *,
    data_dir: Path,
    use_gpu: bool,
    container_name: str | None = None,
) -> list[str]:
    mounts = DockerMountBuilder()
    data_path = mounts.bind(data_dir.resolve(), "/data")
    command = [
        "docker",
        "run",
        "--rm",
        "--name",
        container_name
        or f"diffdock_{_safe_pose_prefix(request.molecule_id)}_{int(time.time() * 1000)}",
    ]
    if use_gpu:
        command.extend(["--gpus", "all"])
    model_dir = _configured_directory("DIFFDOCK_MODEL_DIR")
    confidence_dir = _configured_directory("DIFFDOCK_CONFIDENCE_MODEL_DIR")
    model_path = mounts.bind(model_dir, "/models/score", read_only=True) if model_dir else None
    confidence_path = (
        mounts.bind(confidence_dir, "/models/confidence", read_only=True)
        if confidence_dir
        else None
    )
    command.extend([*mounts.arguments, "-w", "/app/diffdock"])
    command.extend(
        [
            "--entrypoint",
            "python",
            docker_image,
            "/app/diffdock/inference.py",
            "--protein_path",
            str(PurePosixPath(data_path, "protein.pdb")),
            "--ligand_description",
            str(PurePosixPath(data_path, "ligand.sdf")),
            "--out_dir",
            str(PurePosixPath(data_path, "output")),
        ]
    )
    if request.molecule_id:
        command.extend(["--complex_name", request.molecule_id])
    if model_path:
        command.extend(["--model_dir", model_path])
    if confidence_path:
        command.extend(
            [
                "--confidence_model_dir",
                confidence_path,
                "--confidence_ckpt",
                "best_model_epoch75.pt",
            ]
        )
    return command


def _configured_directory(env_name: str) -> Path | None:
    configured = os.environ.get(env_name)
    if not configured:
        setting_name = {
            "DIFFDOCK_MODEL_DIR": "diffdock_model_dir",
            "DIFFDOCK_CONFIDENCE_MODEL_DIR": "diffdock_confidence_model_dir",
        }.get(env_name)
        if setting_name:
            configured = getattr(get_settings(), setting_name, None)
    if not configured:
        return None
    path = Path(configured).expanduser().resolve()
    return path if path.is_dir() else None


def _diffdock_models_configured() -> bool:
    model_dir = _configured_directory("DIFFDOCK_MODEL_DIR")
    confidence_dir = _configured_directory("DIFFDOCK_CONFIDENCE_MODEL_DIR")
    return bool(
        model_dir
        and (model_dir / "best_ema_inference_epoch_model.pt").is_file()
        and confidence_dir
        and (confidence_dir / "best_model_epoch75.pt").is_file()
    )


def check_diffdock_available() -> dict[str, Any]:
    """Check if DiffDock is available via CLI or Docker."""
    result: dict[str, Any] = {
        "available": False,
        "mode": None,
        "version": None,
        "docker_image": None,
        "runtime_available": False,
        "model_configured": _diffdock_models_configured(),
        "gpu_available": False,
        "warning": None,
    }

    local_probe = _run_probe([sys.executable, "-m", "diffdock", "--help"])
    if local_probe is not None and local_probe.returncode == 0:
        result["runtime_available"] = True
        result["mode"] = "python_package"
        result["version"] = "source"
        result["model_configured"] = _diffdock_models_configured()
        result["available"] = result["model_configured"]
        if not result["model_configured"]:
            result["warning"] = "diffdock_model_not_configured"
        return result

    image = _first_existing_docker_image(
        [os.environ.get("DIFFDOCK_IMAGE", "diffdock:latest"), "diffdock:latest"]
    )
    if image is None:
        return result

    result["mode"] = "docker"
    result["docker_image"] = image
    runtime_probe = _run_probe(
        [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "python",
            image,
            "/app/diffdock/inference.py",
            "--help",
        ],
        timeout=30,
    )
    result["runtime_available"] = bool(runtime_probe and runtime_probe.returncode == 0)
    if not result["runtime_available"]:
        result["warning"] = "diffdock_runtime_probe_failed"
        return result

    model_probe = _run_probe(
        [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "python",
            image,
            "-c",
            (
                "from pathlib import Path; "
                "root=Path('/app/diffdock'); "
                "files=[*root.rglob('*.pt'),*root.rglob('*.ckpt'),*root.rglob('*.pth')]; "
                "raise SystemExit(0 if files else 2)"
            ),
        ],
        timeout=20,
    )
    result["model_configured"] = _diffdock_models_configured() or bool(
        model_probe and model_probe.returncode == 0
    )
    result["gpu_available"] = _check_gpu_available(image)
    result["available"] = result["runtime_available"] and result["model_configured"]
    if not result["model_configured"]:
        result["warning"] = "diffdock_model_not_configured"

    return result


def check_gnina_available() -> dict[str, Any]:
    result: dict[str, Any] = {
        "available": False,
        "mode": None,
        "version": None,
        "path": None,
        "docker_image": None,
        "runtime_available": False,
        "gpu_available": False,
        "warning": None,
    }
    path = shutil.which("gnina")
    if path is not None:
        probe = _run_probe([path, "--version"])
        if probe is not None and probe.returncode == 0:
            return {
                **result,
                "available": True,
                "runtime_available": True,
                "mode": "local_cli",
                "path": path,
                "version": _probe_version(probe),
            }

    docker_image = _first_existing_docker_image(
        [
            os.environ.get("GNINA_IMAGE", "gnina/gnina:latest"),
            "gnina/gnina:latest",
            "gnina/gnina:1.0.3",
            "gnina:latest",
        ]
    )
    if docker_image is not None:
        probe = _run_probe(
            ["docker", "run", "--rm", docker_image, "gnina", "--version"],
            timeout=20,
        )
        if probe is not None and probe.returncode == 0:
            return {
                **result,
                "available": True,
                "runtime_available": True,
                "mode": "docker",
                "docker_image": docker_image,
                "version": _probe_version(probe),
                "gpu_available": _check_gpu_available(docker_image),
            }
        return {
            **result,
            "mode": "docker",
            "docker_image": docker_image,
            "warning": "gnina_runtime_probe_failed",
        }
    return result


def check_vina_available() -> dict[str, Any]:
    result: dict[str, Any] = {
        "available": False,
        "mode": None,
        "version": None,
        "path": None,
        "docker_image": None,
        "runtime_available": False,
        "warning": None,
    }
    for command in ["vina", "autodock_vina", "vina_1_1_2"]:
        path = shutil.which(command)
        if path is not None:
            probe = _run_probe([path, "--version"])
            if probe is not None and probe.returncode == 0:
                return {
                    **result,
                    "available": True,
                    "runtime_available": True,
                    "mode": "local_cli",
                    "path": path,
                    "version": _probe_version(probe),
                }

    docker_image = _first_existing_docker_image(["vina:latest"])
    if docker_image is not None:
        probe = _run_probe(
            [
                "docker",
                "run",
                "--rm",
                "--entrypoint",
                "python",
                docker_image,
                "-c",
                "from vina import Vina; print('vina-python-ok')",
            ],
            timeout=20,
        )
        if probe is not None and probe.returncode == 0:
            return {
                **result,
                "available": True,
                "runtime_available": True,
                "mode": "docker",
                "docker_image": docker_image,
                "version": _probe_version(probe),
            }
        return {
            **result,
            "mode": "docker",
            "docker_image": docker_image,
            "warning": "vina_runtime_probe_failed",
        }
    return result


def parse_gnina_output(stdout: str) -> dict[str, Any]:
    affinity = _valid_affinity(_find_named_float(stdout, "Affinity"))
    cnn_score = _valid_cnn_score(_find_named_float(stdout, "CNNscore"))
    cnn_affinity = _valid_affinity(_find_named_float(stdout, "CNNaffinity"))
    mode_values = _mode_values(stdout)
    if affinity is None or cnn_score is None or cnn_affinity is None:
        table_values = mode_values[0] if mode_values else None
        if table_values:
            affinity = affinity if affinity is not None else table_values.get("affinity")
            cnn_score = cnn_score if cnn_score is not None else table_values.get("cnn_score")
            cnn_affinity = (
                cnn_affinity if cnn_affinity is not None else table_values.get("cnn_affinity")
            )
    selected = affinity is not None or cnn_score is not None or cnn_affinity is not None
    return {
        "vina_score": _rounded(affinity),
        "cnn_score": _rounded(cnn_score),
        "cnn_affinity": _rounded(cnn_affinity),
        "selected_pose_rank": 1 if selected else None,
        "pose_count": len(mode_values) if mode_values else (1 if selected else None),
        "pose_selection_method": "gnina_output_mode_1" if selected else None,
        "best_pose_confirmed": selected,
    }


def parse_vina_output(stdout: str) -> dict[str, Any]:
    mode_values = _mode_values(stdout)
    remark_score = _find_remark_vina_score(stdout)
    if remark_score is not None:
        vina_score = _rounded(_valid_affinity(remark_score))
    else:
        table_values = mode_values[0] if mode_values else None
        vina_score = _rounded(table_values.get("affinity")) if table_values else None
    return {
        "vina_score": vina_score,
        "selected_pose_rank": 1 if vina_score is not None else None,
        "pose_count": len(mode_values) if mode_values else (1 if vina_score is not None else None),
        "pose_selection_method": "vina_lowest_affinity_mode_1" if vina_score is not None else None,
        "best_pose_confirmed": vina_score is not None,
    }


def _run_command(command: list[str], timeout_seconds: int) -> tuple[int | None, str, str, float]:
    started = time.perf_counter()
    container_name = _extract_container_name(command)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        runtime_seconds = time.perf_counter() - started
        # Clean up Docker container if timeout occurred
        if container_name:
            _cleanup_docker_container(container_name)
        return None, exc.stdout or "", exc.stderr or "docking_tool_timeout", runtime_seconds
    except OSError as exc:
        runtime_seconds = time.perf_counter() - started
        return None, "", str(exc), runtime_seconds
    runtime_seconds = time.perf_counter() - started
    return completed.returncode, completed.stdout or "", completed.stderr or "", runtime_seconds


def _vina_docker_python_script(
    receptor_path: str,
    ligand_path: str,
    pose_path: str,
    request: DockingToolRequest,
) -> str:
    assert request.grid_center is not None
    assert request.grid_size is not None
    center = [float(value) for value in request.grid_center]
    box_size = [float(value) for value in request.grid_size]
    return "\n".join(
        [
            "from vina import Vina",
            "v = Vina(sf_name='vina')",
            f"v.set_receptor({receptor_path!r})",
            f"v.set_ligand_from_file({ligand_path!r})",
            f"v.compute_vina_maps(center={center!r}, box_size={box_size!r})",
            f"v.dock(exhaustiveness={int(request.exhaustiveness)}, n_poses=9)",
            "energies = v.energies(n_poses=1)",
            "score = float(energies[0][0])",
            f"v.write_poses({pose_path!r}, n_poses=1, overwrite=True)",
            "print(f'REMARK VINA RESULT: {score:.3f} 0.000 0.000')",
        ]
    )


def _grid_args(request: DockingToolRequest) -> list[str]:
    if not _is_vector3(request.grid_center) or not _is_vector3(request.grid_size):
        return []
    assert request.grid_center is not None
    assert request.grid_size is not None
    return [
        "--center_x",
        str(float(request.grid_center[0])),
        "--center_y",
        str(float(request.grid_center[1])),
        "--center_z",
        str(float(request.grid_center[2])),
        "--size_x",
        str(float(request.grid_size[0])),
        "--size_y",
        str(float(request.grid_size[1])),
        "--size_z",
        str(float(request.grid_size[2])),
    ]


def _mode_values(stdout: str) -> list[dict[str, float]]:
    row_pattern = re.compile(
        rf"^\s*(\d{{1,3}})\s+\|?\s*({_FLOAT_PATTERN})"
        rf"(?:\s+\|?\s*({_FLOAT_PATTERN}))?"
        rf"(?:\s+\|?\s*({_FLOAT_PATTERN}))?"
        rf"(?:\s+\|?\s*({_FLOAT_PATTERN}))?"
    )
    results: list[dict[str, float]] = []
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("-") or stripped.lower().startswith("mode"):
            continue
        match = row_pattern.match(stripped)
        if not match:
            continue
        mode = int(match.group(1))
        affinity = _valid_affinity(float(match.group(2)))
        if mode <= 0 or mode > 100 or affinity is None:
            continue
        result = {"affinity": affinity}
        cnn_score_value = match.group(4) if match.group(5) is not None else match.group(3)
        cnn_affinity_value = match.group(5) if match.group(5) is not None else match.group(4)
        if cnn_score_value is not None:
            cnn_score = _valid_cnn_score(float(cnn_score_value))
            if cnn_score is not None:
                result["cnn_score"] = cnn_score
        if cnn_affinity_value is not None:
            cnn_affinity = _valid_affinity(float(cnn_affinity_value))
            if cnn_affinity is not None:
                result["cnn_affinity"] = cnn_affinity
        result["rank"] = float(mode)
        results.append(result)
    return results


def _find_named_float(stdout: str, label: str) -> float | None:
    pattern = re.compile(
        rf"(?<![A-Za-z]){re.escape(label)}(?![A-Za-z])\s*[:=]\s*({_FLOAT_PATTERN})",
        re.IGNORECASE,
    )
    match = pattern.search(stdout)
    return float(match.group(1)) if match else None


def _find_remark_vina_score(stdout: str) -> float | None:
    pattern = re.compile(rf"REMARK\s+VINA\s+RESULT:\s*({_FLOAT_PATTERN})", re.IGNORECASE)
    match = pattern.search(stdout)
    return float(match.group(1)) if match else None


def _valid_affinity(value: float | None) -> float | None:
    if value is None:
        return None
    return value if -50.0 <= value <= 50.0 else None


def _valid_cnn_score(value: float | None) -> float | None:
    if value is None:
        return None
    return value if 0.0 <= value <= 1.0 else None


def _tool_warnings(
    exit_code: int | None,
    vina_score: float | None,
    stderr: str,
) -> list[str]:
    warnings: list[str] = []
    error_text = stderr.lower()
    if exit_code is None:
        warnings.append("external_docking_timeout")
    elif exit_code != 0:
        warnings.append("external_docking_tool_failed")
    if "pdbqt parsing error" in error_text and (
        "rigid receptor" in error_text or "> root" in error_text
    ):
        warnings.append("external_docking_invalid_receptor_pdbqt")
    elif "pdbqt parsing error" in error_text and "ligand" in error_text:
        warnings.append("external_docking_invalid_ligand_pdbqt")
    if any(
        marker in error_text
        for marker in [
            "could not select device driver",
            "nvidia-container-cli",
            "no cuda-capable device",
            "cuda driver version is insufficient",
        ]
    ):
        warnings.append("external_docking_gpu_unavailable")
    if "out of memory" in error_text or "cuda error: out of memory" in error_text:
        warnings.append("external_docking_out_of_memory")
    if "no such file or directory" in error_text or "file not found" in error_text:
        warnings.append("external_docking_input_file_not_found")
    if vina_score is None:
        warnings.append("external_docking_score_not_found")
    if stderr and "docking_tool_timeout" not in stderr:
        warnings.append("external_docking_stderr_present")
    return warnings


def pose_artifact_available(pose_file: str | None) -> bool:
    if not pose_file:
        return False
    path = Path(pose_file)
    return path.is_file() and path.stat().st_size > 0


def pose_coordinates_from_file(
    pose_file: str | None,
    *,
    max_atoms: int = 120,
) -> dict[str, Any] | None:
    if not pose_artifact_available(pose_file):
        return None

    assert pose_file is not None
    path = Path(pose_file)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    parsed = _parse_v2000_pose_atoms(text, max_atoms=max_atoms)
    pose_format = "sdf"
    if parsed is None and path.suffix.lower() in {".pdb", ".pdbqt"}:
        parsed = _parse_pdb_pose_atoms(text, max_atoms=max_atoms)
        pose_format = path.suffix.lower().lstrip(".")
    if parsed is None and path.suffix.lower() == ".xyz":
        parsed = _parse_xyz_pose_atoms(text, max_atoms=max_atoms)
        pose_format = "xyz"
    if parsed is None:
        return None

    atom_count, atoms = parsed
    return {
        "format": pose_format,
        "atom_count": atom_count,
        "returned_atom_count": len(atoms),
        "truncated": atom_count > len(atoms),
        "atoms": atoms,
    }


def _parse_v2000_pose_atoms(
    text: str,
    *,
    max_atoms: int,
) -> tuple[int, list[dict[str, Any]]] | None:
    lines = text.splitlines()
    counts_index: int | None = None
    atom_count: int | None = None
    for index, line in enumerate(lines):
        parts = line.split()
        if len(parts) < 2 or "V2000" not in line.upper():
            continue
        try:
            atom_count = int(parts[0])
        except ValueError:
            continue
        counts_index = index
        break

    if counts_index is None or atom_count is None or atom_count <= 0:
        return None

    atoms: list[dict[str, Any]] = []
    for offset, line in enumerate(lines[counts_index + 1 : counts_index + 1 + atom_count], start=1):
        if len(atoms) >= max_atoms:
            break
        parts = line.split()
        if len(parts) < 4:
            return None
        try:
            x, y, z = (round(float(parts[i]), 4) for i in range(3))
        except ValueError:
            return None
        atoms.append({"index": offset, "element": parts[3], "x": x, "y": y, "z": z})

    return (atom_count, atoms) if atoms else None


def _parse_pdb_pose_atoms(
    text: str,
    *,
    max_atoms: int,
) -> tuple[int, list[dict[str, Any]]] | None:
    atom_lines = [
        line for line in text.splitlines() if line.startswith(("ATOM  ", "HETATM"))
    ]
    atoms: list[dict[str, Any]] = []
    for line in atom_lines[:max_atoms]:
        try:
            x = round(float(line[30:38]), 4)
            y = round(float(line[38:46]), 4)
            z = round(float(line[46:54]), 4)
        except ValueError:
            return None
        element = line[76:78].strip() or line[12:16].strip().lstrip("0123456789")[:2]
        atoms.append(
            {
                "index": len(atoms) + 1,
                "element": element or "X",
                "x": x,
                "y": y,
                "z": z,
            }
        )
    return (len(atom_lines), atoms) if atoms else None


def _parse_xyz_pose_atoms(
    text: str,
    *,
    max_atoms: int,
) -> tuple[int, list[dict[str, Any]]] | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return None
    try:
        atom_count = int(lines[0])
    except ValueError:
        return None

    atoms: list[dict[str, Any]] = []
    for offset, line in enumerate(lines[2 : 2 + atom_count], start=1):
        if len(atoms) >= max_atoms:
            break
        parts = line.split()
        if len(parts) < 4:
            return None
        try:
            x, y, z = (round(float(parts[i]), 4) for i in range(1, 4))
        except ValueError:
            return None
        atoms.append({"index": offset, "element": parts[0], "x": x, "y": y, "z": z})
    return (atom_count, atoms) if atoms else None


def _result_labels(tool_name: str, success: bool) -> list[str]:
    if success:
        return ["external_docking_adapter_used", f"{tool_name}_adapter"]
    return ["external_docking_adapter_failed", f"{tool_name}_adapter"]


def _has_receptor_ligand_pair(request: DockingToolRequest) -> bool:
    return bool(request.receptor_file and request.ligand_file)


def _has_vina_prepared_pair(request: DockingToolRequest) -> bool:
    return bool(
        _has_receptor_ligand_pair(request)
        and request.receptor_file.lower().endswith(".pdbqt")
        and request.ligand_file.lower().endswith(".pdbqt")
    )


def _first_existing_docker_image(images: list[str | None]) -> str | None:
    for image in dict.fromkeys(image for image in images if image):
        try:
            proc = subprocess.run(
                ["docker", "image", "inspect", image],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if proc.returncode == 0:
                return image
        except subprocess.TimeoutExpired:
            continue
        except FileNotFoundError:
            # Docker not found, bail out
            return None
    return None


def _is_vector3(values: list[float] | None) -> bool:
    return values is not None and len(values) == 3


def _safe_pose_prefix(molecule_id: str | None) -> str:
    prefix = molecule_id or "ligand"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", prefix).strip("._") or "ligand"


def _rounded(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 3)


def _combined_output(stdout: str, stderr: str) -> str:
    return "\n".join(part for part in [stdout, stderr] if part)


def _run_probe(command: list[str], timeout: int = 10):
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def _probe_version(probe) -> str:
    output = _combined_output(probe.stdout or "", probe.stderr or "").strip()
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    for line in lines:
        if re.search(r"\b(?:gnina|vina)\b", line, re.IGNORECASE):
            return line
    return lines[0] if lines else "unknown"


def _extract_container_name(command: list[str]) -> str | None:
    """Extract container name from Docker command if present."""
    try:
        if "docker" in command and "run" in command:
            # Look for --name flag
            if "--name" in command:
                name_index = command.index("--name")
                if name_index + 1 < len(command):
                    return command[name_index + 1]
    except (ValueError, IndexError):
        pass
    return None


def _cleanup_docker_container(container_name: str) -> None:
    """Force remove a Docker container."""
    try:
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        # Best effort cleanup, don't fail if it doesn't work
        pass


def _check_gpu_available(docker_image: str | None = None) -> bool:
    """Check if NVIDIA GPU is available for Docker."""
    image = docker_image or os.environ.get("GNINA_IMAGE", "gnina/gnina:latest")
    try:
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--gpus",
                "all",
                "--entrypoint",
                "nvidia-smi",
                image,
                "-L",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False
