"""AutoGrow4 adapter for molecular generation.

AutoGrow4 is a genetic algorithm-based molecular generation tool that
optimizes molecules using docking-guided evolution.

Supports:
- Local installation (pip install autogrow4)
- Docker container execution

Reference: https://github.com/jones-lab/autogrow4
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
class AutoGrow4Request:
    seed_smiles: list[str]
    receptor_file: str
    output_dir: str
    num_generations: int = 10
    population_size: int = 50
    optimization_mode: str = "mcts"  # mcts, genetic
    constraints: dict[str, Any] = field(default_factory=dict)
    docker_image: str = "autogrow4:latest"
    use_docker: bool = False
    timeout_seconds: int = 1200


@dataclass
class AutoGrow4Result:
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
# AutoGrow4 availability check
# ---------------------------------------------------------------------------

def check_autogrow4_available() -> dict[str, Any]:
    """Check if AutoGrow4 is available."""
    result: dict[str, Any] = {
        "available": False,
        "mode": None,
        "version": None,
        "docker_image": None,
    }

    # Check local Python package
    try:
        import autogrow4
        result["available"] = True
        result["mode"] = "python_package"
        result["version"] = getattr(autogrow4, "__version__", "unknown")
        return result
    except ImportError:
        pass

    # Check Docker
    for image in ["autogrow4:latest", "autogrow:latest"]:
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

def run_autogrow4_generation(
    request: AutoGrow4Request,
    autogrow4_status: dict[str, Any] | None = None,
) -> AutoGrow4Result:
    """Run AutoGrow4 molecular generation."""
    if autogrow4_status is None:
        autogrow4_status = check_autogrow4_available()

    if not autogrow4_status.get("available"):
        return AutoGrow4Result(
            adapter_mode="autogrow4_unavailable",
            tool_name="autogrow4",
            success=False,
            warnings=["autogrow4_not_installed"],
        )

    mode = autogrow4_status.get("mode")

    if mode == "docker":
        return _run_autogrow4_docker(request, autogrow4_status.get("docker_image", "autogrow4:latest"))
    else:
        return _run_autogrow4_local(request)


# ---------------------------------------------------------------------------
# Local execution
# ---------------------------------------------------------------------------

def _run_autogrow4_local(request: AutoGrow4Request) -> AutoGrow4Result:
    """Run AutoGrow4 via local CLI."""
    import shutil

    start_time = time.monotonic()

    with tempfile.TemporaryDirectory(prefix="autogrow4_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        seeds_file = tmp_path / "seeds.smi"
        output_dir = tmp_path / "output"

        # Write seed SMILES
        _write_seed_smiles(seeds_file, request.seed_smiles)
        output_dir.mkdir()

        # Build command
        cmd = [
            "python", "-m", "autogrow4",
            "--receptor", request.receptor_file,
            "--seed_ligands", str(seeds_file),
            "--output_dir", str(output_dir),
            "--num_generations", str(request.num_generations),
            "--population_size", str(request.population_size),
            "--optimization_mode", request.optimization_mode,
        ]

        # Run AutoGrow4
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
            return AutoGrow4Result(
                adapter_mode="autogrow4_timeout",
                tool_name="autogrow4",
                success=False,
                warnings=["autogrow4_execution_timeout"],
                exit_code=-1,
                runtime_seconds=time.monotonic() - start_time,
            )
        except FileNotFoundError:
            return AutoGrow4Result(
                adapter_mode="autogrow4_not_found",
                tool_name="autogrow4",
                success=False,
                warnings=["autogrow4_binary_not_found"],
                exit_code=-1,
                runtime_seconds=time.monotonic() - start_time,
            )

        # Parse output
        generated_smiles, scores = _parse_autogrow4_output(output_dir)

        # Copy output to request output_dir
        final_output_dir = Path(request.output_dir)
        final_output_dir.mkdir(parents=True, exist_ok=True)
        if output_dir.exists():
            for f in output_dir.glob("*.sdf"):
                shutil.copy2(f, final_output_dir / f.name)
            for f in output_dir.glob("*.csv"):
                shutil.copy2(f, final_output_dir / f.name)

        return AutoGrow4Result(
            adapter_mode="autogrow4_local",
            tool_name="autogrow4",
            success=exit_code == 0 and len(generated_smiles) > 0,
            generated_smiles=generated_smiles,
            scores=scores,
            labels=["autogrow4_generated", "autogrow4_local"],
            warnings=[] if exit_code == 0 else ["autogrow4_execution_failed"],
            stdout=stdout[:2000],
            stderr=stderr[:2000],
            exit_code=exit_code,
            runtime_seconds=time.monotonic() - start_time,
        )


# ---------------------------------------------------------------------------
# Docker execution
# ---------------------------------------------------------------------------

def _run_autogrow4_docker(request: AutoGrow4Request, docker_image: str) -> AutoGrow4Result:
    """Run AutoGrow4 via Docker container."""
    import shutil

    start_time = time.monotonic()

    with tempfile.TemporaryDirectory(prefix="autogrow4_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        seeds_file = tmp_path / "seeds.smi"
        receptor_file = tmp_path / "protein.pdb"
        output_dir = tmp_path / "output"

        # Write seed SMILES and copy receptor
        _write_seed_smiles(seeds_file, request.seed_smiles)
        shutil.copy2(request.receptor_file, receptor_file)
        output_dir.mkdir()

        # Build Docker command
        cmd = [
            "docker", "run", "--rm",
            "-v", f"{tmp_path}:/data",
            docker_image,
            "python", "-m", "autogrow4",
            "--receptor", "/data/protein.pdb",
            "--seed_ligands", "/data/seeds.smi",
            "--output_dir", "/data/output",
            "--num_generations", str(request.num_generations),
            "--population_size", str(request.population_size),
            "--optimization_mode", request.optimization_mode,
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
            return AutoGrow4Result(
                adapter_mode="autogrow4_docker_timeout",
                tool_name="autogrow4",
                success=False,
                warnings=["autogrow4_docker_timeout"],
                exit_code=-1,
                runtime_seconds=time.monotonic() - start_time,
            )
        except FileNotFoundError:
            return AutoGrow4Result(
                adapter_mode="docker_not_found",
                tool_name="autogrow4",
                success=False,
                warnings=["docker_not_installed"],
                exit_code=-1,
                runtime_seconds=time.monotonic() - start_time,
            )

        # Parse output
        generated_smiles, scores = _parse_autogrow4_output(output_dir)

        # Copy output to request output_dir
        final_output_dir = Path(request.output_dir)
        final_output_dir.mkdir(parents=True, exist_ok=True)
        if output_dir.exists():
            for f in output_dir.glob("*"):
                shutil.copy2(f, final_output_dir / f.name)

        return AutoGrow4Result(
            adapter_mode="autogrow4_docker",
            tool_name="autogrow4",
            success=exit_code == 0 and len(generated_smiles) > 0,
            generated_smiles=generated_smiles,
            scores=scores,
            labels=["autogrow4_generated", "autogrow4_docker"],
            warnings=[] if exit_code == 0 else ["autogrow4_docker_failed"],
            stdout=stdout[:2000],
            stderr=stderr[:2000],
            exit_code=exit_code,
            runtime_seconds=time.monotonic() - start_time,
        )


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _write_seed_smiles(path: Path, smiles_list: list[str]) -> None:
    """Write seed SMILES to file."""
    with open(path, "w") as f:
        for i, smi in enumerate(smiles_list):
            f.write(f"{smi}\tseed_{i}\n")


def _parse_autogrow4_output(
    output_dir: Path,
) -> tuple[list[str], list[float]]:
    """Parse AutoGrow4 output directory for generated molecules."""
    smiles_list: list[str] = []
    scores: list[float] = []

    # Look for output CSV files
    for csv_file in output_dir.glob("*.csv"):
        try:
            with open(csv_file, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    smi = row.get("SMILES") or row.get("smiles") or row.get("Smiles")
                    score = row.get("score") or row.get("Score") or row.get("fitness")
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
            continue

    # Look for SDF files if no CSV found
    if not smiles_list:
        try:
            from rdkit import Chem
            for sdf_file in output_dir.glob("*.sdf"):
                supplier = Chem.SDMolSupplier(str(sdf_file))
                for mol in supplier:
                    if mol is not None:
                        smi = Chem.MolToSmiles(mol)
                        if smi:
                            smiles_list.append(smi)
                            scores.append(0.0)
        except ImportError:
            pass

    return smiles_list, scores


# ---------------------------------------------------------------------------
# Adapter status for tool detection
# ---------------------------------------------------------------------------

def autogrow4_tool_status() -> dict[str, Any]:
    """Get AutoGrow4 tool status."""
    status = check_autogrow4_available()
    return {
        "available": status["available"],
        "mode": status.get("mode"),
        "version": status.get("version"),
        "docker_image": status.get("docker_image"),
    }
