"""REINVENT4 adapter for molecular generation.

REINVENT4 is a molecular generation tool that uses reinforcement learning
to optimize molecules against multiple objectives.

Supports:
- Local installation (pip install reinvent4)
- Docker container execution
- TOML configuration-based generation

Reference: https://github.com/MolecularAI/REINVENT4
"""

import csv
import importlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from medagent.core.config import get_settings
from medagent.services.docker_runtime import DockerMountBuilder, docker_temporary_directory


# ---------------------------------------------------------------------------
# Data contracts
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Reinvent4Request:
    seed_smiles: list[str]
    output_dir: str
    num_molecules: int = 100
    scoring_strategy: str = "simple"  # simple, multi_parameter, scaffold_hop
    constraints: dict[str, Any] = field(default_factory=dict)
    prior_file: str | None = None
    docker_image: str = "reinvent4:latest"
    use_docker: bool = False
    timeout_seconds: int = 600


@dataclass
class Reinvent4Result:
    adapter_mode: str
    tool_name: str
    success: bool
    generated_smiles: list[str] = field(default_factory=list)
    scores: list[float] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    runtime_seconds: float = 0.0


# ---------------------------------------------------------------------------
# REINVENT4 availability check
# ---------------------------------------------------------------------------

def check_reinvent4_available() -> dict[str, Any]:
    """Check if REINVENT4 is available."""
    result: dict[str, Any] = {
        "available": False,
        "mode": None,
        "version": None,
        "path": None,
        "docker_image": None,
        "runtime_available": False,
        "model_configured": False,
        "prior_file": None,
        "gpu_available": False,
        "warning": None,
    }
    prior_file = _resolve_prior_file()
    result["model_configured"] = prior_file is not None
    result["prior_file"] = str(prior_file) if prior_file else None

    path = shutil.which("reinvent")
    if path:
        proc = subprocess.run(
            [path, "--help"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if proc.returncode == 0:
            result["runtime_available"] = True
            result["available"] = result["model_configured"]
            result["mode"] = "local_cli"
            result["path"] = path
            result["version"] = _reinvent_version()
            if not result["model_configured"]:
                result["warning"] = "reinvent4_prior_not_configured"
            return result

    for image in ["reinvent4:latest", "reinvent:latest"]:
        try:
            proc = subprocess.run(
                ["docker", "image", "inspect", image],
                capture_output=True, text=True, timeout=10,
            )
            if proc.returncode == 0:
                result["mode"] = "docker"
                result["docker_image"] = image
                runtime_probe = subprocess.run(
                    ["docker", "run", "--rm", image, "--help"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                result["runtime_available"] = runtime_probe.returncode == 0
                result["gpu_available"] = _check_gpu_available(image)
                result["available"] = (
                    result["runtime_available"] and result["model_configured"]
                )
                if not result["runtime_available"]:
                    result["warning"] = "reinvent4_runtime_probe_failed"
                elif not result["model_configured"]:
                    result["warning"] = "reinvent4_prior_not_configured"
                return result
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    return result


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_reinvent4_generation(
    request: Reinvent4Request,
    reinvent4_status: dict[str, Any] | None = None,
) -> Reinvent4Result:
    """Run REINVENT4 molecular generation."""
    if reinvent4_status is None:
        reinvent4_status = check_reinvent4_available()

    if not reinvent4_status.get("available"):
        if reinvent4_status.get("runtime_available") and not reinvent4_status.get(
            "model_configured"
        ):
            return Reinvent4Result(
                adapter_mode="reinvent4_model_not_configured",
                tool_name="reinvent4",
                success=False,
                warnings=[
                    "reinvent4_prior_not_configured",
                    "set_REINVENT4_PRIOR_FILE_or_request_prior_file",
                ],
            )
        return Reinvent4Result(
            adapter_mode="reinvent4_unavailable",
            tool_name="reinvent4",
            success=False,
            warnings=["reinvent4_not_installed"],
        )

    mode = reinvent4_status.get("mode")

    if mode == "docker":
        return _run_reinvent4_docker(request, reinvent4_status.get("docker_image", "reinvent4:latest"))
    else:
        return _run_reinvent4_local(request)


# ---------------------------------------------------------------------------
# Local execution
# ---------------------------------------------------------------------------

def _run_reinvent4_local(request: Reinvent4Request) -> Reinvent4Result:
    """Run REINVENT4 via local CLI."""
    start_time = time.monotonic()
    prior_file = _resolve_prior_file(request.prior_file)
    if prior_file is None:
        return Reinvent4Result(
            adapter_mode="reinvent4_model_not_configured",
            tool_name="reinvent4",
            success=False,
            warnings=["reinvent4_prior_not_configured"],
        )

    with tempfile.TemporaryDirectory(prefix="reinvent4_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        config_file = tmp_path / "config.toml"
        output_file = tmp_path / "output.csv"

        # Generate TOML config
        _write_reinvent4_config(
            config_file,
            request,
            output_file,
            model_file=str(prior_file),
            device="cpu",
        )

        # Build command
        cmd = ["reinvent", str(config_file)]

        # Run REINVENT4
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=request.timeout_seconds,
                cwd=str(tmp_path),
            )
            exit_code = proc.returncode
            stdout = proc.stdout
            stderr = proc.stderr
        except subprocess.TimeoutExpired:
            return Reinvent4Result(
                adapter_mode="reinvent4_timeout",
                tool_name="reinvent4",
                success=False,
                warnings=["reinvent4_execution_timeout"],
                exit_code=-1,
                runtime_seconds=time.monotonic() - start_time,
            )
        except FileNotFoundError:
            return Reinvent4Result(
                adapter_mode="reinvent4_not_found",
                tool_name="reinvent4",
                success=False,
                warnings=["reinvent4_binary_not_found"],
                exit_code=-1,
                runtime_seconds=time.monotonic() - start_time,
            )

        # Parse output
        generated_smiles, scores = _parse_reinvent4_output(output_file)

        # Copy output to request output_dir
        output_dir = Path(request.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        if output_file.exists():
            import shutil
            shutil.copy2(output_file, output_dir / "reinvent4_output.csv")

        return Reinvent4Result(
            adapter_mode="reinvent4_local",
            tool_name="reinvent4",
            success=exit_code == 0 and len(generated_smiles) > 0,
            generated_smiles=generated_smiles,
            scores=scores,
            labels=["reinvent4_generated", "reinvent4_local"],
            warnings=[] if exit_code == 0 else ["reinvent4_execution_failed"],
            stdout=stdout[:2000],
            stderr=stderr[:2000],
            exit_code=exit_code,
            runtime_seconds=time.monotonic() - start_time,
        )


# ---------------------------------------------------------------------------
# Docker execution
# ---------------------------------------------------------------------------

def _run_reinvent4_docker(request: Reinvent4Request, docker_image: str) -> Reinvent4Result:
    """Run REINVENT4 via Docker container."""
    import shutil

    start_time = time.monotonic()
    prior_file = _resolve_prior_file(request.prior_file)
    if prior_file is None:
        return Reinvent4Result(
            adapter_mode="reinvent4_model_not_configured",
            tool_name="reinvent4",
            success=False,
            warnings=["reinvent4_prior_not_configured"],
        )

    with docker_temporary_directory(prefix="reinvent4_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        config_file = tmp_path / "config.toml"
        output_file = tmp_path / "output.csv"

        # Generate TOML config
        use_gpu = _check_gpu_available(docker_image)
        mounts = DockerMountBuilder()
        data_path = mounts.bind(tmp_path, "/data")
        prior_path = mounts.bind(prior_file, "/data/model.prior", read_only=True)
        _write_reinvent4_config(
            config_file,
            request,
            PurePosixPath(data_path, "output.csv"),
            model_file=prior_path,
            device="cuda:0" if use_gpu else "cpu",
        )

        # Build Docker command
        cmd = _build_reinvent4_docker_command(
            docker_image=docker_image,
            data_dir=tmp_path,
            prior_file=prior_file,
            use_gpu=use_gpu,
            mounts=mounts,
            data_path=data_path,
            prior_path=prior_path,
        )

        # Run Docker
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=request.timeout_seconds,
            )
            exit_code = proc.returncode
            stdout = proc.stdout
            stderr = proc.stderr
        except subprocess.TimeoutExpired:
            return Reinvent4Result(
                adapter_mode="reinvent4_docker_timeout",
                tool_name="reinvent4",
                success=False,
                warnings=["reinvent4_docker_timeout"],
                exit_code=-1,
                runtime_seconds=time.monotonic() - start_time,
            )
        except FileNotFoundError:
            return Reinvent4Result(
                adapter_mode="docker_not_found",
                tool_name="reinvent4",
                success=False,
                warnings=["docker_not_installed"],
                exit_code=-1,
                runtime_seconds=time.monotonic() - start_time,
            )

        # Parse output
        generated_smiles, scores = _parse_reinvent4_output(output_file)

        # Copy output to request output_dir
        output_dir = Path(request.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        if output_file.exists():
            shutil.copy2(output_file, output_dir / "reinvent4_output.csv")

        return Reinvent4Result(
            adapter_mode="reinvent4_docker",
            tool_name="reinvent4",
            success=exit_code == 0 and len(generated_smiles) > 0,
            generated_smiles=generated_smiles,
            scores=scores,
            labels=["reinvent4_generated", "reinvent4_docker"],
            warnings=[] if exit_code == 0 else ["reinvent4_docker_failed"],
            stdout=stdout[:2000],
            stderr=stderr[:2000],
            exit_code=exit_code,
            runtime_seconds=time.monotonic() - start_time,
        )


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _write_reinvent4_config(
    config_path: Path,
    request: Reinvent4Request,
    output_path: Path | PurePosixPath,
    *,
    model_file: str,
    device: str,
) -> None:
    """Write REINVENT4 TOML configuration file."""
    config = "\n".join(
        [
            'run_type = "sampling"',
            f"device = {json.dumps(device)}",
            'json_out_config = "/data/sampling.json"'
            if str(output_path).startswith("/data/")
            else f"json_out_config = {json.dumps(str(output_path.with_suffix('.json')))}",
            "",
            "[parameters]",
            f"model_file = {json.dumps(model_file)}",
            f"output_file = {json.dumps(str(output_path))}",
            f"num_smiles = {int(request.num_molecules)}",
            "unique_molecules = true",
            "randomize_smiles = true",
            "",
        ]
    )
    config_path.write_text(config, encoding="utf-8")


def _build_reinvent4_docker_command(
    *,
    docker_image: str,
    data_dir: Path,
    prior_file: Path,
    use_gpu: bool,
    mounts: DockerMountBuilder | None = None,
    data_path: str | None = None,
    prior_path: str | None = None,
) -> list[str]:
    mounts = mounts or DockerMountBuilder()
    data_path = data_path or mounts.bind(data_dir.resolve(), "/data")
    if prior_path is None:
        mounts.bind(prior_file.resolve(), "/data/model.prior", read_only=True)
    command = ["docker", "run", "--rm"]
    if use_gpu:
        command.extend(["--gpus", "all"])
    command.extend(
        [
            *mounts.arguments,
            "-w",
            data_path,
            docker_image,
            str(PurePosixPath(data_path, "config.toml")),
        ]
    )
    return command


def _resolve_prior_file(value: str | None = None) -> Path | None:
    configured = value or os.environ.get("REINVENT4_PRIOR_FILE")
    if not configured:
        configured = get_settings().reinvent4_prior_file
    if not configured:
        return None
    path = Path(configured).expanduser().resolve()
    try:
        return path if path.is_file() and path.stat().st_size > 0 else None
    except OSError:
        return None


def _reinvent_version() -> str:
    for package_name in ["reinvent4", "reinvent"]:
        try:
            package = importlib.import_module(package_name)
            return str(getattr(package, "__version__", "unknown"))
        except ImportError:
            continue
    return "unknown"


def _check_gpu_available(docker_image: str) -> bool:
    try:
        proc = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--gpus",
                "all",
                "--entrypoint",
                "nvidia-smi",
                docker_image,
                "-L",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return proc.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _parse_reinvent4_output(
    output_path: Path,
) -> tuple[list[str], list[float]]:
    """Parse REINVENT4 output CSV."""
    smiles_list: list[str] = []
    scores: list[float] = []

    if not output_path.exists():
        return smiles_list, scores

    try:
        with open(output_path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                smi = row.get("SMILES") or row.get("smiles") or row.get("Smiles")
                score = row.get("score") or row.get("Score") or row.get("total_score")
                if smi:
                    smiles_list.append(smi)
                    if score:
                        try:
                            scores.append(float(score))
                        except ValueError:
                            scores.append(0.0)
                    else:
                        scores.append(0.0)
    except Exception:
        pass

    return smiles_list, scores


# ---------------------------------------------------------------------------
# Adapter status for tool detection
# ---------------------------------------------------------------------------

def reinvent4_tool_status() -> dict[str, Any]:
    """Get REINVENT4 tool status."""
    status = check_reinvent4_available()
    return {
        "available": status["available"],
        "mode": status.get("mode"),
        "version": status.get("version"),
        "docker_image": status.get("docker_image"),
        "runtime_available": status.get("runtime_available", False),
        "model_configured": status.get("model_configured", False),
        "prior_file": status.get("prior_file"),
        "gpu_available": status.get("gpu_available", False),
        "warning": status.get("warning"),
    }
