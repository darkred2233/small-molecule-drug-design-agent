"""Local AutoGrow4 adapter.

AutoGrow4 is run from a checkout and an isolated Python interpreter.  No
synthetic candidate fallback is produced when the local tool is unavailable.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import json
import math
import shlex
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from medagent.services.tool_config import (
    configured_paths_exist,
    get_tool_runtime_config,
    resolve_configured_path,
)
from medagent.services.wsl_runtime import build_wsl_command, windows_path_to_wsl, wsl_file_exists


AUTOGROW_PROFILES: dict[str, dict[str, int]] = {
    "quick": {
        "generations": 3,
        "population_size": 30,
        "processors": 4,
        "exhaustiveness": 1,
        "timeout": 120,
    },
    "normal": {
        "generations": 5,
        "population_size": 50,
        "processors": 8,
        "exhaustiveness": 2,
        "timeout": 300,
    },
    "heavy": {
        "generations": 10,
        "population_size": 100,
        "processors": 8,
        "exhaustiveness": 4,
        "timeout": 300,
    },
}


@dataclass(frozen=True)
class AutoGrow4Request:
    seed_smiles: list[str]
    receptor_file: str
    output_dir: str
    num_generations: int = 10
    population_size: int = 50
    optimization_mode: str = "genetic"
    constraints: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: int = 3600


@dataclass(frozen=True)
class AutoGrowEvolutionPlan:
    population_size: int
    first_generation_mutants: int
    first_generation_crossovers: int
    later_generation_mutants: int
    later_generation_crossovers: int
    later_generation_elites: int
    parent_count: int


def autogrow_profile(search_intensity: str) -> dict[str, int]:
    return dict(AUTOGROW_PROFILES.get(search_intensity, AUTOGROW_PROFILES["normal"]))


def build_evolution_plan(request: AutoGrow4Request) -> AutoGrowEvolutionPlan:
    population_size = max(int(request.population_size), 1)
    crossover = _bounded_float(
        request.constraints.get("crossover_fraction", 0.5), 0.0, 1.0, 0.5
    )
    first_crossovers = int(round(population_size * crossover))
    if len(request.seed_smiles) < 8:
        first_crossovers = 0
    first_mutants = population_size - first_crossovers

    # Later generations intentionally use a small steady-state population.
    # AutoGrow requires exact mutation counts; asking for 50 children from a
    # five-molecule survivor pool caused the observed multi-hour failure.
    later_size = min(population_size, max(3, int(math.ceil(population_size * 0.10))))
    later_elites = 1 if later_size >= 3 else 0
    later_crossovers = 1 if later_size >= 5 else 0
    later_mutants = later_size - later_elites - later_crossovers
    parent_count = min(max(2, int(math.ceil(math.sqrt(later_size)))), len(request.seed_smiles))
    parent_count = max(1, parent_count)
    return AutoGrowEvolutionPlan(
        population_size=population_size,
        first_generation_mutants=first_mutants,
        first_generation_crossovers=first_crossovers,
        later_generation_mutants=later_mutants,
        later_generation_crossovers=later_crossovers,
        later_generation_elites=later_elites,
        parent_count=parent_count,
    )


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


def check_autogrow4_available() -> dict[str, Any]:
    config = get_tool_runtime_config("autogrow4", default_timeout_seconds=3600)
    required_ready, missing_paths = configured_paths_exist(config)
    script = _script_path(config.command, config.working_directory)
    source_dir = resolve_configured_path(config.working_directory)
    runtime_patch_missing = _missing_autogrow_runtime_extensions(source_dir)
    is_wsl = config.runtime == "wsl"
    python = (
        config.python_executable
        if is_wsl
        and config.python_executable
        and wsl_file_exists(
            config.python_executable,
            distribution=config.wsl_distribution,
            user=config.wsl_user,
        )
        else _local_python(config.python_executable)
        if not is_wsl
        else None
    )
    source_dir_wsl = windows_path_to_wsl(source_dir) if source_dir else None
    script_wsl = windows_path_to_wsl(script) if script else None
    obabel_path = f"{python.rsplit('/', 1)[0]}/obabel" if is_wsl and python else None
    dependencies = [] if is_wsl else _missing_local_dependencies()
    runtime_environment = config.environment_dict()
    gpu_executable = resolve_configured_path(
        runtime_environment.get("MEDAGENT_VINA_GPU_EXECUTABLE")
    )
    gpu_opencl_path = resolve_configured_path(
        runtime_environment.get("MEDAGENT_VINA_GPU_OPENCL_BINARY_PATH")
    )
    result: dict[str, Any] = {
        "available": False,
        "runtime_available": False,
        "mode": "wsl_python" if is_wsl else "local_python",
        "python_executable": python,
        "script": str(script) if script else None,
        "script_wsl": script_wsl if is_wsl else None,
        "source_dir_wsl": source_dir_wsl if is_wsl else None,
        "obabel_path": obabel_path if is_wsl else "obabel",
        "working_directory": config.working_directory,
        "version": None,
        "missing_paths": missing_paths,
        "missing_dependencies": dependencies,
        "runtime_patch_ready": not runtime_patch_missing,
        "runtime_patch_missing": runtime_patch_missing,
        "gpu_docking_backend": "vina_gpu_2_1_batch",
        "gpu_docking_executable": str(gpu_executable) if gpu_executable else None,
        "gpu_docking_opencl_path": str(gpu_opencl_path) if gpu_opencl_path else None,
        "gpu_docking_ready": bool(
            gpu_executable
            and gpu_executable.is_file()
            and gpu_opencl_path
            and gpu_opencl_path.is_dir()
        ),
        "warning": None,
        **config.as_status(),
    }
    if not required_ready:
        result["warning"] = "autogrow4_required_files_missing"
        return result
    if runtime_patch_missing:
        result["warning"] = "autogrow4_medagent_extensions_missing"
        return result
    if not result["gpu_docking_ready"]:
        result["warning"] = "autogrow4_vina_gpu_not_configured"
        return result
    if python is None:
        result["warning"] = "autogrow4_local_python_not_found"
        return result
    if script is None:
        result["warning"] = "autogrow4_entrypoint_not_found"
        return result
    if is_wsl and (
        obabel_path is None
        or not wsl_file_exists(
            obabel_path,
            distribution=config.wsl_distribution,
            user=config.wsl_user,
        )
    ):
        result["warning"] = "autogrow4_openbabel_not_found"
        return result
    if dependencies:
        result["warning"] = "autogrow4_local_dependencies_unavailable:" + ",".join(dependencies)
        return result
    try:
        probe_command = [python, str(script), "--help"]
        probe_cwd = str(script.parent)
        if is_wsl:
            assert script_wsl is not None and source_dir_wsl is not None
            probe_command = build_wsl_command(
                [python, script_wsl, "--help"],
                distribution=config.wsl_distribution,
                user=config.wsl_user,
                cwd=source_dir_wsl,
                environment={"PYTHONPATH": source_dir_wsl},
            )
            probe_cwd = None
        probe = subprocess.run(
            probe_command,
            capture_output=True,
            text=True,
            encoding="utf-8" if is_wsl else None,
            errors="replace" if is_wsl else None,
            timeout=30,
            check=False,
            cwd=probe_cwd,
        )
    except (OSError, subprocess.TimeoutExpired):
        result["warning"] = "autogrow4_local_runtime_probe_failed"
        return result
    result["runtime_available"] = probe.returncode == 0
    result["available"] = probe.returncode == 0
    output = (probe.stdout or probe.stderr or "").strip().splitlines()
    result["version"] = output[0] if output else None
    if not result["available"]:
        result["warning"] = "autogrow4_local_runtime_probe_failed"
    return result


def autogrow4_tool_status() -> dict[str, Any]:
    return check_autogrow4_available()


def run_autogrow4_generation(
    request: AutoGrow4Request, autogrow4_status: dict[str, Any] | None = None
) -> AutoGrow4Result:
    status = autogrow4_status or check_autogrow4_available()
    if not status.get("available"):
        return AutoGrow4Result(
            "autogrow4_unavailable",
            "autogrow4",
            False,
            warnings=[str(status.get("warning") or "autogrow4_not_installed")],
        )
    receptor = Path(request.receptor_file).expanduser()
    if not receptor.is_file():
        return AutoGrow4Result(
            "autogrow4_receptor_not_found",
            "autogrow4",
            False,
            warnings=["autogrow4_receptor_file_not_found"],
        )
    if receptor.suffix.lower() != ".pdb":
        return AutoGrow4Result(
            "autogrow4_receptor_format_unsupported",
            "autogrow4",
            False,
            warnings=["autogrow4_receptor_pdb_required"],
        )
    if not request.seed_smiles:
        return AutoGrow4Result(
            "autogrow4_seed_smiles_missing",
            "autogrow4",
            False,
            warnings=["autogrow4_seed_smiles_required"],
        )
    if request.optimization_mode != "genetic" or _grid_values(request) is None:
        warning = (
            "autogrow4_grid_center_and_size_required"
            if _grid_values(request) is None
            else "autogrow4_optimization_mode_unsupported"
        )
        return AutoGrow4Result("autogrow4_request_invalid", "autogrow4", False, warnings=[warning])

    python = str(status.get("python_executable") or "")
    script = Path(str(status.get("script") or ""))
    is_wsl = status.get("runtime_scope") == "wsl"
    if not python or not script.is_file():
        return AutoGrow4Result(
            "autogrow4_unavailable",
            "autogrow4",
            False,
            warnings=["autogrow4_runtime_not_configured"],
        )
    if not _gpu_policy_is_valid(request):
        return AutoGrow4Result(
            "autogrow4_gpu_policy_invalid",
            "autogrow4",
            False,
            warnings=["autogrow4_requires_vina_gpu_without_cpu_fallback"],
        )

    runtime_config = get_tool_runtime_config("autogrow4", default_timeout_seconds=3600)
    runtime_environment = runtime_config.environment_dict()
    effective_timeout_seconds = _effective_timeout_seconds(request, runtime_environment)
    gpu_executable_path = resolve_configured_path(
        runtime_environment.get("MEDAGENT_VINA_GPU_EXECUTABLE")
    )
    gpu_opencl_path = resolve_configured_path(
        runtime_environment.get("MEDAGENT_VINA_GPU_OPENCL_BINARY_PATH")
    )
    if (
        gpu_executable_path is None
        or not gpu_executable_path.is_file()
        or gpu_opencl_path is None
        or not gpu_opencl_path.is_dir()
    ):
        return AutoGrow4Result(
            "autogrow4_vina_gpu_unavailable",
            "autogrow4",
            False,
            warnings=["autogrow4_vina_gpu_runtime_missing"],
        )

    started = time.monotonic()
    destination_root = Path(request.output_dir).resolve()
    destination_root.mkdir(parents=True, exist_ok=True)
    destination = Path(tempfile.mkdtemp(prefix="attempt-", dir=destination_root)).resolve()
    # Use the destination directory directly for working files so that WSL
    # subprocesses write to the same filesystem visible to Windows.
    seeds_file = destination / "seeds.smi"
    config_file = destination / "config.json"
    generated_dir = destination / "output"
    generated_dir.mkdir(exist_ok=True)
    _write_seed_smiles(seeds_file, request.seed_smiles)
    receptor_file = str(receptor.resolve())
    seeds_path = str(seeds_file)
    generated_path = str(generated_dir)
    if is_wsl:
        receptor_file = windows_path_to_wsl(receptor_file)
        seeds_path = windows_path_to_wsl(seeds_path)
        generated_path = windows_path_to_wsl(generated_path)
    gpu_executable = str(gpu_executable_path)
    gpu_opencl_binary_path = str(gpu_opencl_path)
    if is_wsl:
        gpu_executable = windows_path_to_wsl(gpu_executable)
        gpu_opencl_binary_path = windows_path_to_wsl(gpu_opencl_binary_path)
    config = _write_autogrow4_config(
        config_file,
        request,
        receptor_file=receptor_file,
        seeds_file=seeds_path,
        output_dir=generated_path,
        obabel_path=str(status.get("obabel_path") or "obabel"),
        docking_executable=gpu_executable,
    )
    command = _build_autogrow4_command(
        config_file=str(config_file), executable=[python, str(script)]
    )
    execution_mode = "local_python"
    process_cwd: str | None = str(script.parent)
    if is_wsl:
        try:
            source_dir_wsl = _prepare_wsl_source_cache(
                script.parent,
                distribution=str(status.get("wsl_distribution") or "Ubuntu"),
                user=str(status.get("wsl_user") or "root"),
                cache_root=runtime_environment.get(
                    "MEDAGENT_AUTOGROW4_WSL_CACHE_ROOT",
                    "/opt/medagent/autogrow4-cache",
                ),
            )
        except RuntimeError as exc:
            return AutoGrow4Result(
                "autogrow4_wsl_source_cache_failed",
                "autogrow4",
                False,
                warnings=["autogrow4_wsl_source_cache_failed"],
                stderr=str(exc)[:4000],
                runtime_seconds=time.monotonic() - started,
            )
        script_wsl = f"{source_dir_wsl}/RunAutogrow.py"
        command = _build_autogrow4_command(
            config_file=windows_path_to_wsl(str(config_file)),
            executable=[
                "timeout",
                "--kill-after=30s",
                f"{effective_timeout_seconds}s",
                python,
                script_wsl,
            ],
        )
        command = build_wsl_command(
            command,
            distribution=str(status.get("wsl_distribution") or "Ubuntu"),
            user=str(status.get("wsl_user") or "root"),
            cwd=source_dir_wsl,
            environment={
                "PYTHONPATH": source_dir_wsl,
                **runtime_environment,
                "MEDAGENT_VINA_GPU_EXECUTABLE": gpu_executable,
                "MEDAGENT_VINA_GPU_OPENCL_BINARY_PATH": gpu_opencl_binary_path,
            },
        )
        execution_mode = "wsl_python"
        process_cwd = None
    try:
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8" if is_wsl else None,
            errors="replace" if is_wsl else None,
            # WSL's timeout owns the process group. The host margin exists only
            # for collecting its final output and avoids abandoning Linux or
            # native Windows Vina-GPU children when AutoGrow reaches its limit.
            timeout=effective_timeout_seconds + (60 if is_wsl else 0),
            cwd=process_cwd,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return AutoGrow4Result(
            "autogrow4_timeout",
            "autogrow4",
            False,
            warnings=["autogrow4_execution_timeout"],
            stderr=str(exc)[:4000],
            exit_code=None,
            runtime_seconds=time.monotonic() - started,
            provenance=_provenance(
                request, command, config, execution_mode, destination
            )
            | {"effective_timeout_seconds": effective_timeout_seconds},
        )
    except OSError as exc:
        return AutoGrow4Result(
            "autogrow4_execution_os_error",
            "autogrow4",
            False,
            warnings=[f"autogrow4_execution_os_error:{type(exc).__name__}"],
            stderr=str(exc)[:4000],
            exit_code=None,
            runtime_seconds=time.monotonic() - started,
            provenance=_provenance(
                request, command, config, execution_mode, destination
            )
            | {"effective_timeout_seconds": effective_timeout_seconds},
        )

    smiles, scores = _parse_autogrow4_output(generated_dir, generated_only=True)
    gpu_provenance = _vina_gpu_provenance(generated_dir)
    requested_generations = set(range(1, max(request.num_generations, 1) + 1))
    ranked_complete = requested_generations <= _ranked_generations(generated_dir)
    gpu_complete = (
        gpu_provenance is not None
        and requested_generations
        <= set(gpu_provenance.get("successful_generations", []))
    )
    completed = (
        process.returncode == 0
        and ranked_complete
        and gpu_complete
        and bool(smiles)
    )
    warnings = _autogrow4_warnings(
        process.returncode,
        smiles,
        scores,
        source_only_output=bool(smiles) and not ranked_complete,
    )
    if gpu_provenance is None:
        warnings.append("autogrow4_vina_gpu_provenance_missing")
    elif not gpu_complete:
        warnings.append("autogrow4_vina_gpu_generation_incomplete")
    return AutoGrow4Result(
        "vina_gpu_2_1_batch" if completed else "autogrow4_gpu_generation_failed",
        "autogrow4",
        completed,
        generated_smiles=smiles,
        scores=scores,
        labels=["autogrow4_vina_gpu_executed"] if completed else [],
        warnings=warnings,
        stdout=process.stdout[:4000],
        stderr=process.stderr[:4000],
        exit_code=process.returncode,
        runtime_seconds=time.monotonic() - started,
        provenance={
            **_provenance(request, command, config, execution_mode, destination),
            "adapter_mode": "vina_gpu_2_1_batch",
            "vina_gpu_provenance": gpu_provenance,
            "cpu_fallback": False,
            "wsl_source_cache": source_dir_wsl if is_wsl else None,
            "effective_timeout_seconds": effective_timeout_seconds,
        },
    )


def _prepare_wsl_source_cache(
    source_dir: Path,
    *,
    distribution: str,
    user: str,
    cache_root: str,
) -> str:
    """Stage read-heavy AutoGrow sources on WSL's native filesystem."""
    if not source_dir.is_dir():
        raise RuntimeError(f"AutoGrow source directory is missing: {source_dir}")

    source_wsl = windows_path_to_wsl(str(source_dir.resolve()))
    fingerprint = _source_tree_fingerprint(source_dir)
    cache_dir = f"{cache_root.rstrip('/')}/{fingerprint}"
    script = _wsl_source_cache_script(source_wsl, cache_dir, cache_root)
    # WSL.exe applies Windows command-line escaping before Bash sees an
    # argument. Encode the multi-line shell script so its quotes and dollar
    # signs cannot be altered in transit.
    payload = base64.b64encode(script.encode("utf-8")).decode("ascii")
    command = [
        "wsl",
        "-d",
        distribution,
        "-u",
        user,
        "--",
        "/bin/bash",
        "-c",
        f"echo {payload} | base64 -d | /bin/bash",
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Could not prepare WSL AutoGrow source cache: {exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "cache preparation failed").strip()
        raise RuntimeError(f"Could not prepare WSL AutoGrow source cache: {detail}")
    return cache_dir


def _source_tree_fingerprint(source_dir: Path) -> str:
    """Return a source-tree identifier while avoiding large reaction-library reads."""
    digest = hashlib.sha256()
    for item in sorted(source_dir.rglob("*")):
        if not item.is_file() or ".git" in item.parts or "__pycache__" in item.parts:
            continue
        stat = item.stat()
        relative_path = item.relative_to(source_dir).as_posix()
        digest.update(f"{relative_path}:{stat.st_size}:".encode())
        if item.suffix.lower() == ".py":
            with item.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        else:
            digest.update(str(stat.st_mtime_ns).encode())
        digest.update(b"\n")
    return digest.hexdigest()[:24]


def _wsl_source_cache_script(source_wsl: str, cache_dir: str, cache_root: str) -> str:
    """Build an atomic WSL-side cache operation for the local source tree."""
    source = shlex.quote(source_wsl)
    cache = shlex.quote(cache_dir)
    root = shlex.quote(cache_root)
    return f'''set -euo pipefail
source_dir={source}
cache_dir={cache}
cache_root={root}
if [ ! -f "$cache_dir/.ready" ]; then
  mkdir -p "$cache_root"
  lock_dir="$cache_dir.lock"
  if mkdir "$lock_dir" 2>/dev/null; then
    tmp_dir="$(mktemp -d "$cache_root/.build.XXXXXX")"
    cleanup() {{ rm -rf "$tmp_dir"; rmdir "$lock_dir" 2>/dev/null || true; }}
    trap cleanup EXIT
    if [ ! -f "$cache_dir/.ready" ]; then
      tar -C "$source_dir" --exclude=.git --exclude=__pycache__ -cf - . | tar -C "$tmp_dir" -xf -
      touch "$tmp_dir/.ready"
      rm -rf "$cache_dir"
      mv "$tmp_dir" "$cache_dir"
    fi
  else
    for _ in $(seq 1 600); do
      [ -f "$cache_dir/.ready" ] && break
      sleep 0.5
    done
  fi
fi
test -f "$cache_dir/RunAutogrow.py" && test -f "$cache_dir/.ready"'''


def _write_seed_smiles(path: Path, seeds: list[str]) -> None:
    path.write_text(
        "\n".join(f"{value}\tseed_{index}" for index, value in enumerate(seeds)) + "\n",
        encoding="utf-8",
    )


def _build_autogrow4_command(config_file: str, executable: list[str]) -> list[str]:
    return [*executable, "-j", config_file]


def _write_autogrow4_config(
    config_file: Path,
    request: AutoGrow4Request,
    *,
    receptor_file: str,
    seeds_file: str,
    output_dir: str,
    obabel_path: str = "obabel",
    docking_executable: str | None = None,
) -> dict[str, Any]:
    config = _autogrow4_config(
        request,
        receptor_file=receptor_file,
        seeds_file=seeds_file,
        output_dir=output_dir,
        obabel_path=obabel_path,
        docking_executable=docking_executable,
    )
    config_file.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return config


def _autogrow4_config(
    request: AutoGrow4Request,
    *,
    receptor_file: str,
    seeds_file: str,
    output_dir: str,
    obabel_path: str = "obabel",
    docking_executable: str | None = None,
) -> dict[str, Any]:
    center, size = _grid_values(request) or ([0.0, 0.0, 0.0], [20.0, 20.0, 20.0])
    evolution = build_evolution_plan(request)
    intensity = str(request.constraints.get("search_intensity", "normal"))
    docking_profile = autogrow_profile(intensity)
    processor_count = _bounded_int(
        request.constraints.get("number_of_processors"),
        1,
        16,
        docking_profile["processors"],
    )
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
        "number_of_mutants": evolution.later_generation_mutants,
        "number_of_crossovers": evolution.later_generation_crossovers,
        "number_of_mutants_first_generation": evolution.first_generation_mutants,
        "number_of_crossovers_first_generation": evolution.first_generation_crossovers,
        "number_elitism_advance_from_previous_gen": evolution.later_generation_elites,
        "number_elitism_advance_from_previous_gen_first_generation": 0,
        "top_mols_to_seed_next_generation": evolution.parent_count,
        "top_mols_to_seed_next_generation_first_generation": evolution.parent_count,
        "diversity_mols_to_seed_first_generation": 0,
        "selector_choice": "Rank_Selector",
        "num_generations": request.num_generations,
        "start_a_new_run": True,
        "use_docked_source_compounds": False,
        "multithread_mode": "multithreading" if processor_count > 1 else "serial",
        "number_of_processors": processor_count,
        "docking_exhaustiveness": docking_profile["exhaustiveness"],
        "docking_timeout_limit": docking_profile["timeout"],
        "dock_choice": "VinaGpuBatchDocking",
        "docking_executable": docking_executable,
        "scoring_choice": "VINA",
        "conversion_choice": "ObabelConversion",
        "obabel_path": obabel_path,
    }


def _parse_autogrow4_output(
    output_dir: Path, *, generated_only: bool = False
) -> tuple[list[str], list[float | None]]:
    ranked_files = sorted(output_dir.rglob("*_ranked.smi"), key=_ranked_file_sort_key, reverse=True)
    collected: dict[str, float | None] = {}
    for ranked in ranked_files:
        generation = _generation_number(ranked)
        if generated_only and (generation is None or generation < 1):
            continue
        smiles, scores = _parse_ranked_smi(ranked)
        for index, value in enumerate(smiles):
            if value not in collected:
                collected[value] = scores[index] if index < len(scores) else None
    return list(collected), list(collected.values())


def _parse_ranked_smi(path: Path) -> tuple[list[str], list[float | None]]:
    smiles: list[str] = []
    scores: list[float | None] = []
    for row in csv.reader(
        path.read_text(encoding="utf-8", errors="replace").splitlines(), delimiter="\t"
    ):
        if not row or not row[0].strip() or row[0].lower().strip() in {"smiles", "id"}:
            continue
        smiles.append(row[0].strip())
        scores.append(_first_float(row[2:]))
    return smiles, scores


def _has_completed_generation_output(
    output_dir: Path,
    request: AutoGrow4Request,
    gpu_provenance: dict[str, Any] | None = None,
) -> bool:
    requested_generations = set(range(1, max(request.num_generations, 1) + 1))
    provenance = gpu_provenance or _vina_gpu_provenance(output_dir)
    gpu_generations = set(provenance.get("successful_generations", [])) if provenance else set()
    return (
        requested_generations <= _ranked_generations(output_dir)
        and requested_generations <= gpu_generations
    )


def _ranked_generations(output_dir: Path) -> set[int]:
    return {
        generation
        for path in output_dir.rglob("*_ranked.smi")
        if (generation := _generation_number(path)) is not None
        and generation >= 1
        and bool(_parse_ranked_smi(path)[0])
    }


def _autogrow4_warnings(
    exit_code: int | None,
    smiles: list[str],
    scores: list[float | None],
    *,
    source_only_output: bool = False,
) -> list[str]:
    if source_only_output:
        return ["autogrow4_generated_generation_missing"]
    if exit_code not in {0, None} and smiles:
        return ["autogrow4_partial_generation_output"]
    if exit_code not in {0, None}:
        return ["autogrow4_execution_failed"]
    if not smiles:
        return ["autogrow4_generated_generation_missing"]
    if not any(score is not None for score in scores):
        return ["autogrow4_ranked_scores_missing"]
    return []


def _gpu_policy_is_valid(request: AutoGrow4Request) -> bool:
    constraints = request.constraints or {}
    try:
        gpu_id = int(constraints.get("gpu_id", 0) or 0)
    except (TypeError, ValueError):
        return False
    return (
        constraints.get("docking_backend", "vina_gpu_2_1_batch") == "vina_gpu_2_1_batch"
        and bool(constraints.get("gpu_required", True))
        and not bool(constraints.get("cpu_fallback", False))
        and gpu_id == 0
    )


def _vina_gpu_provenance(output_dir: Path) -> dict[str, Any] | None:
    files: list[dict[str, Any]] = []
    successful_generations: set[int] = set()
    record_count = 0
    for path in sorted(output_dir.rglob("vina_gpu_batches.jsonl")):
        generation = _generation_number(path)
        records: list[dict[str, Any]] = []
        parse_error = False
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                parse_error = True
                continue
            if isinstance(payload, dict):
                records.append(payload)
            else:
                parse_error = True
        if not records:
            continue
        record_count += len(records)
        successful = not parse_error and all(
            _successful_vina_gpu_record(record) for record in records
        )
        if successful and generation is not None:
            successful_generations.add(generation)
        files.append(
            {
                "path": str(path),
                "generation": generation,
                "record_count": len(records),
                "parse_error": parse_error,
                "successful": successful,
            }
        )
    if not files:
        return None
    return {
        "path": files[0]["path"],
        "batch_count": record_count,
        "files": files,
        "successful_generations": sorted(successful_generations),
    }


def _successful_vina_gpu_record(record: dict[str, Any]) -> bool:
    batches = record.get("batches")
    if not isinstance(batches, list) or not batches:
        return False
    failure = record.get("failure")
    if (
        record.get("adapter_mode") != "vina_gpu_2_1_batch"
        or record.get("cpu_fallback_enabled") is not False
        or record.get("gpu_id") != 0
        or (failure is not None and failure != "")
    ):
        return False
    if record.get("failed_smiles_names") not in (None, []):
        return False
    requested_count = record.get("requested_count")
    try:
        requested = int(requested_count)
    except (TypeError, ValueError):
        return False
    successful = 0
    for batch in batches:
        if not isinstance(batch, dict):
            return False
        try:
            input_count = int(batch.get("input_count"))
            success_count = int(batch.get("success_count"))
        except (TypeError, ValueError):
            return False
        if input_count <= 0 or success_count < 0 or success_count > input_count:
            return False
        if batch.get("exit_code") == 0:
            successful += success_count
        elif success_count != 0:
            return False
    return requested > 0 and successful == requested


def _effective_timeout_seconds(
    request: AutoGrow4Request, environment: dict[str, str]
) -> int:
    """Keep the host timeout outside every configured GPU wait/retry budget."""
    wait_timeout = _bounded_int(
        environment.get("MEDAGENT_VINA_GPU_WAIT_TIMEOUT_SECONDS"), 0, 86400, 300
    )
    batch_timeout = _bounded_int(
        environment.get("MEDAGENT_VINA_GPU_BATCH_TIMEOUT_SECONDS"), 1, 86400, 1800
    )
    retry_count = _bounded_int(
        environment.get("MEDAGENT_VINA_GPU_RETRY_COUNT"), 0, 10, 1
    )
    max_batch_size = _bounded_int(
        environment.get("MEDAGENT_VINA_GPU_MAX_BATCH_SIZE"), 1, 10000, 128
    )
    evolution = build_evolution_plan(request)
    generations = max(int(request.num_generations), 1)
    first_chunks = int(math.ceil(evolution.population_size / max_batch_size))
    later_size = (
        evolution.later_generation_mutants
        + evolution.later_generation_crossovers
        + evolution.later_generation_elites
    )
    later_chunks = int(math.ceil(max(later_size, 1) / max_batch_size))
    total_chunks = first_chunks + max(generations - 1, 0) * later_chunks
    internal_budget = (
        generations * wait_timeout
        + total_chunks * batch_timeout * (retry_count + 1)
        + 300
    )
    return max(int(request.timeout_seconds), internal_budget)


def _provenance(
    request: AutoGrow4Request,
    command: list[str],
    config: dict[str, Any],
    execution_mode: str = "local_python",
    output_dir: Path | None = None,
) -> dict[str, Any]:
    artifact_root = output_dir or Path(request.output_dir)
    return {
        "execution_mode": execution_mode,
        "command": command,
        "config": config,
        "configured_output_root": request.output_dir,
        "raw_output_dir": str(artifact_root),
        "input_artifacts": {
            "receptor_pdb": _artifact_record(Path(request.receptor_file).expanduser())
        },
        "output_artifacts": _artifact_inventory(artifact_root),
        "score_semantics": "autogrow4_ranked_output_fitness",
        "requested_count": request.population_size,
        "seed_count": len(request.seed_smiles),
        "evolution_plan": vars(build_evolution_plan(request)),
    }


def _artifact_record(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "path": str(path.resolve()),
        "sha256": digest.hexdigest(),
        "size_bytes": path.stat().st_size,
    }


def _artifact_inventory(root: Path) -> list[dict[str, Any]]:
    if not root.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        record = _artifact_record(path)
        if record is not None:
            record["relative_path"] = path.relative_to(root).as_posix()
            records.append(record)
    return records


def _grid_values(request: AutoGrow4Request) -> tuple[list[float], list[float]] | None:
    center, size = request.constraints.get("grid_center"), request.constraints.get("grid_size")
    if (
        not isinstance(center, list)
        or not isinstance(size, list)
        or len(center) != 3
        or len(size) != 3
    ):
        return None
    try:
        return [float(value) for value in center], [float(value) for value in size]
    except (TypeError, ValueError):
        return None


def _missing_local_dependencies() -> list[str]:
    return [
        name
        for name in ("vina", "obabel")
        if shutil.which(name) is None and not _configured_dependency_exists(name)
    ]


def _configured_dependency_exists(name: str) -> bool:
    config = get_tool_runtime_config(name, default_command=name, default_timeout_seconds=120)
    path = resolve_configured_path(config.command)
    return bool(path and path.is_file())


def _local_python(configured: str | None) -> str | None:
    path = resolve_configured_path(configured)
    return str(path) if path and path.is_file() else None


def _script_path(command: str | None, workdir: str | None) -> Path | None:
    if not command:
        return None
    root = resolve_configured_path(workdir)
    candidate = (
        (root / command).resolve() if root and root.is_dir() else resolve_configured_path(command)
    )
    return candidate if candidate and candidate.is_file() else None


def _missing_autogrow_runtime_extensions(source_dir: Path | None) -> list[str]:
    if source_dir is None or not source_dir.is_dir():
        return ["autogrow4_source_directory"]
    requirements = {
        "vina_gpu_batch_docking": (
            source_dir
            / "autogrow/docking/docking_class/docking_class_children/vina_gpu_batch_docking.py",
            'adapter_mode = "vina_gpu_2_1_batch"',
        ),
        "generation_batch_dispatch": (
            source_dir / "autogrow/docking/execute_docking.py",
            'hasattr(docking_object, "run_batch_dock")',
        ),
        "crossover_mutation_fill": (
            source_dir / "autogrow/operators/operations.py",
            "Attempting to fill the gap with {} extra mutations.",
        ),
        "bounded_crossover_attempts": (
            source_dir / "autogrow/operators/crossover/execute_crossover.py",
            "MAX_CROSSOVER_ATTEMPTS = 200",
        ),
    }
    missing: list[str] = []
    for name, (path, marker) in requirements.items():
        if not path.is_file() or marker not in path.read_text(
            encoding="utf-8", errors="replace"
        ):
            missing.append(name)
    return missing


def _generation_number(path: Path) -> int | None:
    import re

    # AutoGrow names both the ranked file and its immediate directory after
    # the generation.  Inspect those local components first so an unrelated
    # ancestor such as a project or pytest directory cannot shadow the real
    # generation number.
    for component in (path.name, *reversed(path.parent.parts)):
        match = re.search(r"(?:^|_)generation_(\d+)(?:_|\.|$)", component, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _ranked_file_sort_key(path: Path) -> tuple[int, str]:
    return _generation_number(path) or 0, str(path)


def _first_float(values: list[str]) -> float | None:
    for value in values:
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _bounded_float(value: Any, minimum: float, maximum: float, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(parsed, maximum)) if math.isfinite(parsed) else default


def _bounded_int(value: Any, minimum: int, maximum: int, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))
