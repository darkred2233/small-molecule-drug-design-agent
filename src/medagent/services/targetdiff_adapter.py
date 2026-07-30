"""Local TargetDiff runtime adapter.

TargetDiff remains in a dedicated local environment because of its pinned
PyTorch/PyG stack.  The adapter records the raw output directory and only
returns RDKit-readable structures; generated coordinates are hypotheses, not
docking evidence.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
import hashlib
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
class TargetDiffRequest:
    pocket_file: str
    output_dir: str
    num_samples: int = 20
    timeout_seconds: int = 2700
    batch_size: int = 25


@dataclass
class TargetDiffResult:
    adapter_mode: str
    tool_name: str
    success: bool
    generated_smiles: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    runtime_seconds: float = 0.0
    provenance: dict[str, Any] = field(default_factory=dict)


def targetdiff_tool_status() -> dict[str, Any]:
    config = get_tool_runtime_config("targetdiff", default_timeout_seconds=2700)
    files_ready, missing_paths = configured_paths_exist(config)
    source_dir = resolve_configured_path(config.working_directory)
    entrypoint = _entrypoint(config.command, source_dir)
    sampling_config = source_dir / "configs" / "sampling.yml" if source_dir else None
    is_wsl = config.runtime == "wsl"
    if is_wsl:
        python = (
            config.python_executable
            if config.python_executable
            and wsl_file_exists(
                config.python_executable,
                distribution=config.wsl_distribution,
                user=config.wsl_user,
            )
            else None
        )
    else:
        local_python = resolve_configured_path(config.python_executable)
        python = str(local_python) if local_python and local_python.is_file() else None
    source_dir_wsl = windows_path_to_wsl(source_dir) if source_dir else None
    entrypoint_wsl = windows_path_to_wsl(entrypoint) if entrypoint else None
    sampling_config_wsl = windows_path_to_wsl(sampling_config) if sampling_config else None
    result: dict[str, Any] = {
        "available": False,
        "runtime_available": False,
        "mode": "wsl_python" if is_wsl else "local_python",
        "python_executable": python,
        "source_dir": str(source_dir) if source_dir and source_dir.is_dir() else None,
        "source_dir_wsl": source_dir_wsl if is_wsl else None,
        "entrypoint": str(entrypoint) if entrypoint else None,
        "entrypoint_wsl": entrypoint_wsl if is_wsl else None,
        "sampling_config": str(sampling_config) if sampling_config else None,
        "sampling_config_wsl": sampling_config_wsl if is_wsl else None,
        "missing_paths": missing_paths,
        "warning": None,
        **config.as_status(),
    }
    if not files_ready:
        result["warning"] = "targetdiff_required_files_missing"
        return result
    if python is None:
        result["warning"] = "targetdiff_local_python_not_found"
        return result
    if entrypoint is None or sampling_config is None or not sampling_config.is_file():
        result["warning"] = "targetdiff_entrypoint_not_found"
        return result
    try:
        probe_command = [str(python), str(entrypoint), "--help"]
        probe_cwd = str(source_dir)
        probe_environment = _targetdiff_environment(source_dir)
        if is_wsl:
            assert source_dir_wsl is not None and entrypoint_wsl is not None
            probe_command = build_wsl_command(
                [str(python), entrypoint_wsl, "--help"],
                distribution=config.wsl_distribution,
                user=config.wsl_user,
                cwd=source_dir_wsl,
                environment={"PYTHONPATH": source_dir_wsl},
            )
            probe_cwd = None
            probe_environment = None
        probe = subprocess.run(
            probe_command,
            capture_output=True,
            text=True,
            encoding="utf-8" if is_wsl else None,
            errors="replace" if is_wsl else None,
            timeout=45,
            cwd=probe_cwd,
            env=probe_environment,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        result["warning"] = "targetdiff_local_runtime_probe_failed"
        return result
    result["runtime_available"] = probe.returncode == 0
    result["available"] = probe.returncode == 0
    if not result["available"]:
        result["warning"] = "targetdiff_local_runtime_probe_failed"
    return result


def run_targetdiff_generation(
    request: TargetDiffRequest, status: dict[str, Any] | None = None
) -> TargetDiffResult:
    started = time.monotonic()
    status = status or targetdiff_tool_status()
    if not status.get("available"):
        return TargetDiffResult(
            "targetdiff_unavailable",
            "targetdiff",
            False,
            warnings=[str(status.get("warning") or "targetdiff_not_installed")],
        )
    pocket = Path(request.pocket_file).expanduser()
    if not pocket.is_file() or pocket.suffix.lower() != ".pdb":
        return TargetDiffResult(
            "targetdiff_pocket_missing",
            "targetdiff",
            False,
            warnings=["targetdiff_pocket_pdb_required"],
        )
    output_root = Path(request.output_dir).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    output_dir = Path(tempfile.mkdtemp(prefix="attempt-", dir=output_root))
    python, entrypoint = str(status["python_executable"]), str(status["entrypoint"])
    source_dir = str(Path(entrypoint).parents[1])
    sampling_config = str(
        status.get("sampling_config") or Path(source_dir) / "configs" / "sampling.yml"
    )
    command = [
        python,
        entrypoint,
        sampling_config,
        "--pdb_path",
        str(pocket.resolve()),
        "--result_path",
        str(output_dir),
        "--num_samples",
        str(max(1, request.num_samples)),
        "--batch_size",
        str(max(1, request.batch_size)),
    ]
    execution_mode = "local_python"
    process_cwd: str | None = source_dir
    process_environment = _targetdiff_environment(Path(source_dir))
    if status.get("runtime_scope") == "wsl":
        source_dir_wsl = str(status["source_dir_wsl"])
        command = build_wsl_command(
            [
                python,
                str(status["entrypoint_wsl"]),
                str(status["sampling_config_wsl"]),
                "--pdb_path",
                windows_path_to_wsl(str(pocket.resolve())),
                "--result_path",
                windows_path_to_wsl(str(output_dir)),
                "--num_samples",
                str(max(1, request.num_samples)),
                "--batch_size",
                str(max(1, request.batch_size)),
            ],
            distribution=str(status.get("wsl_distribution") or "Ubuntu"),
            user=str(status.get("wsl_user") or "root"),
            cwd=source_dir_wsl,
            environment={"PYTHONPATH": source_dir_wsl},
        )
        execution_mode = "wsl_python"
        process_cwd = None
        process_environment = None
    try:
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8" if execution_mode == "wsl_python" else None,
            errors="replace" if execution_mode == "wsl_python" else None,
            timeout=request.timeout_seconds,
            cwd=process_cwd,
            env=process_environment,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return TargetDiffResult(
            "targetdiff_timeout",
            "targetdiff",
            False,
            warnings=["targetdiff_execution_timeout"],
            stderr=str(exc)[:4000],
            runtime_seconds=time.monotonic() - started,
            provenance=_provenance(request, command, execution_mode, output_dir),
        )
    except OSError as exc:
        return TargetDiffResult(
            "targetdiff_execution_os_error",
            "targetdiff",
            False,
            warnings=[f"targetdiff_execution_os_error:{type(exc).__name__}"],
            stderr=str(exc)[:4000],
            runtime_seconds=time.monotonic() - started,
            provenance=_provenance(request, command, execution_mode, output_dir),
        )
    smiles = _read_generated_smiles(output_dir)
    success = process.returncode == 0 and bool(smiles)
    warnings = (
        []
        if success
        else [
            "targetdiff_generation_output_missing"
            if process.returncode == 0
            else "targetdiff_execution_failed"
        ]
    )
    return TargetDiffResult(
        "targetdiff_local_generation",
        "targetdiff",
        success,
        generated_smiles=smiles,
        labels=["targetdiff_generation_pose", "targetdiff_rdkit_validated"] if success else [],
        warnings=warnings,
        stdout=process.stdout[:4000],
        stderr=process.stderr[:4000],
        exit_code=process.returncode,
        runtime_seconds=time.monotonic() - started,
        provenance=_provenance(request, command, execution_mode, output_dir),
    )


def _read_generated_smiles(output_dir: Path) -> list[str]:
    try:
        from rdkit import Chem
    except ImportError:
        return []
    smiles: list[str] = []
    seen: set[str] = set()
    for sdf in output_dir.rglob("*.sdf"):
        try:
            supplier = Chem.SDMolSupplier(str(sdf), removeHs=True)
            for molecule in supplier:
                if molecule is None:
                    continue
                value = Chem.MolToSmiles(molecule, canonical=True)
                if value and value not in seen:
                    seen.add(value)
                    smiles.append(value)
        except OSError:
            continue
    return smiles


def _entrypoint(command: str | None, source_dir: Path | None) -> Path | None:
    if not command:
        return None
    candidate = (
        (source_dir / command).resolve()
        if source_dir and source_dir.is_dir()
        else resolve_configured_path(command)
    )
    return candidate if candidate and candidate.is_file() else None


def _targetdiff_environment(source_dir: Path) -> dict[str, str]:
    environment = os.environ.copy()
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        f"{source_dir}{os.pathsep}{existing_pythonpath}"
        if existing_pythonpath
        else str(source_dir)
    )
    # Keep the model away from an already saturated second GPU by default.
    environment.setdefault(
        "CUDA_VISIBLE_DEVICES",
        environment.get("MEDAGENT_TARGETDIFF_CUDA_VISIBLE_DEVICES", "0"),
    )
    return environment


def _provenance(
    request: TargetDiffRequest,
    command: list[str],
    execution_mode: str = "local_python",
    output_dir: Path | None = None,
) -> dict[str, Any]:
    artifact_root = output_dir or Path(request.output_dir)
    return {
        "execution_mode": execution_mode,
        "command": command,
        "pocket_file": request.pocket_file,
        "configured_output_root": request.output_dir,
        "num_samples": max(1, request.num_samples),
        "batch_size": max(1, request.batch_size),
        "raw_output_dir": str(artifact_root),
        "input_artifacts": {
            "pocket_pdb": _artifact_record(Path(request.pocket_file).expanduser())
        },
        "output_artifacts": _artifact_inventory(artifact_root),
        "generated_pose_is_docking_evidence": False,
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
