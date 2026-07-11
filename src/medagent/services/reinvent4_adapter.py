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
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


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
    }

    # Check local Python package
    try:
        import reinvent4
        result["available"] = True
        result["mode"] = "python_package"
        result["version"] = getattr(reinvent4, "__version__", "unknown")
        return result
    except ImportError:
        pass

    # Check CLI
    try:
        proc = subprocess.run(
            ["reinvent", "--version"],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode == 0:
            result["available"] = True
            result["mode"] = "local_cli"
            result["version"] = proc.stdout.strip()
            return result
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Check Docker
    for image in ["reinvent4:latest", "reinvent:latest"]:
        try:
            proc = subprocess.run(
                ["docker", "image", "inspect", image],
                capture_output=True, text=True, timeout=10,
            )
            if proc.returncode == 0:
                result["available"] = True
                result["mode"] = "docker"
                result["docker_image"] = image
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

    with tempfile.TemporaryDirectory(prefix="reinvent4_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        config_file = tmp_path / "config.toml"
        output_file = tmp_path / "output.csv"

        # Generate TOML config
        _write_reinvent4_config(config_file, request, output_file)

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

    with tempfile.TemporaryDirectory(prefix="reinvent4_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        config_file = tmp_path / "config.toml"
        output_file = tmp_path / "output.csv"

        # Generate TOML config
        _write_reinvent4_config(config_file, request, output_file)

        # Build Docker command
        cmd = [
            "docker", "run", "--rm",
            "-v", f"{tmp_path}:/data",
            docker_image,
            "reinvent", "/data/config.toml",
        ]

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
    output_path: Path,
) -> None:
    """Write REINVENT4 TOML configuration file."""
    # Basic REINVENT4 config
    config = f"""
[run_type]
name = "sampling"
json_out = "sampling.json"

[parameters]
summary_csv_file = "{output_path}"
num_smiles = {request.num_molecules}
unique_molecules = true
randomize_smiles = true
output_size = {request.num_molecules}

[diversity_filter]
name = "IdenticalMurckoScaffold"
bucket_size = 50
minscore = 0.0

[inception]
memory_size = 100
sample_size = 10

[scoring]
type = "{request.scoring_strategy}"
[[scoring.component]]
[scoring.component.custom_sum]
name = "custom_sum"
[[scoring.component.custom_sum.endpoint]]
name = "default"
weight = 1.0
transform.type = "reverse_sigmoid"
transform.high = -5.0
transform.low = -10.0
transform.k = 0.5
"""

    # Add seed SMILES as starting points
    if request.seed_smiles:
        config += "\n[reinforcement]\n"
        for i, smi in enumerate(request.seed_smiles[:5]):  # Limit to 5 seeds
            config += f'scaffold_smiles_{i} = "{smi}"\n'

    config_path.write_text(config)


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
    }
