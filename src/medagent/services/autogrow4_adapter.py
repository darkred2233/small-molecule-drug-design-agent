"""AutoGrow4 adapter for molecular generation.

AutoGrow4 is a genetic algorithm-based molecular generation tool that
optimizes molecules using docking-guided evolution.

Supports:
- Local source/module installation
- Docker container execution

Reference: https://github.com/durrantlab/autogrow4
"""

import csv
import json
import math
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

from medagent.services.docker_runtime import DockerMountBuilder, docker_temporary_directory
from medagent.services.tool_config import get_tool_runtime_config


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
    optimization_mode: str = "genetic"
    constraints: dict[str, Any] = field(default_factory=dict)
    docker_image: str | None = None
    use_docker: bool = False
    timeout_seconds: int = 1200


@dataclass
class AutoGrow4Result:
    adapter_mode: str
    tool_name: str
    success: bool
    generated_smiles: list[str] = field(default_factory=list)
    scores: list[float | None] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    runtime_seconds: float = 0.0
    provenance: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# AutoGrow4 availability check
# ---------------------------------------------------------------------------

def check_autogrow4_available() -> dict[str, Any]:
    """Check if AutoGrow4 is available."""
    runtime_config = get_tool_runtime_config(
        "autogrow4",
        default_images=("autogrow4:latest", "autogrow:latest"),
        default_timeout_seconds=1200,
    )
    result: dict[str, Any] = {
        "available": False,
        "mode": None,
        "version": None,
        "docker_image": None,
        "runtime_available": False,
        "warning": None,
        **runtime_config.as_status(),
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
            result["mode"] = "python_package"
            result["version"] = getattr(autogrow4, "__version__", "unknown")
            missing_dependencies = _missing_local_dependencies()
            if not missing_dependencies:
                result["available"] = True
                result["runtime_available"] = True
                return result
            result["warning"] = (
                "autogrow4_local_dependencies_unavailable:"
                + ",".join(missing_dependencies)
            )
    except (ImportError, OSError, subprocess.TimeoutExpired):
        pass

    # Check Docker
    for image in runtime_config.docker_images:
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
                            "(test -f /app/autogrow4/RunAutogrow.py "
                            "|| test -f /app/autogrow4/run_autogrow.py) "
                            "&& python -m autogrow4 --help >/dev/null "
                            "&& command -v vina >/dev/null "
                            "&& command -v obabel >/dev/null"
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
        except (OSError, subprocess.TimeoutExpired):
            pass

    return result


def _missing_local_dependencies() -> list[str]:
    return [name for name in ("vina", "obabel") if shutil.which(name) is None]


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

    receptor_path = Path(request.receptor_file).expanduser()
    if not receptor_path.is_file():
        return AutoGrow4Result(
            adapter_mode="autogrow4_receptor_not_found",
            tool_name="autogrow4",
            success=False,
            warnings=["autogrow4_receptor_file_not_found"],
        )
    if receptor_path.suffix.lower() != ".pdb":
        return AutoGrow4Result(
            adapter_mode="autogrow4_receptor_format_unsupported",
            tool_name="autogrow4",
            success=False,
            warnings=["autogrow4_receptor_pdb_required"],
        )

    if not request.seed_smiles:
        return AutoGrow4Result(
            adapter_mode="autogrow4_seed_smiles_missing",
            tool_name="autogrow4",
            success=False,
            warnings=["autogrow4_seed_smiles_required"],
        )

    if request.optimization_mode.strip().lower() != "genetic":
        return AutoGrow4Result(
            adapter_mode="autogrow4_optimization_mode_unsupported",
            tool_name="autogrow4",
            success=False,
            warnings=[
                f"autogrow4_optimization_mode_unsupported:{request.optimization_mode}"
            ],
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
        docker_image = (
            request.docker_image
            or autogrow4_status.get("docker_image")
            or "autogrow4:latest"
        )
        return _run_autogrow4_docker(request, str(docker_image))
    else:
        return _run_autogrow4_local(request)


# ---------------------------------------------------------------------------
# Local execution
# ---------------------------------------------------------------------------

def _run_autogrow4_local(request: AutoGrow4Request) -> AutoGrow4Result:
    """Run AutoGrow4 via local CLI."""
    start_time = time.monotonic()

    with docker_temporary_directory(prefix="autogrow4_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        seeds_file = tmp_path / "seeds.smi"
        config_file = tmp_path / "config.json"
        output_dir = tmp_path / "output"

        # Write seed SMILES
        _write_seed_smiles(seeds_file, request.seed_smiles)
        output_dir.mkdir()

        config = _write_autogrow4_config(
            config_file,
            request,
            receptor_file=str(Path(request.receptor_file).expanduser().resolve()),
            seeds_file=str(seeds_file),
            output_dir=str(output_dir),
            docker=False,
        )
        cmd = _build_autogrow4_command(
            config_file=str(config_file),
            executable=[sys.executable, "-m", "autogrow4"],
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
                provenance=_autogrow4_provenance(
                    request,
                    execution_mode="python_package",
                    command=cmd,
                    config=config,
                ),
            )
        except FileNotFoundError:
            return AutoGrow4Result(
                adapter_mode="autogrow4_not_found",
                tool_name="autogrow4",
                success=False,
                warnings=["autogrow4_binary_not_found"],
                exit_code=-1,
                runtime_seconds=time.monotonic() - start_time,
                provenance=_autogrow4_provenance(
                    request,
                    execution_mode="python_package",
                    command=cmd,
                    config=config,
                ),
            )
        except OSError as exc:
            return AutoGrow4Result(
                adapter_mode="autogrow4_execution_os_error",
                tool_name="autogrow4",
                success=False,
                warnings=[f"autogrow4_execution_os_error:{type(exc).__name__}"],
                exit_code=-1,
                runtime_seconds=time.monotonic() - start_time,
                provenance=_autogrow4_provenance(
                    request,
                    execution_mode="python_package",
                    command=cmd,
                    config=config,
                ),
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

        success = (
            exit_code == 0
            and len(generated_smiles) > 0
            and any(score is not None for score in scores)
        )
        return AutoGrow4Result(
            adapter_mode="autogrow4_local",
            tool_name="autogrow4",
            success=success,
            generated_smiles=generated_smiles,
            scores=scores,
            labels=_autogrow4_labels(success, "autogrow4_local"),
            warnings=_autogrow4_warnings(exit_code, generated_smiles, scores),
            stdout=stdout[:2000],
            stderr=stderr[:2000],
            exit_code=exit_code,
            runtime_seconds=time.monotonic() - start_time,
            provenance=_autogrow4_provenance(
                request,
                execution_mode="python_package",
                command=cmd,
                config=config,
            ),
        )


# ---------------------------------------------------------------------------
# Docker execution
# ---------------------------------------------------------------------------

def _run_autogrow4_docker(request: AutoGrow4Request, docker_image: str) -> AutoGrow4Result:
    """Run AutoGrow4 via Docker container."""
    start_time = time.monotonic()

    with docker_temporary_directory(prefix="autogrow4_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        seeds_file = tmp_path / "seeds.smi"
        receptor_file = tmp_path / "protein.pdb"
        config_file = tmp_path / "config.json"
        output_dir = tmp_path / "output"

        # Write seed SMILES and copy receptor
        _write_seed_smiles(seeds_file, request.seed_smiles)
        shutil.copy2(request.receptor_file, receptor_file)
        output_dir.mkdir()

        # Generate unique container name
        container_name = f"autogrow4_{int(time.monotonic() * 1000)}"
        mounts = DockerMountBuilder()
        data_path = mounts.bind(tmp_path, "/data")

        config = _write_autogrow4_config(
            config_file,
            request,
            receptor_file=str(PurePosixPath(data_path, "protein.pdb")),
            seeds_file=str(PurePosixPath(data_path, "seeds.smi")),
            output_dir=str(PurePosixPath(data_path, "output")),
            docker=True,
        )
        autogrow_command = _build_autogrow4_command(
            config_file=str(PurePosixPath(data_path, "config.json")),
            executable=["-m", "autogrow4"],
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
                provenance=_autogrow4_provenance(
                    request,
                    execution_mode="docker",
                    command=cmd,
                    config=config,
                    docker_image=docker_image,
                ),
            )
        except FileNotFoundError:
            return AutoGrow4Result(
                adapter_mode="docker_not_found",
                tool_name="autogrow4",
                success=False,
                warnings=["docker_not_installed"],
                exit_code=-1,
                runtime_seconds=time.monotonic() - start_time,
                provenance=_autogrow4_provenance(
                    request,
                    execution_mode="docker",
                    command=cmd,
                    config=config,
                    docker_image=docker_image,
                ),
            )
        except OSError as exc:
            return AutoGrow4Result(
                adapter_mode="autogrow4_docker_os_error",
                tool_name="autogrow4",
                success=False,
                warnings=[f"autogrow4_docker_os_error:{type(exc).__name__}"],
                exit_code=-1,
                runtime_seconds=time.monotonic() - start_time,
                provenance=_autogrow4_provenance(
                    request,
                    execution_mode="docker",
                    command=cmd,
                    config=config,
                    docker_image=docker_image,
                ),
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

        success = (
            exit_code == 0
            and len(generated_smiles) > 0
            and any(score is not None for score in scores)
        )
        return AutoGrow4Result(
            adapter_mode="autogrow4_docker",
            tool_name="autogrow4",
            success=success,
            generated_smiles=generated_smiles,
            scores=scores,
            labels=_autogrow4_labels(success, "autogrow4_docker"),
            warnings=_autogrow4_warnings(
                exit_code, generated_smiles, scores, docker=True
            ),
            stdout=stdout[:2000],
            stderr=stderr[:2000],
            exit_code=exit_code,
            runtime_seconds=time.monotonic() - start_time,
            provenance=_autogrow4_provenance(
                request,
                execution_mode="docker",
                command=cmd,
                config=config,
                docker_image=docker_image,
            ),
        )


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _write_seed_smiles(path: Path, smiles_list: list[str]) -> None:
    """Write seed SMILES to file."""
    with open(path, "w", encoding="utf-8") as f:
        for i, smi in enumerate(smiles_list):
            f.write(f"{smi}\tseed_{i}\n")


def _build_autogrow4_command(
    *,
    config_file: str,
    executable: list[str],
) -> list[str]:
    return [*executable, "-j", config_file]


def _write_autogrow4_config(
    path: Path,
    request: AutoGrow4Request,
    *,
    receptor_file: str,
    seeds_file: str,
    output_dir: str,
    docker: bool,
) -> dict[str, Any]:
    config = _autogrow4_config(
        request,
        receptor_file=receptor_file,
        seeds_file=seeds_file,
        output_dir=output_dir,
        docker=docker,
    )
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return config


def _autogrow4_config(
    request: AutoGrow4Request,
    *,
    receptor_file: str,
    seeds_file: str,
    output_dir: str,
    docker: bool,
) -> dict[str, Any]:
    grid = _grid_values(request)
    if grid is None:
        raise ValueError("autogrow4_grid_center_and_size_required")
    center, size = grid
    population_size = max(4, request.population_size)
    elite = max(1, population_size // 5)
    generated = population_size - elite
    crossovers = generated // 2
    mutants = generated - crossovers
    vina_path = "/usr/bin/vina" if docker else str(shutil.which("vina") or "vina")
    obabel_path = "/usr/bin/obabel" if docker else str(shutil.which("obabel") or "obabel")
    return {
        "filename_of_receptor": receptor_file,
        "source_compound_file": seeds_file,
        "root_output_folder": output_dir,
        "center_x": center[0],
        "center_y": center[1],
        "center_z": center[2],
        "size_x": size[0],
        "size_y": size[1],
        "size_z": size[2],
        "num_generations": max(1, request.num_generations),
        "number_of_crossovers_first_generation": crossovers,
        "number_of_mutants_first_generation": mutants,
        "number_of_crossovers": crossovers,
        "number_of_mutants": mutants,
        "number_elitism_advance_from_previous_gen": elite,
        "top_mols_to_seed_next_generation": elite,
        "diversity_mols_to_seed_first_generation": elite,
        "conversion_choice": "ObabelConversion",
        "obabel_path": obabel_path,
        "dock_choice": "VinaDocking",
        "docking_executable": vina_path,
        "multithread_mode": "multithreading",
        "number_of_processors": -1,
        "start_a_new_run": True,
    }


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
        center_values = [float(value) for value in center]
        size_values = [float(value) for value in size]
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in [*center_values, *size_values]):
        return None
    if not all(value > 0 for value in size_values):
        return None
    return center_values, size_values


def _parse_autogrow4_output(
    output_dir: Path,
) -> tuple[list[str], list[float | None]]:
    """Parse AutoGrow4 output directory for generated molecules."""
    smiles_list: list[str] = []
    scores: list[float | None] = []

    ranked_files = sorted(output_dir.rglob("*ranked*.smi"), key=_ranked_output_sort_key)
    if ranked_files:
        for line in ranked_files[-1].read_text(encoding="utf-8", errors="ignore").splitlines():
            columns = line.split()
            if not columns or columns[0].lower() == "smiles":
                continue
            score: float | None = None
            for value in reversed(columns[1:]):
                try:
                    parsed_score = float(value)
                    score = parsed_score if math.isfinite(parsed_score) else None
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
                    if smi and smi not in smiles_list:
                        smiles_list.append(smi)
                        if score:
                            try:
                                parsed_score = float(score)
                                scores.append(
                                    parsed_score if math.isfinite(parsed_score) else None
                                )
                            except ValueError:
                                scores.append(None)
                        else:
                            scores.append(None)
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
                            scores.append(None)
        except ImportError:
            pass

    return smiles_list, scores


def _ranked_output_sort_key(path: Path) -> tuple[int, int, str]:
    generation_match = re.search(r"generation[_-]?(\d+)", str(path), re.IGNORECASE)
    generation = int(generation_match.group(1)) if generation_match else -1
    try:
        modified_ns = path.stat().st_mtime_ns
    except OSError:
        modified_ns = -1
    return generation, modified_ns, str(path)


def _autogrow4_warnings(
    exit_code: int,
    generated_smiles: list[str],
    scores: list[float | None],
    *,
    docker: bool = False,
) -> list[str]:
    if exit_code != 0:
        return ["autogrow4_docker_failed" if docker else "autogrow4_execution_failed"]
    if not generated_smiles:
        return ["autogrow4_output_missing_or_empty"]
    if not any(score is not None for score in scores):
        return ["autogrow4_ranked_fitness_missing"]
    return []


def _autogrow4_labels(success: bool, mode_label: str) -> list[str]:
    outcome = "autogrow4_generated" if success else "autogrow4_generation_failed"
    return [outcome, mode_label]


def _autogrow4_provenance(
    request: AutoGrow4Request,
    *,
    execution_mode: str,
    command: list[str],
    config: dict[str, Any],
    docker_image: str | None = None,
) -> dict[str, Any]:
    grid = _grid_values(request)
    return {
        "execution_mode": execution_mode,
        "docker_image": docker_image,
        "command": command,
        "config": config,
        "receptor_file": str(Path(request.receptor_file).resolve()),
        "grid_center": grid[0] if grid else None,
        "grid_size": grid[1] if grid else None,
        "num_generations": request.num_generations,
        "population_size": request.population_size,
        "effective_population_size": (
            config["number_of_crossovers"]
            + config["number_of_mutants"]
            + config["number_elitism_advance_from_previous_gen"]
        ),
        "optimization_mode": request.optimization_mode,
        "score_semantics": "autogrow4_ranked_output_fitness",
        "timeout_seconds": request.timeout_seconds,
    }


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
        "docker_image_candidates": status.get("docker_image_candidates", []),
        "configured_timeout_seconds": status.get("configured_timeout_seconds", 1200),
        "config_source": status.get("config_source"),
        "config_loaded": status.get("config_loaded", False),
        "config_environment_overrides": status.get("config_environment_overrides", []),
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
