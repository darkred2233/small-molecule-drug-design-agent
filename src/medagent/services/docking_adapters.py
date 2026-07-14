import os
import re
import shutil
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
) -> tuple[list[str], str]:
    receptor_file = Path(request.receptor_file).resolve()
    ligand_file = Path(request.ligand_file).resolve()
    output_dir = Path(request.output_dir).resolve()
    pose_file = output_dir / f"{_safe_pose_prefix(request.molecule_id)}_gnina_pose.sdf"
    command = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{receptor_file.parent}:/data/receptor:ro",
        "-v",
        f"{ligand_file.parent}:/data/ligand:ro",
        "-v",
        f"{output_dir}:/data/output",
        docker_image,
        "gnina",
        "-r",
        f"/data/receptor/{receptor_file.name}",
        "-l",
        f"/data/ligand/{ligand_file.name}",
        "-o",
        f"/data/output/{pose_file.name}",
        "--exhaustiveness",
        str(request.exhaustiveness),
    ]
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
) -> tuple[list[str], str]:
    receptor_file = Path(request.receptor_file).resolve()
    ligand_file = Path(request.ligand_file).resolve()
    output_dir = Path(request.output_dir).resolve()
    pose_file = output_dir / f"{_safe_pose_prefix(request.molecule_id)}_vina_pose.pdbqt"
    script = _vina_docker_python_script(
        receptor_path=f"/data/receptor/{receptor_file.name}",
        ligand_path=f"/data/ligand/{ligand_file.name}",
        pose_path=f"/data/output/{pose_file.name}",
        request=request,
    )
    command = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{receptor_file.parent}:/data/receptor:ro",
        "-v",
        f"{ligand_file.parent}:/data/ligand:ro",
        "-v",
        f"{output_dir}:/data/output",
        docker_image,
        "-c",
        script,
    ]
    return command, str(pose_file)


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


def run_gnina_docker_docking(
    request: DockingToolRequest,
    gnina_status: dict[str, Any],
) -> DockingToolResult:
    Path(request.output_dir).mkdir(parents=True, exist_ok=True)
    docker_image = gnina_status.get("docker_image") or "gnina/gnina:latest"
    command, pose_file = build_gnina_docker_command(docker_image, request)
    exit_code, stdout, stderr, runtime_seconds = _run_command(command, request.timeout_seconds)
    parsed = parse_gnina_output(stdout)
    success = exit_code == 0 and parsed["vina_score"] is not None
    warnings = _tool_warnings(exit_code, parsed["vina_score"], stderr)
    return DockingToolResult(
        adapter_mode="gnina_docker_docking",
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


def run_vina_docker_docking(
    request: DockingToolRequest,
    vina_status: dict[str, Any],
) -> DockingToolResult:
    Path(request.output_dir).mkdir(parents=True, exist_ok=True)
    docker_image = vina_status.get("docker_image") or "vina:latest"
    command, pose_file = build_vina_docker_command(docker_image, request)
    exit_code, stdout, stderr, runtime_seconds = _run_command(command, request.timeout_seconds)
    parsed = parse_vina_output(stdout)
    success = exit_code == 0 and parsed["vina_score"] is not None
    warnings = _tool_warnings(exit_code, parsed["vina_score"], stderr)
    return DockingToolResult(
        adapter_mode="vina_docker_docking",
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
            "--entrypoint", "python",
            docker_image,
            "-m", "diffdock",
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


def check_gnina_available() -> dict[str, Any]:
    result: dict[str, Any] = {
        "available": False,
        "mode": None,
        "version": None,
        "path": None,
        "docker_image": None,
    }
    path = shutil.which("gnina")
    if path is not None:
        return {**result, "available": True, "mode": "local_cli", "path": path}

    docker_image = _first_existing_docker_image(
        [
            os.environ.get("GNINA_IMAGE", "gnina/gnina:latest"),
            "gnina/gnina:latest",
            "gnina/gnina:1.0.3",
            "gnina:latest",
        ]
    )
    if docker_image is not None:
        return {**result, "available": True, "mode": "docker", "docker_image": docker_image}
    return result


def check_vina_available() -> dict[str, Any]:
    result: dict[str, Any] = {
        "available": False,
        "mode": None,
        "version": None,
        "path": None,
        "docker_image": None,
    }
    for command in ["vina", "autodock_vina", "vina_1_1_2"]:
        path = shutil.which(command)
        if path is not None:
            return {**result, "available": True, "mode": "local_cli", "path": path}

    docker_image = _first_existing_docker_image(["vina:latest"])
    if docker_image is not None:
        return {**result, "available": True, "mode": "docker", "docker_image": docker_image}
    return result


def parse_gnina_output(stdout: str) -> dict[str, float | None]:
    affinity = _valid_affinity(_find_named_float(stdout, "Affinity"))
    cnn_score = _valid_cnn_score(_find_named_float(stdout, "CNNscore"))
    cnn_affinity = _valid_affinity(_find_named_float(stdout, "CNNaffinity"))
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
        return {"vina_score": _rounded(_valid_affinity(remark_score))}
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


def _first_mode_values(stdout: str) -> dict[str, float] | None:
    row_pattern = re.compile(
        rf"^\s*(\d{{1,3}})\s+\|?\s*({_FLOAT_PATTERN})"
        rf"(?:\s+\|?\s*({_FLOAT_PATTERN}))?"
        rf"(?:\s+\|?\s*({_FLOAT_PATTERN}))?"
    )
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
        if match.group(3) is not None:
            cnn_score = _valid_cnn_score(float(match.group(3)))
            if cnn_score is not None:
                result["cnn_score"] = cnn_score
        if match.group(4) is not None:
            cnn_affinity = _valid_affinity(float(match.group(4)))
            if cnn_affinity is not None:
                result["cnn_affinity"] = cnn_affinity
        return result
    return None


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
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None
        if proc.returncode == 0:
            return image
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
