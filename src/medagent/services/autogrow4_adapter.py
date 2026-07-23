"""Local AutoGrow4 adapter.

AutoGrow4 is run from a checkout and an isolated Python interpreter.  No
synthetic candidate fallback is produced when the local tool is unavailable.
"""

from __future__ import annotations

import csv
import json
import math
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


@dataclass(frozen=True)
class AutoGrow4Request:
    seed_smiles: list[str]
    receptor_file: str
    output_dir: str
    num_generations: int = 10
    population_size: int = 50
    optimization_mode: str = "genetic"
    constraints: dict[str, Any] = field(default_factory=dict)
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


def check_autogrow4_available() -> dict[str, Any]:
    config = get_tool_runtime_config("autogrow4", default_timeout_seconds=1200)
    required_ready, missing_paths = configured_paths_exist(config)
    script = _script_path(config.command, config.working_directory)
    source_dir = resolve_configured_path(config.working_directory)
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
        "warning": None,
        **config.as_status(),
    }
    if not required_ready:
        result["warning"] = "autogrow4_required_files_missing"
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

    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="autogrow4_") as temporary:
        root = Path(temporary)
        seeds_file, config_file, generated_dir = (
            root / "seeds.smi",
            root / "config.json",
            root / "output",
        )
        _write_seed_smiles(seeds_file, request.seed_smiles)
        generated_dir.mkdir()
        receptor_file = str(receptor.resolve())
        seeds_path = str(seeds_file)
        generated_path = str(generated_dir)
        if is_wsl:
            receptor_file = windows_path_to_wsl(receptor_file)
            seeds_path = windows_path_to_wsl(seeds_path)
            generated_path = windows_path_to_wsl(generated_path)
        config = _write_autogrow4_config(
            config_file,
            request,
            receptor_file=receptor_file,
            seeds_file=seeds_path,
            output_dir=generated_path,
            obabel_path=str(status.get("obabel_path") or "obabel"),
        )
        command = _build_autogrow4_command(
            config_file=str(config_file), executable=[python, str(script)]
        )
        execution_mode = "local_python"
        process_cwd: str | None = str(script.parent)
        if is_wsl:
            source_dir_wsl = str(status["source_dir_wsl"])
            command = _build_autogrow4_command(
                config_file=windows_path_to_wsl(str(config_file)),
                executable=[python, str(status["script_wsl"])],
            )
            command = build_wsl_command(
                command,
                distribution=str(status.get("wsl_distribution") or "Ubuntu"),
                user=str(status.get("wsl_user") or "root"),
                cwd=source_dir_wsl,
                environment={"PYTHONPATH": source_dir_wsl},
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
                timeout=request.timeout_seconds,
                cwd=process_cwd,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return AutoGrow4Result(
                "autogrow4_timeout",
                "autogrow4",
                False,
                warnings=["autogrow4_execution_timeout"],
                exit_code=None,
                runtime_seconds=time.monotonic() - started,
                provenance=_provenance(request, command, config, execution_mode),
            )
        except OSError as exc:
            return AutoGrow4Result(
                "autogrow4_execution_os_error",
                "autogrow4",
                False,
                warnings=[f"autogrow4_execution_os_error:{type(exc).__name__}"],
                exit_code=None,
                runtime_seconds=time.monotonic() - started,
                provenance=_provenance(request, command, config, execution_mode),
            )

        smiles, scores = _parse_autogrow4_output(generated_dir, generated_only=True)
        destination = Path(request.output_dir)
        destination.mkdir(parents=True, exist_ok=True)
        if generated_dir.exists():
            shutil.copytree(generated_dir, destination, dirs_exist_ok=True)
        completed = (
            process.returncode == 0
            and _has_completed_generation_output(generated_dir, request)
            and bool(smiles)
        )
        warnings = _autogrow4_warnings(
            process.returncode, smiles, scores, source_only_output=bool(smiles) and not completed
        )
        return AutoGrow4Result(
            "autogrow4_local_generation",
            "autogrow4",
            completed,
            generated_smiles=smiles,
            scores=scores,
            labels=["autogrow4_local_executed"] if completed else [],
            warnings=warnings,
            stdout=process.stdout[:4000],
            stderr=process.stderr[:4000],
            exit_code=process.returncode,
            runtime_seconds=time.monotonic() - started,
            provenance=_provenance(request, command, config, execution_mode),
        )


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
) -> dict[str, Any]:
    config = _autogrow4_config(
        request,
        receptor_file=receptor_file,
        seeds_file=seeds_file,
        output_dir=output_dir,
        obabel_path=obabel_path,
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
) -> dict[str, Any]:
    center, size = _grid_values(request) or ([0.0, 0.0, 0.0], [20.0, 20.0, 20.0])
    crossover = _bounded_float(request.constraints.get("crossover_fraction", 0.5), 0.0, 1.0, 0.5)
    population_size = max(int(request.population_size), 1)
    crossover_count = int(round(population_size * crossover))
    if len(request.seed_smiles) < 2:
        crossover_count = 0
    mutant_count = population_size - crossover_count
    seed_count = max(1, min(len(request.seed_smiles), population_size))
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
        "number_of_mutants": mutant_count,
        "number_of_crossovers": crossover_count,
        "number_of_mutants_first_generation": mutant_count,
        "number_of_crossovers_first_generation": crossover_count,
        "number_elitism_advance_from_previous_gen": 0,
        "number_elitism_advance_from_previous_gen_first_generation": 0,
        "top_mols_to_seed_next_generation": seed_count,
        "top_mols_to_seed_next_generation_first_generation": seed_count,
        "diversity_mols_to_seed_first_generation": 0,
        "num_generations": request.num_generations,
        "start_a_new_run": True,
        "use_docked_source_compounds": True,
        "multithread_mode": "serial",
        "number_of_processors": 1,
        "dock_choice": "VinaDocking",
        "scoring_choice": "VINA",
        "conversion_choice": "ObabelConversion",
        "obabel_path": obabel_path,
    }


def _parse_autogrow4_output(
    output_dir: Path, *, generated_only: bool = False
) -> tuple[list[str], list[float | None]]:
    ranked_files = sorted(output_dir.rglob("*_ranked.smi"), key=_ranked_file_sort_key, reverse=True)
    for ranked in ranked_files:
        generation = _generation_number(ranked)
        if generated_only and (generation is None or generation < 1):
            continue
        smiles, scores = _parse_ranked_smi(ranked)
        if smiles:
            return smiles, scores
    return [], []


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


def _has_completed_generation_output(output_dir: Path, request: AutoGrow4Request) -> bool:
    highest_generation = max(
        (_generation_number(path) or 0 for path in output_dir.rglob("*_ranked.smi")), default=0
    )
    return highest_generation >= max(request.num_generations, 1)


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


def _provenance(
    request: AutoGrow4Request,
    command: list[str],
    config: dict[str, Any],
    execution_mode: str = "local_python",
) -> dict[str, Any]:
    return {
        "execution_mode": execution_mode,
        "command": command,
        "config": config,
        "score_semantics": "autogrow4_ranked_output_fitness",
        "requested_count": len(request.seed_smiles),
    }


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


def _generation_number(path: Path) -> int | None:
    import re

    match = re.search(r"generation_(\d+)", str(path).replace("\\", "/"), re.IGNORECASE)
    return int(match.group(1)) if match else None


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
