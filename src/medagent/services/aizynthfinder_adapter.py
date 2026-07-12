"""AiZynthFinder adapter status, execution, and safe fallback helpers."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from importlib import metadata, util
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AiZynthFinderRequest:
    smiles: str
    output_dir: str
    config_file: str | None = None
    max_steps: int = 6
    docker_image: str = "aizynthfinder:latest"
    timeout_seconds: int = 900


@dataclass
class AiZynthFinderResult:
    adapter_mode: str
    tool_name: str
    success: bool
    route_found: bool = False
    num_steps: int | None = None
    route_score: float | None = None
    route_summary: str | None = None
    labels: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    runtime_seconds: float = 0.0


def check_aizynthfinder_available() -> dict[str, Any]:
    result: dict[str, Any] = {
        "available": False,
        "mode": None,
        "version": None,
        "path": None,
        "docker_image": None,
        "model_configured": False,
    }

    package_status = _python_package_status()
    if package_status is not None:
        return {**result, **package_status}

    cli_status = _cli_status()
    if cli_status is not None:
        return {**result, **cli_status}

    docker_status = _docker_status()
    if docker_status is not None:
        return {**result, **docker_status}

    return result


def aizynthfinder_tool_status() -> dict[str, Any]:
    status = check_aizynthfinder_available()
    return {
        "available": status["available"],
        "mode": status.get("mode"),
        "version": status.get("version"),
        "path": status.get("path"),
        "docker_image": status.get("docker_image"),
        "model_configured": status.get("model_configured", False),
    }


def run_aizynthfinder_retrosynthesis(
    request: AiZynthFinderRequest,
    status: dict[str, Any] | None = None,
) -> AiZynthFinderResult:
    start_time = time.monotonic()
    status = status or check_aizynthfinder_available()

    if not status.get("available"):
        return AiZynthFinderResult(
            adapter_mode="aizynthfinder_unavailable",
            tool_name="aizynthfinder",
            success=False,
            warnings=["aizynthfinder_not_installed"],
            runtime_seconds=time.monotonic() - start_time,
        )

    config_file = _resolve_config_file(request.config_file)
    if config_file is None:
        return AiZynthFinderResult(
            adapter_mode="aizynthfinder_model_not_configured",
            tool_name="aizynthfinder",
            success=False,
            warnings=["aizynthfinder_config_not_configured"],
            runtime_seconds=time.monotonic() - start_time,
        )
    if not config_file.is_file():
        return AiZynthFinderResult(
            adapter_mode="aizynthfinder_config_missing",
            tool_name="aizynthfinder",
            success=False,
            warnings=["aizynthfinder_config_missing"],
            runtime_seconds=time.monotonic() - start_time,
        )
    if config_file.stat().st_size == 0:
        return AiZynthFinderResult(
            adapter_mode="aizynthfinder_config_empty",
            tool_name="aizynthfinder",
            success=False,
            warnings=["aizynthfinder_config_empty"],
            runtime_seconds=time.monotonic() - start_time,
        )

    mode = status.get("mode")
    if mode == "docker":
        return _run_aizynthfinder_docker(request, status, config_file, start_time)
    if mode in {"local_cli", "python_package"}:
        return _run_aizynthfinder_local(request, status, config_file, start_time)

    return AiZynthFinderResult(
        adapter_mode="aizynthfinder_mode_unsupported",
        tool_name="aizynthfinder",
        success=False,
        warnings=[f"aizynthfinder_mode_unsupported:{mode}"],
        runtime_seconds=time.monotonic() - start_time,
    )


def _python_package_status() -> dict[str, Any] | None:
    if util.find_spec("aizynthfinder") is None:
        return None

    try:
        version = metadata.version("aizynthfinder")
    except metadata.PackageNotFoundError:
        version = "unknown"

    return {
        "available": True,
        "mode": "python_package",
        "version": version,
        "path": None,
        "model_configured": _default_config_available(),
    }


def _cli_status() -> dict[str, Any] | None:
    for command in ["aizynthcli", "aizynthapp"]:
        path = shutil.which(command)
        if path is not None:
            return {
                "available": True,
                "mode": "local_cli",
                "version": "unknown",
                "path": path,
                "model_configured": _default_config_available(),
            }
    return None


def _docker_status() -> dict[str, Any] | None:
    for image in ["aizynthfinder:latest", "molecularai/aizynthfinder:latest"]:
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
            return {
                "available": True,
                "mode": "docker",
                "docker_image": image,
                "model_configured": _default_config_available(),
            }
    return None


def _default_config_path() -> Path | None:
    env_path = os.environ.get("AIZYNTHFINDER_CONFIG") or os.environ.get(
        "MEDAGENT_AIZYNTHFINDER_CONFIG"
    )
    if not env_path:
        return None
    return Path(env_path).expanduser().resolve()


def _default_config_available() -> bool:
    path = _default_config_path()
    return bool(path and _config_file_ready(path))


def _config_file_ready(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _resolve_config_file(config_file: str | None) -> Path | None:
    if config_file:
        return Path(config_file).expanduser().resolve()
    return _default_config_path()


def _run_aizynthfinder_local(
    request: AiZynthFinderRequest,
    status: dict[str, Any],
    config_file: Path,
    start_time: float,
) -> AiZynthFinderResult:
    output_dir = Path(request.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "aizynthfinder_routes.json"
    _remove_stale_output(output_file)

    with tempfile.TemporaryDirectory(prefix="aizynthfinder_") as tmp_dir:
        smiles_file = Path(tmp_dir) / "targets.smi"
        _write_smiles_input(smiles_file, request.smiles)
        command = _build_aizynthfinder_local_command(
            status=status,
            config_file=config_file,
            smiles_file=smiles_file,
            output_file=output_file,
        )
        adapter_mode = (
            "aizynthfinder_python_package"
            if status.get("mode") == "python_package"
            else "aizynthfinder_local"
        )
        return _run_command(
            command=command,
            adapter_mode=adapter_mode,
            start_time=start_time,
            timeout_seconds=request.timeout_seconds,
            output_file=output_file,
            max_steps=request.max_steps,
            cwd=config_file.parent,
        )


def _run_aizynthfinder_docker(
    request: AiZynthFinderRequest,
    status: dict[str, Any],
    config_file: Path,
    start_time: float,
) -> AiZynthFinderResult:
    output_dir = Path(request.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "aizynthfinder_routes.json"
    _remove_stale_output(output_file)

    with tempfile.TemporaryDirectory(prefix="aizynthfinder_") as tmp_dir:
        smiles_file = Path(tmp_dir) / "targets.smi"
        _write_smiles_input(smiles_file, request.smiles)
        command = _build_aizynthfinder_docker_command(
            request=request,
            status=status,
            config_file=config_file,
            smiles_file=smiles_file,
            output_dir=output_dir,
        )
        return _run_command(
            command=command,
            adapter_mode="aizynthfinder_docker",
            start_time=start_time,
            timeout_seconds=request.timeout_seconds,
            output_file=output_file,
            max_steps=request.max_steps,
        )


def _write_smiles_input(path: Path, smiles: str) -> None:
    path.write_text(smiles.strip() + "\n", encoding="utf-8")


def _remove_stale_output(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _build_aizynthfinder_local_command(
    status: dict[str, Any],
    config_file: Path,
    smiles_file: Path,
    output_file: Path,
) -> list[str]:
    if status.get("mode") == "python_package":
        executable = [sys.executable, "-m", "aizynthfinder.interfaces.aizynthcli"]
    else:
        executable = [status.get("path") or "aizynthcli"]

    return executable + [
        "--config",
        str(config_file),
        "--smiles",
        str(smiles_file),
        "--output",
        str(output_file),
    ]


def _build_aizynthfinder_docker_command(
    request: AiZynthFinderRequest,
    status: dict[str, Any],
    config_file: Path,
    smiles_file: Path,
    output_dir: Path,
) -> list[str]:
    image = status.get("docker_image") or request.docker_image
    command = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{smiles_file.parent.resolve()}:/data/input:ro",
        "-v",
        f"{output_dir.resolve()}:/data/output",
        "-v",
        f"{config_file.parent.resolve()}:/data/config:ro",
    ]
    data_dir = _resolve_data_dir(config_file)
    if data_dir is not None:
        command += ["-v", f"{data_dir}:/data/aizynthfinder:ro"]

    command += [
        "-w",
        "/data/config",
        "--entrypoint",
        "aizynthcli",
        image,
        "--config",
        f"/data/config/{config_file.name}",
        "--smiles",
        f"/data/input/{smiles_file.name}",
        "--output",
        "/data/output/aizynthfinder_routes.json",
    ]
    return command


def _resolve_data_dir(config_file: Path) -> Path | None:
    env_path = os.environ.get("AIZYNTHFINDER_DATA_DIR") or os.environ.get(
        "MEDAGENT_AIZYNTHFINDER_DATA_DIR"
    )
    candidates = []
    if env_path:
        candidates.append(Path(env_path).expanduser().resolve())
    candidates.append(config_file.parent.resolve())
    repo_data_dir = Path.cwd().resolve() / "data" / "aizynthfinder"
    candidates.append(repo_data_dir)

    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def _run_command(
    command: list[str],
    adapter_mode: str,
    start_time: float,
    timeout_seconds: int,
    output_file: Path,
    max_steps: int,
    cwd: Path | None = None,
) -> AiZynthFinderResult:
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=str(cwd) if cwd else None,
        )
    except subprocess.TimeoutExpired:
        return AiZynthFinderResult(
            adapter_mode=f"{adapter_mode}_timeout",
            tool_name="aizynthfinder",
            success=False,
            warnings=["aizynthfinder_timeout"],
            exit_code=-1,
            runtime_seconds=time.monotonic() - start_time,
        )
    except FileNotFoundError:
        return AiZynthFinderResult(
            adapter_mode="aizynthfinder_not_found",
            tool_name="aizynthfinder",
            success=False,
            warnings=["aizynthfinder_binary_not_found"],
            exit_code=-1,
            runtime_seconds=time.monotonic() - start_time,
        )

    execution_ok = proc.returncode == 0
    parsed = _parse_aizynthfinder_output(output_file, max_steps) if execution_ok else {}
    warnings = list(parsed.get("warnings", []))
    if not execution_ok:
        warnings.append("aizynthfinder_execution_failed")
    elif not output_file.exists() and "aizynthfinder_output_missing" not in warnings:
        warnings.append("aizynthfinder_output_missing")

    output_parsed = bool(parsed.get("parsed", False))
    success = execution_ok and output_parsed
    route_found = bool(parsed.get("route_found", False))
    labels = ["aizynthfinder_executed"]
    if route_found:
        labels.append("aizynthfinder_route")

    return AiZynthFinderResult(
        adapter_mode=adapter_mode,
        tool_name="aizynthfinder",
        success=success,
        route_found=route_found,
        num_steps=parsed.get("num_steps"),
        route_score=parsed.get("route_score"),
        route_summary=parsed.get("route_summary"),
        labels=labels if success else [],
        warnings=warnings,
        stdout=proc.stdout[:2000],
        stderr=proc.stderr[:2000],
        exit_code=proc.returncode,
        runtime_seconds=time.monotonic() - start_time,
    )


def _parse_aizynthfinder_output(output_file: Path, max_steps: int) -> dict[str, Any]:
    if not output_file.exists():
        return {"parsed": False, "warnings": ["aizynthfinder_output_missing"]}

    try:
        payload = json.loads(output_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"parsed": False, "warnings": ["aizynthfinder_output_parse_failed"]}

    record = _extract_first_record(payload)
    if record is None:
        return {"parsed": False, "warnings": ["aizynthfinder_output_empty"]}

    is_solved = _coerce_bool(record.get("is_solved"))
    solved_routes = _coerce_int(record.get("number_of_solved_routes"))
    if solved_routes is not None and solved_routes > 0:
        is_solved = True

    num_steps = _coerce_int(record.get("number_of_steps"))
    route_score = _coerce_float(record.get("top_score"))

    warnings: list[str] = []
    route_found = is_solved
    if is_solved and num_steps is not None and num_steps > max_steps:
        route_found = False
        warnings.append("aizynthfinder_route_exceeds_max_steps")

    if route_found:
        route_summary = _route_found_summary(num_steps, route_score)
    elif is_solved:
        route_summary = (
            f"AiZynthFinder found a route, but it exceeds max_steps={max_steps}."
        )
    else:
        route_summary = "AiZynthFinder completed, but no solved route was found."

    return {
        "parsed": True,
        "route_found": route_found,
        "num_steps": num_steps,
        "route_score": route_score,
        "route_summary": route_summary,
        "warnings": warnings,
    }


def _extract_first_record(payload: Any) -> dict[str, Any] | None:
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list) and data:
            first = data[0]
            return first if isinstance(first, dict) else None
        if "is_solved" in payload or "number_of_solved_routes" in payload:
            return payload
    return None


def _route_found_summary(num_steps: int | None, route_score: float | None) -> str:
    if num_steps is not None and route_score is not None:
        return f"AiZynthFinder found a route in {num_steps} steps; top score={route_score:.3g}."
    if num_steps is not None:
        return f"AiZynthFinder found a route in {num_steps} steps."
    if route_score is not None:
        return f"AiZynthFinder found a route; top score={route_score:.3g}."
    return "AiZynthFinder found a retrosynthesis route."


def _coerce_int(value: Any) -> int | None:
    value = _first_scalar(value)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    value = _first_scalar(value)
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_bool(value: Any) -> bool:
    value = _first_scalar(value)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "solved"}
    return bool(value)


def _first_scalar(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value
