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
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

from medagent.services.docker_runtime import DockerMountBuilder, docker_temporary_directory


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
        "runtime_available": False,
        "warning": None,
    }

    # Check local Python package
    try:
        import autogrow4
        proc = subprocess.run(
            [sys.executable, "-m", "autogrow4", "--help"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if proc.returncode == 0:
            result["available"] = True
            result["runtime_available"] = True
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
                result["mode"] = "docker"
                result["docker_image"] = image
                runtime_probe = subprocess.run(
                    [
                        "docker",
                        "run",
                        "--rm",
                        "--entrypoint",
                        "sh",
                        image,
                        "-c",
                        (
                            "python /app/autogrow4/run_autogrow.py --help >/dev/null "
                            "&& command -v vina >/dev/null"
                        ),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                result["runtime_available"] = runtime_probe.returncode == 0
                result["available"] = result["runtime_available"]
                if not result["runtime_available"]:
                    result["warning"] = "autogrow4_runtime_or_vina_dependency_unavailable"
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

    if _grid_values(request) is None:
        return AutoGrow4Result(
            adapter_mode="autogrow4_grid_not_configured",
            tool_name="autogrow4",
            success=False,
            warnings=["autogrow4_grid_center_and_size_required"],
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

    with docker_temporary_directory(prefix="autogrow4_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        seeds_file = tmp_path / "seeds.smi"
        output_dir = tmp_path / "output"

        # Write seed SMILES
        _write_seed_smiles(seeds_file, request.seed_smiles)
        output_dir.mkdir()

        cmd = _build_autogrow4_command(
            request,
            receptor_file=request.receptor_file,
            seeds_file=str(seeds_file),
            output_dir=str(output_dir),
            executable=[sys.executable, "-m", "autogrow4"],
            docker=False,
        )

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
            shutil.copytree(
                output_dir,
                final_output_dir / "autogrow4_output",
                dirs_exist_ok=True,
            )

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

    with docker_temporary_directory(prefix="autogrow4_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        seeds_file = tmp_path / "seeds.smi"
        receptor_file = tmp_path / "protein.pdb"
        output_dir = tmp_path / "output"

        # Write seed SMILES and copy receptor
        _write_seed_smiles(seeds_file, request.seed_smiles)
        shutil.copy2(request.receptor_file, receptor_file)
        output_dir.mkdir()

        # Generate unique container name
        container_name = f"autogrow4_{int(time.monotonic() * 1000)}"
        mounts = DockerMountBuilder()
        data_path = mounts.bind(tmp_path, "/data")

        autogrow_command = _build_autogrow4_command(
            request,
            receptor_file=str(PurePosixPath(data_path, "protein.pdb")),
            seeds_file=str(PurePosixPath(data_path, "seeds.smi")),
            output_dir=str(PurePosixPath(data_path, "output")),
            executable=["-m", "autogrow4"],
            docker=True,
        )
        cmd = [
            "docker", "run", "--rm",
            "--name", container_name,
            *mounts.arguments,
            docker_image,
            *autogrow_command,
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
            # Clean up container on timeout
            _cleanup_docker_container(container_name)
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
            shutil.copytree(
                output_dir,
                final_output_dir / "autogrow4_output",
                dirs_exist_ok=True,
            )

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


def _build_autogrow4_command(
    request: AutoGrow4Request,
    *,
    receptor_file: str,
    seeds_file: str,
    output_dir: str,
    executable: list[str],
    docker: bool,
) -> list[str]:
    grid = _grid_values(request)
    if grid is None:
        raise ValueError("autogrow4_grid_center_and_size_required")
    center, size = grid
    elite = max(1, request.population_size // 5)
    generated = max(2, request.population_size - elite)
    crossovers = generated // 2
    mutants = generated - crossovers
    vina_path = "/usr/bin/vina" if docker else "vina"
    obabel_path = "/usr/bin/obabel" if docker else "obabel"
    command = [
        *executable,
        "--filename_of_receptor",
        receptor_file,
        "--source_compound_file",
        seeds_file,
        "--root_output_folder",
        output_dir,
        "--center_x",
        str(center[0]),
        "--center_y",
        str(center[1]),
        "--center_z",
        str(center[2]),
        "--size_x",
        str(size[0]),
        "--size_y",
        str(size[1]),
        "--size_z",
        str(size[2]),
        "--num_generations",
        str(request.num_generations),
        "--number_of_crossovers_first_generation",
        str(crossovers),
        "--number_of_mutants_first_generation",
        str(mutants),
        "--number_of_crossovers",
        str(crossovers),
        "--number_of_mutants",
        str(mutants),
        "--number_elitism_advance_from_previous_gen",
        str(elite),
        "--top_mols_to_seed_next_generation",
        str(elite),
        "--diversity_mols_to_seed_first_generation",
        str(elite),
        "--conversion_choice",
        "ObabelConversion",
        "--obabel_path",
        obabel_path,
        "--dock_choice",
        "VinaDocking",
        "--docking_executable",
        vina_path,
        "--multithread_mode",
        "multithreading",
        "--number_of_processors",
        "-1",
        "--start_a_new_run",
    ]
    return command


def _grid_values(
    request: AutoGrow4Request,
) -> tuple[list[float], list[float]] | None:
    center = request.constraints.get("grid_center") or request.constraints.get("center")
    size = request.constraints.get("grid_size") or request.constraints.get("size")
    if not isinstance(center, list) or not isinstance(size, list):
        return None
    if len(center) != 3 or len(size) != 3:
        return None
    try:
        return [float(value) for value in center], [float(value) for value in size]
    except (TypeError, ValueError):
        return None


def _parse_autogrow4_output(
    output_dir: Path,
) -> tuple[list[str], list[float]]:
    """Parse AutoGrow4 output directory for generated molecules."""
    smiles_list: list[str] = []
    scores: list[float] = []

    ranked_files = sorted(output_dir.rglob("*ranked*.smi"))
    if ranked_files:
        for line in ranked_files[-1].read_text(encoding="utf-8", errors="ignore").splitlines():
            columns = line.split()
            if not columns or columns[0].lower() == "smiles":
                continue
            score = 0.0
            for value in reversed(columns[1:]):
                try:
                    score = float(value)
                    break
                except ValueError:
                    continue
            if columns[0] not in smiles_list:
                smiles_list.append(columns[0])
                scores.append(score)

    # Look for output CSV files
    for csv_file in output_dir.rglob("*.csv"):
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
            for sdf_file in output_dir.rglob("*.sdf"):
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
        "runtime_available": status.get("runtime_available", False),
        "warning": status.get("warning"),
    }


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
