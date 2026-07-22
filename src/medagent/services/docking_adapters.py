"""Local GNINA and AutoDock Vina adapters.

Docking is intentionally limited to host executables.  A successful result
requires both a parsed score and a non-empty pose artifact, so a command that
only prints a score is never represented as an evaluated pose.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from medagent.services.tool_config import get_tool_runtime_config, resolve_configured_path


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
    # Nullable legacy compatibility field. New docking code never writes it.
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
    provenance: dict[str, Any] = field(default_factory=dict)


def run_external_docking(
    request: DockingToolRequest, tool_status: dict[str, Any]
) -> DockingToolResult | None:
    selected_tool = select_docking_tool(request, tool_status)
    validation_warnings = validate_docking_request(request, selected_tool)
    if validation_warnings:
        return DockingToolResult(
            adapter_mode="external_docking_unavailable",
            tool_name="external_docking",
            success=False,
            labels=["external_docking_adapter_failed"],
            warnings=validation_warnings,
        )
    if selected_tool == "gnina":
        return run_gnina_docking(str(tool_status["gnina"].get("path") or "gnina"), request)
    if selected_tool == "vina":
        return run_vina_docking(str(tool_status["vina"].get("path") or "vina"), request)
    return None


def select_docking_tool(request: DockingToolRequest, tool_status: dict[str, Any]) -> str | None:
    has_grid = _is_vector3(request.grid_center) and _is_vector3(request.grid_size)
    if tool_status.get("gnina", {}).get("available") and has_grid:
        return "gnina"
    if (
        tool_status.get("vina", {}).get("available")
        and has_grid
        and _has_vina_prepared_pair(request)
    ):
        return "vina"
    return None


def validate_docking_request(
    request: DockingToolRequest, selected_tool: str | None = None
) -> list[str]:
    warnings: list[str] = []
    if not Path(request.receptor_file).is_file():
        warnings.append("receptor_file_not_found")
    if not Path(request.ligand_file).is_file():
        warnings.append("ligand_file_not_found")
    if selected_tool in {None, "gnina", "vina"} and (
        not _is_vector3(request.grid_center) or not _is_vector3(request.grid_size)
    ):
        warnings.append("grid_center_and_grid_size_required_for_external_docking")
    if selected_tool == "vina" and not _has_vina_prepared_pair(request):
        warnings.append("vina_requires_prepared_pdbqt_inputs")
    return warnings


def build_gnina_command(executable: str, request: DockingToolRequest) -> tuple[list[str], str]:
    pose_file = str(Path(request.output_dir) / f"{_safe_pose_prefix(request.molecule_id)}_gnina_pose.sdf")
    command = [
        executable, "-r", request.receptor_file, "-l", request.ligand_file, "-o", pose_file,
        "--exhaustiveness", str(request.exhaustiveness), *_grid_args(request),
    ]
    return command, pose_file


def build_vina_command(executable: str, request: DockingToolRequest) -> tuple[list[str], str]:
    pose_file = str(Path(request.output_dir) / f"{_safe_pose_prefix(request.molecule_id)}_vina_pose.pdbqt")
    command = [
        executable, "--receptor", request.receptor_file, "--ligand", request.ligand_file,
        "--out", pose_file, "--exhaustiveness", str(request.exhaustiveness), *_grid_args(request),
    ]
    return command, pose_file


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
        adapter_mode="gnina_local_docking", tool_name="gnina", success=success,
        vina_score=parsed["vina_score"], cnn_score=parsed["cnn_score"],
        cnn_affinity=parsed["cnn_affinity"], pose_file=pose_file if success else None,
        selected_pose_rank=parsed["selected_pose_rank"], pose_count=parsed["pose_count"],
        pose_selection_method=parsed["pose_selection_method"],
        best_pose_confirmed=bool(parsed["best_pose_confirmed"] and pose_exists),
        labels=_result_labels("gnina", success), warnings=warnings, stdout=stdout, stderr=stderr,
        exit_code=exit_code, runtime_seconds=runtime_seconds, command=command,
        provenance=_docking_provenance(request, "local_cli", executable),
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
        adapter_mode="vina_local_docking", tool_name="vina", success=success,
        vina_score=parsed["vina_score"], pose_file=pose_file if success else None,
        selected_pose_rank=parsed["selected_pose_rank"], pose_count=parsed["pose_count"],
        pose_selection_method=parsed["pose_selection_method"],
        best_pose_confirmed=bool(parsed["best_pose_confirmed"] and pose_exists),
        labels=_result_labels("vina", success), warnings=warnings, stdout=stdout, stderr=stderr,
        exit_code=exit_code, runtime_seconds=runtime_seconds, command=command,
        provenance=_docking_provenance(request, "local_cli", executable),
    )


def check_gnina_available() -> dict[str, Any]:
    return _check_local_cli("gnina", default_command="gnina", timeout_seconds=300)


def check_vina_available() -> dict[str, Any]:
    return _check_local_cli("vina", default_command="vina", timeout_seconds=300)


def _check_local_cli(name: str, *, default_command: str, timeout_seconds: int) -> dict[str, Any]:
    config = get_tool_runtime_config(
        name, default_command=default_command, default_timeout_seconds=timeout_seconds
    )
    executable = _find_local_executable(config.command)
    result: dict[str, Any] = {
        "available": False, "runtime_available": False, "mode": "local_cli", "path": executable,
        "version": None, "gpu_available": _local_gpu_available() if name == "gnina" else False,
        "warning": None, **config.as_status(),
    }
    if executable is None:
        result["warning"] = f"{name}_local_executable_not_found"
        return result
    try:
        probe = subprocess.run(
            [executable, "--version"], capture_output=True, text=True, timeout=15, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        result["warning"] = f"{name}_local_runtime_probe_failed"
        return result
    version = (probe.stdout or probe.stderr or "").strip().splitlines()
    result["version"] = version[0] if version else None
    result["runtime_available"] = probe.returncode == 0
    result["available"] = probe.returncode == 0
    if not result["available"]:
        result["warning"] = f"{name}_local_runtime_probe_failed"
    return result


def parse_gnina_output(stdout: str) -> dict[str, Any]:
    affinity = _valid_affinity(_find_named_float(stdout, "Affinity"))
    cnn_score = _valid_cnn_score(_find_named_float(stdout, "CNNscore"))
    cnn_affinity = _valid_affinity(_find_named_float(stdout, "CNNaffinity"))
    rows = _mode_values(stdout)
    if rows:
        row = rows[0]
        affinity = affinity if affinity is not None else row.get("affinity")
        cnn_score = cnn_score if cnn_score is not None else row.get("cnn_score")
        cnn_affinity = cnn_affinity if cnn_affinity is not None else row.get("cnn_affinity")
    selected = any(value is not None for value in (affinity, cnn_score, cnn_affinity))
    return {
        "vina_score": _rounded(affinity), "cnn_score": _rounded(cnn_score),
        "cnn_affinity": _rounded(cnn_affinity), "selected_pose_rank": 1 if selected else None,
        "pose_count": len(rows) if rows else (1 if selected else None),
        "pose_selection_method": "gnina_output_mode_1" if selected else None,
        "best_pose_confirmed": selected,
    }


def parse_vina_output(stdout: str) -> dict[str, Any]:
    rows = _mode_values(stdout)
    score = _valid_affinity(_find_remark_vina_score(stdout))
    if score is None and rows:
        score = rows[0].get("affinity")
    score = _rounded(score)
    return {
        "vina_score": score, "selected_pose_rank": 1 if score is not None else None,
        "pose_count": len(rows) if rows else (1 if score is not None else None),
        "pose_selection_method": "vina_lowest_affinity_mode_1" if score is not None else None,
        "best_pose_confirmed": score is not None,
    }


def pose_artifact_available(pose_file: str | None) -> bool:
    if not pose_file:
        return False
    path = Path(pose_file)
    return path.is_file() and path.stat().st_size > 0


def pose_coordinates_from_file(pose_file: str | None, *, max_atoms: int = 120) -> dict[str, Any] | None:
    if not pose_artifact_available(pose_file):
        return None
    path = Path(str(pose_file))
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    parsed = _parse_v2000_pose_atoms(text, max_atoms)
    pose_format = "sdf"
    if parsed is None and path.suffix.lower() in {".pdb", ".pdbqt"}:
        parsed, pose_format = _parse_pdb_pose_atoms(text, max_atoms), path.suffix.lower().lstrip(".")
    if parsed is None:
        return None
    atom_count, atoms = parsed
    return {"format": pose_format, "atom_count": atom_count, "returned_atom_count": len(atoms), "truncated": atom_count > len(atoms), "atoms": atoms}


def _run_command(command: list[str], timeout_seconds: int) -> tuple[int | None, str, str, float]:
    started = time.perf_counter()
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout_seconds, check=False)
    except subprocess.TimeoutExpired as exc:
        return None, _text(exc.stdout), _text(exc.stderr) or "docking_tool_timeout", time.perf_counter() - started
    except OSError as exc:
        return None, "", str(exc), time.perf_counter() - started
    return completed.returncode, completed.stdout or "", completed.stderr or "", time.perf_counter() - started


def _grid_args(request: DockingToolRequest) -> list[str]:
    if not _is_vector3(request.grid_center) or not _is_vector3(request.grid_size):
        return []
    assert request.grid_center is not None and request.grid_size is not None
    return [
        "--center_x", str(float(request.grid_center[0])), "--center_y", str(float(request.grid_center[1])),
        "--center_z", str(float(request.grid_center[2])), "--size_x", str(float(request.grid_size[0])),
        "--size_y", str(float(request.grid_size[1])), "--size_z", str(float(request.grid_size[2])),
    ]


def _mode_values(stdout: str) -> list[dict[str, float]]:
    row_pattern = re.compile(
        rf"^\s*(\d{{1,3}})\s+\|?\s*({_FLOAT_PATTERN})(?:\s+\|?\s*({_FLOAT_PATTERN}))?(?:\s+\|?\s*({_FLOAT_PATTERN}))?(?:\s+\|?\s*({_FLOAT_PATTERN}))?"
    )
    values: list[dict[str, float]] = []
    for line in stdout.splitlines():
        match = row_pattern.match(line.strip())
        if not match:
            continue
        rank, affinity = int(match.group(1)), _valid_affinity(float(match.group(2)))
        if not 0 < rank <= 100 or affinity is None:
            continue
        row: dict[str, float] = {"affinity": affinity, "rank": float(rank)}
        cnn_score_raw = match.group(4) if match.group(5) is not None else match.group(3)
        cnn_affinity_raw = match.group(5) if match.group(5) is not None else match.group(4)
        if cnn_score_raw is not None:
            score = _valid_cnn_score(float(cnn_score_raw))
            if score is not None:
                row["cnn_score"] = score
        if cnn_affinity_raw is not None:
            cnn_affinity = _valid_affinity(float(cnn_affinity_raw))
            if cnn_affinity is not None:
                row["cnn_affinity"] = cnn_affinity
        values.append(row)
    return values


def _tool_warnings(exit_code: int | None, vina_score: float | None, stderr: str) -> list[str]:
    warnings: list[str] = []
    text = stderr.lower()
    if exit_code is None:
        warnings.append("external_docking_timeout")
    elif exit_code != 0:
        warnings.append("external_docking_tool_failed")
    if "pdbqt parsing error" in text and ("rigid receptor" in text or "> root" in text):
        warnings.append("external_docking_invalid_receptor_pdbqt")
    elif "pdbqt parsing error" in text and "ligand" in text:
        warnings.append("external_docking_invalid_ligand_pdbqt")
    if "out of memory" in text:
        warnings.append("external_docking_out_of_memory")
    if "file not found" in text or "no such file or directory" in text:
        warnings.append("external_docking_input_file_not_found")
    if vina_score is None:
        warnings.append("external_docking_score_not_found")
    if stderr and "docking_tool_timeout" not in text:
        warnings.append("external_docking_stderr_present")
    return warnings


def _parse_v2000_pose_atoms(text: str, max_atoms: int) -> tuple[int, list[dict[str, Any]]] | None:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        parts = line.split()
        if len(parts) < 2 or "V2000" not in line.upper():
            continue
        try:
            atom_count = int(parts[0])
        except ValueError:
            continue
        atoms: list[dict[str, Any]] = []
        for position, atom_line in enumerate(lines[index + 1 : index + 1 + atom_count], start=1):
            fields = atom_line.split()
            if len(fields) < 4:
                return None
            try:
                x, y, z = (round(float(fields[item]), 4) for item in range(3))
            except ValueError:
                return None
            if len(atoms) < max_atoms:
                atoms.append({"index": position, "element": fields[3], "x": x, "y": y, "z": z})
        return (atom_count, atoms) if atoms else None
    return None


def _parse_pdb_pose_atoms(text: str, max_atoms: int) -> tuple[int, list[dict[str, Any]]] | None:
    source = [line for line in text.splitlines() if line.startswith(("ATOM  ", "HETATM"))]
    if not source:
        return None
    atoms: list[dict[str, Any]] = []
    for index, line in enumerate(source[:max_atoms], start=1):
        try:
            x, y, z = (round(float(line[start:end]), 4) for start, end in ((30, 38), (38, 46), (46, 54)))
        except ValueError:
            continue
        element = line[76:78].strip() or re.sub(r"[^A-Za-z]", "", line[12:16]).title()[:2]
        atoms.append({"index": index, "element": element or "?", "x": x, "y": y, "z": z})
    return (len(source), atoms) if atoms else None


def _find_local_executable(command: str | None) -> str | None:
    if not command:
        return None
    configured = resolve_configured_path(command)
    if configured is not None and configured.is_file():
        return str(configured)
    found = shutil.which(command)
    return found or None


def _local_gpu_available() -> bool:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        return False
    try:
        return subprocess.run([executable, "-L"], capture_output=True, text=True, timeout=5, check=False).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _docking_provenance(request: DockingToolRequest, execution_mode: str, executable: str) -> dict[str, Any]:
    return {"execution_mode": execution_mode, "executable": executable, "receptor_file": request.receptor_file, "ligand_file": request.ligand_file, "grid_center": request.grid_center, "grid_size": request.grid_size, "exhaustiveness": request.exhaustiveness}


def _result_labels(tool_name: str, success: bool) -> list[str]:
    return [f"{tool_name}_local_executed", "external_docking_pose_confirmed"] if success else ["external_docking_adapter_failed"]


def _find_named_float(text: str, label: str) -> float | None:
    match = re.search(rf"(?<![A-Za-z]){re.escape(label)}(?![A-Za-z])\s*[:=]\s*({_FLOAT_PATTERN})", text, re.IGNORECASE)
    return float(match.group(1)) if match else None


def _find_remark_vina_score(text: str) -> float | None:
    match = re.search(rf"REMARK\s+VINA\s+RESULT:\s*({_FLOAT_PATTERN})", text, re.IGNORECASE)
    return float(match.group(1)) if match else None


def _valid_affinity(value: float | None) -> float | None:
    return value if value is not None and -50.0 <= value <= 50.0 else None


def _valid_cnn_score(value: float | None) -> float | None:
    return value if value is not None and 0.0 <= value <= 1.0 else None


def _rounded(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None


def _is_vector3(values: list[float] | None) -> bool:
    return values is not None and len(values) == 3


def _has_vina_prepared_pair(request: DockingToolRequest) -> bool:
    return Path(request.receptor_file).suffix.lower() == ".pdbqt" and Path(request.ligand_file).suffix.lower() == ".pdbqt"


def _safe_pose_prefix(molecule_id: str | None) -> str:
    raw = molecule_id or "ligand"
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._")
    return safe or "ligand"


def _combined_output(stdout: str, stderr: str) -> str:
    return "\n".join(part for part in (stdout, stderr) if part)


def _text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return str(value or "")
