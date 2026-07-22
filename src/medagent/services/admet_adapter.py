"""Local ADMET prediction adapter.

The preferred runtime is ADMET-AI's bundled Chemprop ensemble.  A separately
installed local Chemprop CLI is supported for project-owned checkpoints.  This
module never starts a container and never substitutes fabricated predictions
for a failed external model run.
"""

from __future__ import annotations

import contextlib
import csv
import importlib.metadata
import importlib.util
import io
import math
import os
import shutil
import subprocess
import tempfile
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_ADMET_AI_MODEL_CACHE: dict[str | None, Any] = {}
_RISK_THRESHOLDS = {
    "hERG": {"high": 0.7, "medium": 0.4},
    "Ames": {"high": 0.7, "medium": 0.4},
    "CYP3A4": {"high": 0.7, "medium": 0.4},
    "CYP2D6": {"high": 0.7, "medium": 0.4},
    "DILI": {"high": 0.7, "medium": 0.4},
    "Pgp": {"high": 0.7, "medium": 0.4},
    "BBB": {"high": 0.7, "medium": 0.4},
}


@dataclass(frozen=True)
class ChempropADMETRequest:
    smiles_list: list[str]
    molecule_ids: list[str]
    properties: list[str] = field(default_factory=lambda: [
        "hERG", "Ames", "CYP3A4", "CYP2D6", "solubility",
        "permeability", "DILI", "Pgp", "BBB",
    ])
    checkpoint_dir: str | None = None
    timeout_seconds: int = 300


@dataclass
class SingleADMETResult:
    molecule_id: str
    smiles: str
    hERG_probability: float | None = None
    hERG_risk: str | None = None
    Ames_probability: float | None = None
    Ames_risk: str | None = None
    CYP3A4_inhibition: float | None = None
    CYP3A4_risk: str | None = None
    CYP2D6_inhibition: float | None = None
    CYP2D6_risk: str | None = None
    solubility: str | None = None
    solubility_score: float | None = None
    permeability: str | None = None
    permeability_score: float | None = None
    DILI_probability: float | None = None
    DILI_risk: str | None = None
    Pgp_substrate: float | None = None
    Pgp_risk: str | None = None
    BBB_penetration: float | None = None
    BBB_risk: str | None = None
    admet_risk_score: float | None = None
    labels: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class ChempropADMETOutput:
    adapter_mode: str
    tool_name: str
    success: bool
    results: list[SingleADMETResult] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    runtime_seconds: float = 0.0
    compute_device: str | None = None


def _check_admet_ai_available() -> dict[str, Any] | None:
    spec = importlib.util.find_spec("admet_ai")
    if spec is None or spec.origin is None:
        return None
    models_dir = Path(spec.origin).parent / "resources" / "models"
    if not all((models_dir / name).is_dir() for name in ("admet_classification", "admet_regression")):
        return None
    model_files = list(models_dir.rglob("*.pt"))
    if not model_files:
        return None
    try:
        version = importlib.metadata.version("admet-ai")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"
    try:
        import torch

        gpu_available = bool(torch.cuda.is_available())
    except (ImportError, RuntimeError):
        gpu_available = False
    return {
        "version": version,
        "models_dir": str(models_dir),
        "model_count": len(model_files),
        "gpu_available": gpu_available,
        "device": "cuda" if gpu_available else "cpu",
    }


def _check_chemprop_cli() -> dict[str, Any] | None:
    path = shutil.which("chemprop")
    if path is None:
        return None
    try:
        probe = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return {"path": path, "version": "unknown", "warning": "chemprop_cli_version_unavailable"}
    return {
        "path": path,
        "version": (probe.stdout or probe.stderr).strip() or "unknown",
        "warning": None if probe.returncode == 0 else "chemprop_cli_version_unavailable",
    }


def check_chemprop_available() -> dict[str, Any]:
    """Return a status for a real project-local ADMET runtime."""
    result: dict[str, Any] = {
        "available": False,
        "mode": None,
        "version": None,
        "path": None,
        "models_dir": None,
        "model_count": None,
        "model_configured": False,
        "runtime_available": False,
        "gpu_available": False,
        "device": None,
        "warning": None,
    }
    admet_ai_status = _check_admet_ai_available()
    if admet_ai_status:
        return {
            **result,
            "available": True,
            "mode": "admet_ai",
            "runtime_available": True,
            "model_configured": True,
            **admet_ai_status,
        }
    cli = _check_chemprop_cli()
    if cli is None:
        result["warning"] = "admet_ai_and_local_chemprop_unavailable"
        return result
    checkpoint = os.environ.get("CHEMPROP_CHECKPOINT_DIR")
    checkpoint_dir = Path(checkpoint).expanduser().resolve() if checkpoint else None
    configured = bool(checkpoint_dir and checkpoint_dir.is_dir())
    return {
        **result,
        "available": configured,
        "mode": "local_cli",
        "version": cli["version"],
        "path": cli["path"],
        "runtime_available": True,
        "model_configured": configured,
        "models_dir": str(checkpoint_dir) if configured else None,
        "warning": cli.get("warning") or (None if configured else "chemprop_checkpoint_not_configured"),
    }


def run_chemprop_admet(
    request: ChempropADMETRequest,
    chemprop_status: dict[str, Any] | None = None,
) -> ChempropADMETOutput:
    status = chemprop_status or check_chemprop_available()
    if not status.get("available"):
        return ChempropADMETOutput(
            adapter_mode="chemprop_unavailable",
            tool_name="chemprop",
            success=False,
            warnings=[str(status.get("warning") or "chemprop_not_installed")],
        )
    if status.get("mode") == "admet_ai":
        return _run_admet_ai(request, status)
    return _run_chemprop_local(request, status)


def _run_admet_ai(request: ChempropADMETRequest, status: dict[str, Any]) -> ChempropADMETOutput:
    started = time.monotonic()
    stdout, stderr = io.StringIO(), io.StringIO()
    device = status.get("device")
    models_dir = request.checkpoint_dir or os.environ.get("ADMET_AI_MODELS_DIR") or status.get("models_dir")
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            model = _get_admet_ai_model(models_dir)
            device = str(model.device)
            predictions = model.predict(smiles=request.smiles_list)
    except Exception as exc:
        return ChempropADMETOutput(
            adapter_mode="admet_ai_prediction_failed",
            tool_name="chemprop",
            success=False,
            warnings=[f"admet_ai_prediction_failed:{type(exc).__name__}"],
            stdout=stdout.getvalue()[:2000],
            stderr=stderr.getvalue()[:2000],
            runtime_seconds=time.monotonic() - started,
            compute_device=device,
        )
    results = _parse_admet_ai_predictions(predictions, request.molecule_ids, request.smiles_list)
    return ChempropADMETOutput(
        adapter_mode="admet_ai_local_prediction",
        tool_name="chemprop",
        success=bool(results),
        results=results,
        labels=["chemprop_admet", "admet_ai_local"] if results else ["chemprop_admet", "chemprop_no_results"],
        warnings=[] if results else ["admet_ai_failed_to_predict"],
        stdout=stdout.getvalue()[:2000],
        stderr=stderr.getvalue()[:2000],
        exit_code=0 if results else None,
        runtime_seconds=time.monotonic() - started,
        compute_device=device,
    )


def _get_admet_ai_model(models_dir: str | None) -> Any:
    key = str(Path(models_dir).resolve()) if models_dir else None
    if key not in _ADMET_AI_MODEL_CACHE:
        from admet_ai import ADMETModel

        kwargs: dict[str, Any] = {"num_workers": 0}
        if models_dir:
            kwargs["models_dir"] = Path(models_dir)
        _ADMET_AI_MODEL_CACHE[key] = ADMETModel(**kwargs)
    return _ADMET_AI_MODEL_CACHE[key]


def _run_chemprop_local(request: ChempropADMETRequest, status: dict[str, Any]) -> ChempropADMETOutput:
    started = time.monotonic()
    checkpoint_dir = Path(request.checkpoint_dir or status.get("models_dir") or "").expanduser()
    executable = status.get("path") or shutil.which("chemprop")
    if not executable or not checkpoint_dir.is_dir():
        return ChempropADMETOutput("chemprop_local_not_configured", "chemprop", False, warnings=["chemprop_checkpoint_not_configured"], runtime_seconds=time.monotonic() - started)
    with tempfile.TemporaryDirectory(prefix="chemprop_admet_") as temporary:
        root = Path(temporary)
        input_file, output_file = root / "input.csv", root / "output.csv"
        _write_input_csv(input_file, request.smiles_list)
        command = [str(executable), "predict", "--test-path", str(input_file), "--preds-path", str(output_file), "--checkpoint-dir", str(checkpoint_dir.resolve())]
        try:
            process = subprocess.run(command, capture_output=True, text=True, timeout=request.timeout_seconds, cwd=str(root), check=False)
        except subprocess.TimeoutExpired:
            return ChempropADMETOutput("chemprop_local_timeout", "chemprop", False, warnings=["chemprop_execution_timeout"], runtime_seconds=time.monotonic() - started)
        except OSError as exc:
            return ChempropADMETOutput("chemprop_local_os_error", "chemprop", False, warnings=[f"chemprop_execution_os_error:{type(exc).__name__}"], runtime_seconds=time.monotonic() - started)
        results = _parse_chemprop_output(output_file, request.molecule_ids, request.smiles_list)
        return ChempropADMETOutput(
            adapter_mode="chemprop_local_prediction",
            tool_name="chemprop",
            success=process.returncode == 0 and bool(results),
            results=results,
            labels=["chemprop_admet", "chemprop_local"] if results else ["chemprop_admet", "chemprop_no_results"],
            warnings=[] if results else ["chemprop_output_missing_or_empty"],
            stdout=process.stdout[:2000],
            stderr=process.stderr[:2000],
            exit_code=process.returncode,
            runtime_seconds=time.monotonic() - started,
        )


def _write_input_csv(path: Path, smiles_list: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["smiles"])
        writer.writerows([[smiles] for smiles in smiles_list])


def _parse_chemprop_output(output_csv: Path, molecule_ids: list[str], smiles_list: list[str]) -> list[SingleADMETResult]:
    try:
        with output_csv.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
    except OSError:
        return []
    return [_result_from_row(row, molecule_ids[index] if index < len(molecule_ids) else f"MOL-{index}", smiles_list[index] if index < len(smiles_list) else "", "chemprop_predicted") for index, row in enumerate(rows)]


def _parse_admet_ai_predictions(predictions: Any, molecule_ids: list[str], smiles_list: list[str]) -> list[SingleADMETResult]:
    if not hasattr(predictions, "to_dict"):
        return []
    rows = predictions.to_dict(orient="records")
    index_values = list(getattr(predictions, "index", []))
    occurrences: dict[str, deque[int]] = defaultdict(deque)
    for index, smiles in enumerate(smiles_list):
        occurrences[str(smiles)].append(index)
    results: list[SingleADMETResult] = []
    for row_index, row in enumerate(rows):
        smiles = str(index_values[row_index]) if row_index < len(index_values) else ""
        positions = occurrences.get(smiles)
        input_index = positions.popleft() if positions else row_index
        if input_index >= len(molecule_ids) or input_index >= len(smiles_list):
            continue
        results.append(_result_from_row(row, molecule_ids[input_index], smiles_list[input_index], "admet_ai_predicted", admet_ai=True))
    return results


def _result_from_row(row: dict[str, Any], molecule_id: str, smiles: str, source_label: str, *, admet_ai: bool = False) -> SingleADMETResult:
    def value(*keys: str) -> float | None:
        return _safe_float(_first_present(row, *keys))

    herg, ames = value("hERG"), value("AMES", "Ames")
    cyp3a4, cyp2d6 = value("CYP3A4_Veith", "CYP3A4"), value("CYP2D6_Veith", "CYP2D6")
    solubility = value("Solubility_AqSolDB", "Solubility", "solubility")
    permeability = value("PAMPA_NCATS", "Permeability", "permeability")
    dili, pgp, bbb = value("DILI", "dili"), value("Pgp_Broccatelli", "Pgp", "pgp"), value("BBB_Martins", "BBB", "bbb")
    risk_values = [item for item in (herg, ames, dili) if item is not None]
    risk_score = sum(risk_values) / len(risk_values) if risk_values else None
    labels = [source_label, _risk_label(herg, "hERG"), _risk_label(ames, "Ames")]
    labels.append("admet_blocker" if "high_risk" in labels else "admet_warning" if "medium_risk" in labels else "admet_clean")
    return SingleADMETResult(
        molecule_id=molecule_id, smiles=smiles,
        hERG_probability=herg, hERG_risk=_risk_label(herg, "hERG"),
        Ames_probability=ames, Ames_risk=_risk_label(ames, "Ames"),
        CYP3A4_inhibition=cyp3a4, CYP3A4_risk=_risk_label(cyp3a4, "CYP3A4"),
        CYP2D6_inhibition=cyp2d6, CYP2D6_risk=_risk_label(cyp2d6, "CYP2D6"),
        solubility=_solubility_class_from_log_s(solubility) if admet_ai else _score_class(solubility), solubility_score=_normalized_solubility_score(solubility) if admet_ai else solubility,
        permeability=_score_class(permeability), permeability_score=permeability,
        DILI_probability=dili, DILI_risk=_risk_label(dili, "DILI"),
        Pgp_substrate=pgp, Pgp_risk=_risk_label(pgp, "Pgp"),
        BBB_penetration=bbb, BBB_risk=_risk_label(bbb, "BBB"),
        admet_risk_score=round(risk_score, 3) if risk_score is not None else None,
        labels=labels,
    )


def _risk_label(probability: float | None, property_name: str) -> str:
    if probability is None:
        return "unknown_risk"
    threshold = _RISK_THRESHOLDS[property_name]
    return "high_risk" if probability >= threshold["high"] else "medium_risk" if probability >= threshold["medium"] else "low_risk"


def _score_class(score: float | None) -> str:
    if score is None:
        return "unknown"
    return "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"


def _solubility_class_from_log_s(value: float | None) -> str:
    if value is None:
        return "unknown"
    return "high" if value >= -2 else "medium" if value >= -4 else "low"


def _normalized_solubility_score(value: float | None) -> float | None:
    return round(max(0.0, min(1.0, (value + 6.0) / 6.0)), 3) if value is not None else None


def _safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def _first_present(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def chemprop_tool_status() -> dict[str, Any]:
    status = check_chemprop_available()
    return {key: status.get(key) for key in ("available", "mode", "version", "path", "models_dir", "model_count", "model_configured", "runtime_available", "gpu_available", "device", "warning")}
