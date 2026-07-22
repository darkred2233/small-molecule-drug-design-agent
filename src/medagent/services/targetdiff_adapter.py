"""Local TargetDiff runtime adapter.

TargetDiff remains in a dedicated local environment because of its pinned
PyTorch/PyG stack.  The adapter records the raw output directory and only
returns RDKit-readable structures; generated coordinates are hypotheses, not
docking evidence.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from medagent.services.tool_config import configured_paths_exist, get_tool_runtime_config, resolve_configured_path


@dataclass(frozen=True)
class TargetDiffRequest:
    pocket_file: str
    output_dir: str
    num_samples: int = 20
    timeout_seconds: int = 1800


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
    config = get_tool_runtime_config("targetdiff", default_timeout_seconds=1800)
    files_ready, missing_paths = configured_paths_exist(config)
    python = resolve_configured_path(config.python_executable)
    source_dir = resolve_configured_path(config.working_directory)
    entrypoint = _entrypoint(config.command, source_dir)
    result: dict[str, Any] = {
        "available": False, "runtime_available": False, "mode": "local_python",
        "python_executable": str(python) if python and python.is_file() else None,
        "source_dir": str(source_dir) if source_dir and source_dir.is_dir() else None,
        "entrypoint": str(entrypoint) if entrypoint else None, "missing_paths": missing_paths,
        "warning": None, **config.as_status(),
    }
    if not files_ready:
        result["warning"] = "targetdiff_required_files_missing"
        return result
    if python is None or not python.is_file():
        result["warning"] = "targetdiff_local_python_not_found"
        return result
    if entrypoint is None:
        result["warning"] = "targetdiff_entrypoint_not_found"
        return result
    try:
        probe = subprocess.run([str(python), str(entrypoint), "--help"], capture_output=True, text=True, timeout=45, cwd=str(entrypoint.parent), check=False)
    except (OSError, subprocess.TimeoutExpired):
        result["warning"] = "targetdiff_local_runtime_probe_failed"
        return result
    result["runtime_available"] = probe.returncode == 0
    result["available"] = probe.returncode == 0
    if not result["available"]:
        result["warning"] = "targetdiff_local_runtime_probe_failed"
    return result


def run_targetdiff_generation(request: TargetDiffRequest, status: dict[str, Any] | None = None) -> TargetDiffResult:
    started = time.monotonic()
    status = status or targetdiff_tool_status()
    if not status.get("available"):
        return TargetDiffResult("targetdiff_unavailable", "targetdiff", False, warnings=[str(status.get("warning") or "targetdiff_not_installed")])
    pocket = Path(request.pocket_file).expanduser()
    if not pocket.is_file() or pocket.suffix.lower() != ".pdb":
        return TargetDiffResult("targetdiff_pocket_missing", "targetdiff", False, warnings=["targetdiff_pocket_pdb_required"])
    output_dir = Path(request.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    python, entrypoint = str(status["python_executable"]), str(status["entrypoint"])
    command = [python, entrypoint, "--pdb_path", str(pocket.resolve()), "--out_dir", str(output_dir), "--num_samples", str(max(1, request.num_samples))]
    try:
        process = subprocess.run(command, capture_output=True, text=True, timeout=request.timeout_seconds, cwd=str(Path(entrypoint).parent), check=False)
    except subprocess.TimeoutExpired:
        return TargetDiffResult("targetdiff_timeout", "targetdiff", False, warnings=["targetdiff_execution_timeout"], runtime_seconds=time.monotonic() - started, provenance=_provenance(request, command))
    except OSError as exc:
        return TargetDiffResult("targetdiff_execution_os_error", "targetdiff", False, warnings=[f"targetdiff_execution_os_error:{type(exc).__name__}"], runtime_seconds=time.monotonic() - started, provenance=_provenance(request, command))
    smiles = _read_generated_smiles(output_dir)
    success = process.returncode == 0 and bool(smiles)
    warnings = [] if success else ["targetdiff_generation_output_missing" if process.returncode == 0 else "targetdiff_execution_failed"]
    return TargetDiffResult("targetdiff_local_generation", "targetdiff", success, generated_smiles=smiles, labels=["targetdiff_generation_pose", "targetdiff_rdkit_validated"] if success else [], warnings=warnings, stdout=process.stdout[:4000], stderr=process.stderr[:4000], exit_code=process.returncode, runtime_seconds=time.monotonic() - started, provenance=_provenance(request, command))


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
    candidate = (source_dir / command).resolve() if source_dir and source_dir.is_dir() else resolve_configured_path(command)
    return candidate if candidate and candidate.is_file() else None


def _provenance(request: TargetDiffRequest, command: list[str]) -> dict[str, Any]:
    return {"execution_mode": "local_python", "command": command, "pocket_file": request.pocket_file, "raw_output_dir": request.output_dir, "generated_pose_is_docking_evidence": False}
