"""Chemprop ADMET adapter for real ADMET predictions.

Integrates with Chemprop (https://github.com/chemprop/chemprop) for:
- hERG channel blockade
- Ames mutagenicity
- CYP3A4/CYP2D6 inhibition
- Solubility prediction
- Permeability prediction
- DILI (drug-induced liver injury)
- Pgp substrate prediction
- BBB penetration

Supports three execution modes:
1. ADMET-AI bundled Chemprop ADMET ensembles
2. Local chemprop CLI (pip install chemprop)
3. Docker container (docker compose up chemprop)
4. RDKit surrogate fallback (always available)
"""

import csv
import contextlib
import importlib.metadata
import importlib.util
import io
import math
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_ADMET_AI_MODEL_CACHE: dict[str | None, Any] = {}


# ---------------------------------------------------------------------------
# Data contracts
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ChempropADMETRequest:
    smiles_list: list[str]
    molecule_ids: list[str]
    properties: list[str] = field(default_factory=lambda: [
        "hERG", "Ames", "CYP3A4", "CYP2D6", "solubility",
        "permeability", "DILI", "Pgp", "BBB",
    ])
    checkpoint_dir: str | None = None
    docker_image: str = "chemprop:latest"
    use_docker: bool = False
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


# ---------------------------------------------------------------------------
# Risk classification thresholds
# ---------------------------------------------------------------------------

_RISK_THRESHOLDS = {
    "hERG": {"high": 0.7, "medium": 0.4},
    "Ames": {"high": 0.7, "medium": 0.4},
    "CYP3A4": {"high": 0.7, "medium": 0.4},
    "CYP2D6": {"high": 0.7, "medium": 0.4},
    "DILI": {"high": 0.7, "medium": 0.4},
    "Pgp": {"high": 0.7, "medium": 0.4},
    "BBB": {"high": 0.7, "medium": 0.4},
}


def _risk_label(probability: float | None, property_name: str = "hERG") -> str:
    if probability is None:
        return "unknown_risk"
    thresholds = _RISK_THRESHOLDS.get(property_name, {"high": 0.7, "medium": 0.4})
    if probability >= thresholds["high"]:
        return "high_risk"
    if probability >= thresholds["medium"]:
        return "medium_risk"
    return "low_risk"


def _solubility_class(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score >= 0.7:
        return "high"
    if score >= 0.4:
        return "medium"
    return "low"


def _permeability_class(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score >= 0.7:
        return "high"
    if score >= 0.4:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Chemprop availability check
# ---------------------------------------------------------------------------

def _check_admet_ai_available() -> dict[str, Any] | None:
    """Return bundled ADMET-AI Chemprop model metadata when available."""
    spec = importlib.util.find_spec("admet_ai")
    if spec is None or spec.origin is None:
        return None

    package_dir = Path(spec.origin).parent
    models_dir = package_dir / "resources" / "models"
    required_dirs = [
        models_dir / "admet_classification",
        models_dir / "admet_regression",
    ]
    if not all(path.exists() for path in required_dirs):
        return None

    model_files = list(models_dir.rglob("*.pt"))
    if not model_files:
        return None

    try:
        version = importlib.metadata.version("admet-ai")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"

    return {
        "version": version,
        "models_dir": str(models_dir),
        "model_count": len(model_files),
    }


def _check_chemprop_cli() -> dict[str, Any] | None:
    """Return CLI metadata when a Chemprop command is callable."""
    path = shutil.which("chemprop")
    if path is None:
        return None

    try:
        proc = subprocess.run(
            ["chemprop", "--version"],
            capture_output=True, text=True, timeout=3,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {
            "version": "unknown",
            "path": path,
            "warning": "chemprop_cli_version_unavailable",
        }

    if proc.returncode == 0:
        return {"version": proc.stdout.strip() or "unknown", "path": path}

    return {
        "version": "unknown",
        "path": path,
        "warning": "chemprop_cli_version_unavailable",
    }


def check_chemprop_available() -> dict[str, Any]:
    """Check if Chemprop is available via CLI or Docker."""
    result: dict[str, Any] = {
        "available": False,
        "mode": None,
        "version": None,
        "path": None,
        "docker_image": None,
        "models_dir": None,
        "model_count": None,
    }

    # Prefer ADMET-AI's bundled Chemprop ADMET ensembles when installed.
    admet_ai_status = _check_admet_ai_available()
    if admet_ai_status:
        result["available"] = True
        result["mode"] = "admet_ai"
        result["version"] = admet_ai_status["version"]
        result["models_dir"] = admet_ai_status["models_dir"]
        result["model_count"] = admet_ai_status["model_count"]
        return result

    # Check local CLI
    cli_status = _check_chemprop_cli()
    if cli_status:
        result["available"] = True
        result["mode"] = "local_cli"
        result["version"] = cli_status["version"]
        result["path"] = cli_status["path"]
        if cli_status.get("warning"):
            result["warning"] = cli_status["warning"]
        return result

    # Check pip package
    try:
        import chemprop
        result["available"] = True
        result["mode"] = "python_package"
        result["version"] = getattr(chemprop, "__version__", "unknown")
        return result
    except ImportError:
        pass

    # Check Docker
    try:
        proc = subprocess.run(
            ["docker", "image", "inspect", "chemprop:latest"],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode == 0:
            result["available"] = True
            result["mode"] = "docker"
            result["docker_image"] = "chemprop:latest"
            return result
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return result


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_chemprop_admet(
    request: ChempropADMETRequest,
    chemprop_status: dict[str, Any] | None = None,
) -> ChempropADMETOutput:
    """Run ADMET predictions using Chemprop.

    Falls back to RDKit surrogate if Chemprop is unavailable.
    """
    if chemprop_status is None:
        chemprop_status = check_chemprop_available()

    if not chemprop_status.get("available"):
        return ChempropADMETOutput(
            adapter_mode="chemprop_unavailable",
            tool_name="chemprop",
            success=False,
            warnings=["chemprop_not_installed", "use_rdkit_surrogate_fallback"],
        )

    mode = chemprop_status.get("mode")

    if mode == "admet_ai":
        return _run_admet_ai(request, chemprop_status)
    if mode == "docker":
        return _run_chemprop_docker(request)
    else:
        return _run_chemprop_local(request)


def _run_admet_ai(
    request: ChempropADMETRequest,
    chemprop_status: dict[str, Any],
) -> ChempropADMETOutput:
    """Run ADMET-AI's bundled Chemprop ADMET ensembles."""
    import time

    start_time = time.monotonic()
    models_dir = request.checkpoint_dir or os.environ.get("ADMET_AI_MODELS_DIR") or chemprop_status.get("models_dir")
    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()

    try:
        with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
            model = _get_admet_ai_model(models_dir)
            predictions = model.predict(smiles=request.smiles_list)
    except ImportError as exc:
        return ChempropADMETOutput(
            adapter_mode="admet_ai_not_installed",
            tool_name="chemprop",
            success=False,
            warnings=["admet_ai_not_installed", str(exc)],
            runtime_seconds=time.monotonic() - start_time,
        )
    except Exception as exc:
        return ChempropADMETOutput(
            adapter_mode="admet_ai_chemprop_failed",
            tool_name="chemprop",
            success=False,
            warnings=["admet_ai_prediction_failed", str(exc)],
            stdout=stdout_buffer.getvalue()[:2000],
            stderr=stderr_buffer.getvalue()[:2000],
            runtime_seconds=time.monotonic() - start_time,
        )

    results = _parse_admet_ai_predictions(
        predictions,
        molecule_ids=request.molecule_ids,
        smiles_list=request.smiles_list,
    )
    warnings: list[str] = []
    labels = ["chemprop_admet", "admet_ai_chemprop"]
    if not results:
        labels.append("chemprop_no_results")
        warnings.append("admet_ai_failed_to_predict")

    return ChempropADMETOutput(
        adapter_mode="admet_ai_chemprop_admet",
        tool_name="chemprop",
        success=len(results) > 0,
        results=results,
        labels=labels,
        warnings=warnings,
        stdout=stdout_buffer.getvalue()[:2000],
        stderr=stderr_buffer.getvalue()[:2000],
        exit_code=0 if results else None,
        runtime_seconds=time.monotonic() - start_time,
    )


def _get_admet_ai_model(models_dir: str | None) -> Any:
    cache_key = str(Path(models_dir).resolve()) if models_dir else None
    if cache_key not in _ADMET_AI_MODEL_CACHE:
        from admet_ai import ADMETModel

        kwargs: dict[str, Any] = {"num_workers": 0}
        if models_dir:
            kwargs["models_dir"] = Path(models_dir)
        _ADMET_AI_MODEL_CACHE[cache_key] = ADMETModel(**kwargs)
    return _ADMET_AI_MODEL_CACHE[cache_key]


def _resolve_checkpoint_dir(request: ChempropADMETRequest) -> str | None:
    """Resolve an explicit or environment-configured Chemprop checkpoint path."""
    return request.checkpoint_dir or os.environ.get("CHEMPROP_CHECKPOINT_DIR")


def _chemprop_model_not_configured(start_time: float) -> ChempropADMETOutput:
    import time

    return ChempropADMETOutput(
        adapter_mode="chemprop_model_not_configured",
        tool_name="chemprop",
        success=False,
        labels=["chemprop_admet", "chemprop_model_missing"],
        warnings=[
            "chemprop_checkpoint_not_configured",
            "set_CHEMPROP_CHECKPOINT_DIR_or_request_checkpoint_dir",
            "use_rdkit_surrogate_fallback",
        ],
        exit_code=None,
        runtime_seconds=time.monotonic() - start_time,
    )


# ---------------------------------------------------------------------------
# Local CLI execution
# ---------------------------------------------------------------------------

def _run_chemprop_local(request: ChempropADMETRequest) -> ChempropADMETOutput:
    """Run Chemprop via local CLI or Python package."""
    import time

    start_time = time.monotonic()
    warnings: list[str] = []
    checkpoint_dir = _resolve_checkpoint_dir(request)
    if not checkpoint_dir:
        return _chemprop_model_not_configured(start_time)

    with tempfile.TemporaryDirectory(prefix="chemprop_admet_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        input_csv = tmp_path / "input.csv"
        output_csv = tmp_path / "output.csv"

        # Write input CSV
        _write_input_csv(input_csv, request.smiles_list)

        # Build command
        cmd = _build_chemprop_command(
            input_csv=input_csv,
            output_csv=output_csv,
            checkpoint_dir=checkpoint_dir,
            properties=request.properties,
        )

        # Run Chemprop
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
            return ChempropADMETOutput(
                adapter_mode="chemprop_timeout",
                tool_name="chemprop",
                success=False,
                warnings=["chemprop_execution_timeout"],
                exit_code=-1,
                runtime_seconds=time.monotonic() - start_time,
            )
        except FileNotFoundError:
            return ChempropADMETOutput(
                adapter_mode="chemprop_not_found",
                tool_name="chemprop",
                success=False,
                warnings=["chemprop_binary_not_found"],
                exit_code=-1,
                runtime_seconds=time.monotonic() - start_time,
            )

        # Parse output
        results = []
        if output_csv.exists():
            results = _parse_chemprop_output(
                output_csv, request.molecule_ids, request.smiles_list
            )
        else:
            warnings.append("chemprop_output_file_not_created")

        # Determine overall labels
        labels = ["chemprop_admet"]
        if not results:
            labels.append("chemprop_no_results")
            warnings.append("chemprop_failed_to_predict")

        return ChempropADMETOutput(
            adapter_mode="chemprop_local_admet",
            tool_name="chemprop",
            success=exit_code == 0 and len(results) > 0,
            results=results,
            labels=labels,
            warnings=warnings,
            stdout=stdout[:2000],
            stderr=stderr[:2000],
            exit_code=exit_code,
            runtime_seconds=time.monotonic() - start_time,
        )


# ---------------------------------------------------------------------------
# Docker execution
# ---------------------------------------------------------------------------

def _run_chemprop_docker(request: ChempropADMETRequest) -> ChempropADMETOutput:
    """Run Chemprop via Docker container."""
    import time

    start_time = time.monotonic()
    warnings: list[str] = []
    checkpoint_dir = _resolve_checkpoint_dir(request)
    if not checkpoint_dir:
        return _chemprop_model_not_configured(start_time)

    with tempfile.TemporaryDirectory(prefix="chemprop_admet_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        input_csv = tmp_path / "input.csv"
        output_csv = tmp_path / "output.csv"

        # Write input CSV
        _write_input_csv(input_csv, request.smiles_list)

        # Build Docker command
        cmd = [
            "docker", "run", "--rm",
            "-v", f"{tmp_path.resolve()}:/data",
            request.docker_image,
            "chemprop", "predict",
            "--test-path", "/data/input.csv",
            "--preds-path", "/data/output.csv",
        ]

        cmd.extend(["--checkpoint-dir", checkpoint_dir])

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
            return ChempropADMETOutput(
                adapter_mode="chemprop_docker_timeout",
                tool_name="chemprop",
                success=False,
                warnings=["chemprop_docker_timeout"],
                exit_code=-1,
                runtime_seconds=time.monotonic() - start_time,
            )
        except FileNotFoundError:
            return ChempropADMETOutput(
                adapter_mode="docker_not_found",
                tool_name="chemprop",
                success=False,
                warnings=["docker_not_installed"],
                exit_code=-1,
                runtime_seconds=time.monotonic() - start_time,
            )

        # Parse output
        results = []
        if output_csv.exists():
            results = _parse_chemprop_output(
                output_csv, request.molecule_ids, request.smiles_list
            )
        else:
            warnings.append("chemprop_output_file_not_created")

        labels = ["chemprop_admet", "chemprop_docker"]
        if not results:
            labels.append("chemprop_no_results")

        return ChempropADMETOutput(
            adapter_mode="chemprop_docker_admet",
            tool_name="chemprop",
            success=exit_code == 0 and len(results) > 0,
            results=results,
            labels=labels,
            warnings=warnings,
            stdout=stdout[:2000],
            stderr=stderr[:2000],
            exit_code=exit_code,
            runtime_seconds=time.monotonic() - start_time,
        )


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _write_input_csv(path: Path, smiles_list: list[str]) -> None:
    """Write SMILES to CSV for Chemprop input."""
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["smiles"])
        for smi in smiles_list:
            writer.writerow([smi])


def _build_chemprop_command(
    input_csv: Path,
    output_csv: Path,
    checkpoint_dir: str | None,
    properties: list[str],
) -> list[str]:
    """Build Chemprop CLI command."""
    cmd = [
        "chemprop", "predict",
        "--test-path", str(input_csv),
        "--preds-path", str(output_csv),
    ]

    if checkpoint_dir:
        cmd.extend(["--checkpoint-dir", checkpoint_dir])

    return cmd


def _parse_chemprop_output(
    output_csv: Path,
    molecule_ids: list[str],
    smiles_list: list[str],
) -> list[SingleADMETResult]:
    """Parse Chemprop output CSV into SingleADMETResult objects."""
    results: list[SingleADMETResult] = []

    try:
        with open(output_csv, newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except Exception:
        return results

    for idx, row in enumerate(rows):
        mol_id = molecule_ids[idx] if idx < len(molecule_ids) else f"MOL-{idx}"
        smi = smiles_list[idx] if idx < len(smiles_list) else ""

        # Extract probabilities from Chemprop output columns
        herg_prob = _safe_float(row.get("hERG") or row.get("herg"))
        ames_prob = _safe_float(row.get("Ames") or row.get("ames"))
        cyp3a4_prob = _safe_float(row.get("CYP3A4") or row.get("cyp3a4"))
        cyp2d6_prob = _safe_float(row.get("CYP2D6") or row.get("cyp2d6"))
        sol_score = _safe_float(row.get("Solubility") or row.get("solubility"))
        perm_score = _safe_float(row.get("Permeability") or row.get("permeability"))
        dili_prob = _safe_float(row.get("DILI") or row.get("dili"))
        pgp_prob = _safe_float(row.get("Pgp") or row.get("pgp"))
        bbb_prob = _safe_float(row.get("BBB") or row.get("bbb"))

        # Calculate overall risk score
        risk_probs = [p for p in [herg_prob, ames_prob, dili_prob] if p is not None]
        admet_risk = sum(risk_probs) / len(risk_probs) if risk_probs else None

        # Build labels
        labels = ["chemprop_predicted"]
        herg_risk = _risk_label(herg_prob, "hERG")
        ames_risk = _risk_label(ames_prob, "Ames")
        labels.extend([herg_risk, ames_risk])

        if herg_risk == "high_risk" or ames_risk == "high_risk":
            labels.append("admet_blocker")
        elif herg_risk == "medium_risk" or ames_risk == "medium_risk":
            labels.append("admet_warning")
        else:
            labels.append("admet_clean")

        result = SingleADMETResult(
            molecule_id=mol_id,
            smiles=smi,
            hERG_probability=herg_prob,
            hERG_risk=herg_risk,
            Ames_probability=ames_prob,
            Ames_risk=ames_risk,
            CYP3A4_inhibition=cyp3a4_prob,
            CYP3A4_risk=_risk_label(cyp3a4_prob, "CYP3A4"),
            CYP2D6_inhibition=cyp2d6_prob,
            CYP2D6_risk=_risk_label(cyp2d6_prob, "CYP2D6"),
            solubility=_solubility_class(sol_score),
            solubility_score=sol_score,
            permeability=_permeability_class(perm_score),
            permeability_score=perm_score,
            DILI_probability=dili_prob,
            DILI_risk=_risk_label(dili_prob, "DILI"),
            Pgp_substrate=pgp_prob,
            Pgp_risk=_risk_label(pgp_prob, "Pgp"),
            BBB_penetration=bbb_prob,
            BBB_risk=_risk_label(bbb_prob, "BBB"),
            admet_risk_score=round(admet_risk, 3) if admet_risk is not None else None,
            labels=labels,
        )
        results.append(result)

    return results


def _parse_admet_ai_predictions(
    predictions: Any,
    molecule_ids: list[str],
    smiles_list: list[str],
) -> list[SingleADMETResult]:
    """Map ADMET-AI prediction columns into this adapter's ADMET contract."""
    if hasattr(predictions, "to_dict"):
        rows = predictions.to_dict(orient="records")
    elif isinstance(predictions, dict):
        rows = [predictions]
    else:
        return []

    results: list[SingleADMETResult] = []
    for idx, row in enumerate(rows):
        mol_id = molecule_ids[idx] if idx < len(molecule_ids) else f"MOL-{idx}"
        smi = smiles_list[idx] if idx < len(smiles_list) else ""

        herg_prob = _safe_float(_first_present(row, "hERG"))
        ames_prob = _safe_float(_first_present(row, "AMES", "Ames"))
        cyp3a4_prob = _safe_float(_first_present(row, "CYP3A4_Veith", "CYP3A4"))
        cyp2d6_prob = _safe_float(_first_present(row, "CYP2D6_Veith", "CYP2D6"))
        solubility_log_s = _safe_float(_first_present(row, "Solubility_AqSolDB", "Solubility"))
        permeability_score = _safe_float(_first_present(row, "PAMPA_NCATS", "Permeability"))
        dili_prob = _safe_float(_first_present(row, "DILI"))
        pgp_prob = _safe_float(_first_present(row, "Pgp_Broccatelli", "Pgp"))
        bbb_prob = _safe_float(_first_present(row, "BBB_Martins", "BBB"))

        risk_probs = [p for p in [herg_prob, ames_prob, dili_prob] if p is not None]
        admet_risk = sum(risk_probs) / len(risk_probs) if risk_probs else None
        herg_risk = _risk_label(herg_prob, "hERG")
        ames_risk = _risk_label(ames_prob, "Ames")

        labels = ["chemprop_predicted", "admet_ai_predicted", herg_risk, ames_risk]
        if herg_risk == "high_risk" or ames_risk == "high_risk":
            labels.append("admet_blocker")
        elif herg_risk == "medium_risk" or ames_risk == "medium_risk":
            labels.append("admet_warning")
        else:
            labels.append("admet_clean")

        results.append(SingleADMETResult(
            molecule_id=mol_id,
            smiles=smi,
            hERG_probability=herg_prob,
            hERG_risk=herg_risk,
            Ames_probability=ames_prob,
            Ames_risk=ames_risk,
            CYP3A4_inhibition=cyp3a4_prob,
            CYP3A4_risk=_risk_label(cyp3a4_prob, "CYP3A4"),
            CYP2D6_inhibition=cyp2d6_prob,
            CYP2D6_risk=_risk_label(cyp2d6_prob, "CYP2D6"),
            solubility=_solubility_class_from_log_s(solubility_log_s),
            solubility_score=_normalized_solubility_score(solubility_log_s),
            permeability=_permeability_class(permeability_score),
            permeability_score=permeability_score,
            DILI_probability=dili_prob,
            DILI_risk=_risk_label(dili_prob, "DILI"),
            Pgp_substrate=pgp_prob,
            Pgp_risk=_risk_label(pgp_prob, "Pgp"),
            BBB_penetration=bbb_prob,
            BBB_risk=_risk_label(bbb_prob, "BBB"),
            admet_risk_score=round(admet_risk, 3) if admet_risk is not None else None,
            labels=labels,
        ))

    return results


def _solubility_class_from_log_s(log_s: float | None) -> str:
    if log_s is None:
        return "unknown"
    if log_s >= -2:
        return "high"
    if log_s >= -4:
        return "medium"
    return "low"


def _normalized_solubility_score(log_s: float | None) -> float | None:
    if log_s is None:
        return None
    return round(max(0.0, min(1.0, (log_s + 6.0) / 6.0)), 3)


def _safe_float(value: Any) -> float | None:
    """Safely convert value to float."""
    if value is None:
        return None
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    if math.isnan(number):
        return None
    return number


def _first_present(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key not in row:
            continue
        value = row[key]
        if value is None:
            continue
        if isinstance(value, str) and value == "":
            continue
        return value
    return None


# ---------------------------------------------------------------------------
# Adapter status for tool detection
# ---------------------------------------------------------------------------

def chemprop_tool_status() -> dict[str, Any]:
    """Get Chemprop tool status for integration with candidate_assessment."""
    status = check_chemprop_available()
    return {
        "available": status["available"],
        "mode": status.get("mode"),
        "version": status.get("version"),
        "path": status.get("path"),
        "docker_image": status.get("docker_image"),
        "models_dir": status.get("models_dir"),
        "model_count": status.get("model_count"),
    }
