import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


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
    pose_file: str | None = None
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
        executable = str(tool_status["gnina"].get("path") or "gnina")
        return run_gnina_docking(executable, request)
    if selected_tool == "vina":
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
    if tool_status.get("vina", {}).get("available") and _has_receptor_ligand_pair(request):
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


def run_gnina_docking(executable: str, request: DockingToolRequest) -> DockingToolResult:
    Path(request.output_dir).mkdir(parents=True, exist_ok=True)
    command, pose_file = build_gnina_command(executable, request)
    exit_code, stdout, stderr, runtime_seconds = _run_command(command, request.timeout_seconds)
    parsed = parse_gnina_output(stdout)
    success = exit_code == 0 and parsed["vina_score"] is not None
    warnings = _tool_warnings(exit_code, parsed["vina_score"], stderr)
    return DockingToolResult(
        adapter_mode="gnina_external_docking",
        tool_name="gnina",
        success=success,
        vina_score=parsed["vina_score"],
        cnn_score=parsed["cnn_score"],
        cnn_affinity=parsed["cnn_affinity"],
        pose_file=pose_file if success else None,
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
    parsed = parse_vina_output(stdout)
    success = exit_code == 0 and parsed["vina_score"] is not None
    warnings = _tool_warnings(exit_code, parsed["vina_score"], stderr)
    return DockingToolResult(
        adapter_mode="vina_external_docking",
        tool_name="vina",
        success=success,
        vina_score=parsed["vina_score"],
        pose_file=pose_file if success else None,
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
        "--ligand_path", request.ligand_file,
        "--output_dir", str(output_dir),
    ]

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
        cnn_score=parsed.get("confidence_score"),
        pose_file=parsed.get("pose_file") if success else None,
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

    # Create temp directories for Docker mounts
    import tempfile
    with tempfile.TemporaryDirectory(prefix="diffdock_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        protein_link = tmp_path / "protein.pdb"
        ligand_link = tmp_path / "ligand.sdf"
        out_dir = tmp_path / "output"

        # Create symlinks or copy files
        import shutil
        shutil.copy2(request.receptor_file, protein_link)
        shutil.copy2(request.ligand_file, ligand_link)
        out_dir.mkdir()

        command = [
            "docker", "run", "--rm",
            "-v", f"{tmp_path}:/data",
            docker_image,
            "python", "-m", "diffdock",
            "--protein_path", "/data/protein.pdb",
            "--ligand_path", "/data/ligand.sdf",
            "--output_dir", "/data/output",
        ]

        if request.molecule_id:
            command.extend(["--complex_id", request.molecule_id])

        exit_code, stdout, stderr, runtime_seconds = _run_command(command, request.timeout_seconds)

        # Copy results back
        if out_dir.exists():
            for f in out_dir.glob("*"):
                shutil.copy2(f, output_dir / f.name)

        parsed = parse_diffdock_output(stdout, output_dir, request.molecule_id)
        success = exit_code == 0 and parsed.get("confidence_score") is not None

        warnings = []
        if exit_code != 0:
            warnings.append("diffdock_docker_failed")
        if not parsed.get("confidence_score"):
            warnings.append("diffdock_confidence_not_found")

        return DockingToolResult(
            adapter_mode="diffdock_docker_docking",
            tool_name="diffdock",
            success=success,
            vina_score=parsed.get("vina_score"),
            cnn_score=parsed.get("confidence_score"),
            pose_file=parsed.get("pose_file") if success else None,
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
    - confidence_score: 0-1, higher is better
    - pose file in SDF format
    """
    result: dict[str, Any] = {
        "confidence_score": None,
        "vina_score": None,
        "pose_file": None,
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

    # Find pose file
    prefix = _safe_pose_prefix(molecule_id)
    pose_candidates = list(Path(output_dir).glob(f"*{prefix}*rank1*.sdf"))
    if not pose_candidates:
        pose_candidates = list(Path(output_dir).glob(f"*{prefix}*.sdf"))
    if not pose_candidates:
        pose_candidates = list(Path(output_dir).glob("rank1*.sdf"))
    if pose_candidates:
        result["pose_file"] = str(pose_candidates[0])

    return result


def check_diffdock_available() -> dict[str, Any]:
    """Check if DiffDock is available via CLI or Docker."""
    result: dict[str, Any] = {
        "available": False,
        "mode": None,
        "version": None,
        "docker_image": None,
    }

    # Check local Python package
    try:
        import diffdock
        result["available"] = True
        result["mode"] = "python_package"
        result["version"] = getattr(diffdock, "__version__", "unknown")
        return result
    except ImportError:
        pass

    # Check Docker
    try:
        proc = subprocess.run(
            ["docker", "image", "inspect", "diffdock:latest"],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode == 0:
            result["available"] = True
            result["mode"] = "docker"
            result["docker_image"] = "diffdock:latest"
            return result
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return result


def parse_gnina_output(stdout: str) -> dict[str, float | None]:
    affinity = _find_named_float(stdout, "Affinity")
    cnn_score = _find_named_float(stdout, "CNNscore")
    cnn_affinity = _find_named_float(stdout, "CNNaffinity")
    if affinity is None or cnn_score is None or cnn_affinity is None:
        table_values = _first_mode_values(stdout)
        if table_values:
            affinity = affinity if affinity is not None else table_values.get("affinity")
            cnn_score = cnn_score if cnn_score is not None else table_values.get("cnn_score")
            cnn_affinity = (
                cnn_affinity if cnn_affinity is not None else table_values.get("cnn_affinity")
            )
    return {
        "vina_score": _rounded(affinity),
        "cnn_score": _rounded(cnn_score),
        "cnn_affinity": _rounded(cnn_affinity),
    }


def parse_vina_output(stdout: str) -> dict[str, float | None]:
    remark_score = _find_remark_vina_score(stdout)
    if remark_score is not None:
        return {"vina_score": _rounded(remark_score)}
    table_values = _first_mode_values(stdout)
    return {"vina_score": _rounded(table_values.get("affinity")) if table_values else None}


def _run_command(command: list[str], timeout_seconds: int) -> tuple[int | None, str, str, float]:
    started = time.perf_counter()
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
        return None, exc.stdout or "", exc.stderr or "docking_tool_timeout", runtime_seconds
    except OSError as exc:
        runtime_seconds = time.perf_counter() - started
        return None, "", str(exc), runtime_seconds
    runtime_seconds = time.perf_counter() - started
    return completed.returncode, completed.stdout or "", completed.stderr or "", runtime_seconds


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


def _first_mode_values(stdout: str) -> dict[str, float] | None:
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("-") or stripped.lower().startswith("mode"):
            continue
        values = [float(value) for value in re.findall(_FLOAT_PATTERN, stripped)]
        if len(values) >= 2 and int(values[0]) == values[0] and values[0] > 0:
            result = {"affinity": values[1]}
            if len(values) >= 3:
                result["cnn_score"] = values[2]
            if len(values) >= 4:
                result["cnn_affinity"] = values[3]
            return result
    return None


def _find_named_float(stdout: str, label: str) -> float | None:
    pattern = re.compile(rf"{re.escape(label)}\s*[:=]\s*({_FLOAT_PATTERN})", re.IGNORECASE)
    match = pattern.search(stdout)
    return float(match.group(1)) if match else None


def _find_remark_vina_score(stdout: str) -> float | None:
    pattern = re.compile(rf"REMARK\s+VINA\s+RESULT:\s*({_FLOAT_PATTERN})", re.IGNORECASE)
    match = pattern.search(stdout)
    return float(match.group(1)) if match else None


def _tool_warnings(
    exit_code: int | None,
    vina_score: float | None,
    stderr: str,
) -> list[str]:
    warnings: list[str] = []
    if exit_code != 0:
        warnings.append("external_docking_tool_failed")
    if vina_score is None:
        warnings.append("external_docking_score_not_found")
    if stderr:
        warnings.append("external_docking_stderr_present")
    return warnings


def _result_labels(tool_name: str, success: bool) -> list[str]:
    if success:
        return ["external_docking_adapter_used", f"{tool_name}_adapter"]
    return ["external_docking_adapter_failed", f"{tool_name}_adapter"]


def _has_receptor_ligand_pair(request: DockingToolRequest) -> bool:
    return bool(request.receptor_file and request.ligand_file)


def _is_vector3(values: list[float] | None) -> bool:
    return values is not None and len(values) == 3


def _safe_pose_prefix(molecule_id: str | None) -> str:
    prefix = molecule_id or "ligand"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", prefix).strip("._") or "ligand"


def _rounded(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 3)
