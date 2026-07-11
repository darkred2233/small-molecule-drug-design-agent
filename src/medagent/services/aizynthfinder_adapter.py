"""AiZynthFinder adapter status and safe fallback helpers."""

import os
import shutil
import subprocess
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

    if not request.config_file:
        return AiZynthFinderResult(
            adapter_mode="aizynthfinder_model_not_configured",
            tool_name="aizynthfinder",
            success=False,
            warnings=["aizynthfinder_config_not_configured"],
            runtime_seconds=time.monotonic() - start_time,
        )

    if status.get("mode") == "docker":
        return _run_aizynthfinder_docker(request, status, start_time)
    return _run_aizynthfinder_cli(request, status, start_time)


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


def _default_config_available() -> bool:
    env_path = os.environ.get("AIZYNTHFINDER_CONFIG") or os.environ.get(
        "MEDAGENT_AIZYNTHFINDER_CONFIG"
    )
    return bool(env_path and Path(env_path).exists())


def _run_aizynthfinder_cli(
    request: AiZynthFinderRequest,
    status: dict[str, Any],
    start_time: float,
) -> AiZynthFinderResult:
    output_dir = Path(request.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "aizynthfinder_routes.json"
    command = [
        status.get("path") or "aizynthcli",
        "--config",
        str(request.config_file),
        "--smiles",
        request.smiles,
        "--output",
        str(output_file),
    ]
    return _run_command(command, "aizynthfinder_local", start_time, request.timeout_seconds)


def _run_aizynthfinder_docker(
    request: AiZynthFinderRequest,
    status: dict[str, Any],
    start_time: float,
) -> AiZynthFinderResult:
    output_dir = Path(request.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    config_file = Path(request.config_file or "").resolve()
    command = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{output_dir}:/data/output",
        "-v",
        f"{config_file}:/data/config.yml",
        status.get("docker_image") or request.docker_image,
        "aizynthcli",
        "--config",
        "/data/config.yml",
        "--smiles",
        request.smiles,
        "--output",
        "/data/output/aizynthfinder_routes.json",
    ]
    return _run_command(command, "aizynthfinder_docker", start_time, request.timeout_seconds)


def _run_command(
    command: list[str],
    adapter_mode: str,
    start_time: float,
    timeout_seconds: int,
) -> AiZynthFinderResult:
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
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

    success = proc.returncode == 0
    return AiZynthFinderResult(
        adapter_mode=adapter_mode,
        tool_name="aizynthfinder",
        success=success,
        route_found=success,
        labels=["aizynthfinder_route"] if success else [],
        warnings=[] if success else ["aizynthfinder_execution_failed"],
        stdout=proc.stdout[:2000],
        stderr=proc.stderr[:2000],
        exit_code=proc.returncode,
        runtime_seconds=time.monotonic() - start_time,
    )

