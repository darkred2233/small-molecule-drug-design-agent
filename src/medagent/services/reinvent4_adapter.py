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
import importlib
import json
import math
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from medagent.core.config import get_settings
from medagent.services.docker_runtime import DockerMountBuilder, docker_temporary_directory
from medagent.services.tool_config import get_tool_runtime_config


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
    prior_file: str | None = None
    docker_image: str | None = None
    use_docker: bool = False
    timeout_seconds: int = 600
    # TL / RL fields
    run_type: str = "sampling"  # "sampling" | "transfer_learning" | "staged_learning"
    tl_epochs: int = 5
    rl_epochs: int = 30
    rl_sigma: float = 128.0
    rl_batch_size: int = 128
    scoring_components: list[dict[str, Any]] | None = None
    reference_ligands: list[str] | None = None  # seed similarity 的参考集


@dataclass
class Reinvent4Result:
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
# REINVENT4 availability check
# ---------------------------------------------------------------------------

def check_reinvent4_available() -> dict[str, Any]:
    """Check if REINVENT4 is available."""
    runtime_config = get_tool_runtime_config(
        "reinvent4",
        default_command="reinvent",
        default_images=("reinvent4:latest", "reinvent:latest"),
        default_timeout_seconds=600,
    )
    result: dict[str, Any] = {
        "available": False,
        "mode": None,
        "version": None,
        "path": None,
        "docker_image": None,
        "runtime_available": False,
        "model_configured": False,
        "prior_file": None,
        "gpu_available": False,
        "warning": None,
        **runtime_config.as_status(),
    }
    prior_file = _resolve_prior_file()
    result["model_configured"] = prior_file is not None
    result["prior_file"] = str(prior_file) if prior_file else None

    path = shutil.which(runtime_config.command or "reinvent")
    if path:
        try:
            proc = subprocess.run(
                [path, "--help"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if proc.returncode == 0:
                result["runtime_available"] = True
                result["available"] = result["model_configured"]
                result["mode"] = "local_cli"
                result["path"] = path
                result["version"] = _reinvent_version()
                if not result["model_configured"]:
                    result["warning"] = "reinvent4_prior_not_configured"
                return result
        except (OSError, subprocess.TimeoutExpired):
            pass

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
                    ["docker", "run", "--rm", image, "--help"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                result["runtime_available"] = runtime_probe.returncode == 0
                result["gpu_available"] = _check_gpu_available(image)
                result["available"] = (
                    result["runtime_available"] and result["model_configured"]
                )
                if not result["runtime_available"]:
                    result["warning"] = "reinvent4_runtime_probe_failed"
                elif not result["model_configured"]:
                    result["warning"] = "reinvent4_prior_not_configured"
                return result
        except (OSError, subprocess.TimeoutExpired):
            pass

    return result


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_reinvent4_generation(
    request: Reinvent4Request,
    reinvent4_status: dict[str, Any] | None = None,
) -> Reinvent4Result:
    """Run REINVENT4 molecular generation.

    Dispatches to sampling, transfer_learning, or staged_learning based on
    request.run_type.  For staged_learning, performs TL first to fine-tune
    the prior on seed SMILES, then RL with scoring function.
    """
    if reinvent4_status is None:
        reinvent4_status = check_reinvent4_available()

    request_prior = _resolve_prior_file(request.prior_file)
    if (
        not reinvent4_status.get("available")
        and reinvent4_status.get("runtime_available")
        and request_prior is not None
    ):
        reinvent4_status = {
            **reinvent4_status,
            "available": True,
            "model_configured": True,
            "prior_file": str(request_prior),
            "warning": None,
        }

    if not reinvent4_status.get("available"):
        if reinvent4_status.get("runtime_available") and not reinvent4_status.get(
            "model_configured"
        ):
            return Reinvent4Result(
                adapter_mode="reinvent4_model_not_configured",
                tool_name="reinvent4",
                success=False,
                warnings=[
                    "reinvent4_prior_not_configured",
                    "set_REINVENT4_PRIOR_FILE_or_request_prior_file",
                ],
            )
        return Reinvent4Result(
            adapter_mode="reinvent4_unavailable",
            tool_name="reinvent4",
            success=False,
            warnings=["reinvent4_not_installed"],
        )

    mode = reinvent4_status.get("mode")
    is_docker = mode == "docker"
    docker_image = (
        request.docker_image
        or reinvent4_status.get("docker_image")
        or "reinvent4:latest"
    ) if is_docker else None
    executable = None if is_docker else str(reinvent4_status.get("path") or "reinvent")

    # Dispatch based on run_type
    if request.run_type == "staged_learning":
        return _run_tl_then_rl(request, executable=executable, docker_image=docker_image)
    elif request.run_type == "transfer_learning":
        model, warnings = _run_transfer_learning(
            request, executable=executable, docker_image=docker_image,
        )
        return Reinvent4Result(
            adapter_mode="reinvent4_transfer_learning",
            tool_name="reinvent4",
            success=model is not None,
            generated_smiles=[],
            scores=[],
            labels=["reinvent4_transfer_learning"],
            warnings=warnings,
            provenance={"output_model": str(model) if model else None},
        )
    else:
        # Sampling (original behavior)
        if is_docker:
            return _run_reinvent4_docker(request, str(docker_image))
        else:
            return _run_reinvent4_local(request, executable)


def _run_tl_then_rl(
    request: Reinvent4Request,
    *,
    executable: str | None = None,
    docker_image: str | None = None,
) -> Reinvent4Result:
    """Transfer Learning → Staged Learning pipeline.

    1. Fine-tune prior on seed SMILES (TL)
    2. Run RL with scoring function using the fine-tuned model
    3. Fall back to sampling if either step fails
    """
    # Step 1: Transfer Learning
    tl_model, tl_warnings = _run_transfer_learning(
        request, executable=executable, docker_image=docker_image,
    )

    if tl_model is None:
        # TL failed — fall back to sampling
        fallback_warnings = tl_warnings + ["reinvent4_tl_failed_falling_back_to_sampling"]
        if docker_image:
            result = _run_reinvent4_docker(request, docker_image)
        else:
            result = _run_reinvent4_local(request, executable)
        result.warnings.extend(fallback_warnings)
        return result

    # Step 2: Staged Learning (RL)
    rl_result = _run_staged_learning(
        request,
        tl_model,
        executable=executable,
        docker_image=docker_image,
    )

    if not rl_result.success:
        # RL failed — fall back to sampling with TL model
        fallback_warnings = rl_result.warnings + ["reinvent4_rl_failed_falling_back_to_sampling"]
        sampling_request = Reinvent4Request(
            seed_smiles=request.seed_smiles,
            output_dir=request.output_dir,
            num_molecules=request.num_molecules,
            prior_file=str(tl_model),
            docker_image=request.docker_image,
            use_docker=request.use_docker,
            timeout_seconds=request.timeout_seconds,
            run_type="sampling",
        )
        if docker_image:
            result = _run_reinvent4_docker(sampling_request, docker_image)
        else:
            result = _run_reinvent4_local(sampling_request, executable)
        result.warnings.extend(fallback_warnings)
        return result

    rl_result.warnings.extend(tl_warnings)
    return rl_result


# ---------------------------------------------------------------------------
# Local execution
# ---------------------------------------------------------------------------

def _run_reinvent4_local(request: Reinvent4Request, executable: str) -> Reinvent4Result:
    """Run REINVENT4 via local CLI."""
    start_time = time.monotonic()
    prior_file = _resolve_prior_file(request.prior_file)
    if prior_file is None:
        return Reinvent4Result(
            adapter_mode="reinvent4_model_not_configured",
            tool_name="reinvent4",
            success=False,
            warnings=["reinvent4_prior_not_configured"],
        )

    with tempfile.TemporaryDirectory(prefix="reinvent4_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        config_file = tmp_path / "config.toml"
        output_file = tmp_path / "output.csv"

        # Generate TOML config
        _write_reinvent4_config(
            config_file,
            request,
            output_file,
            model_file=str(prior_file),
            device="cpu",
        )

        # Build command
        cmd = [executable, str(config_file)]

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
                provenance=_reinvent4_provenance(
                    request,
                    execution_mode="local_cli",
                    command=cmd,
                    prior_file=prior_file,
                    device="cpu",
                ),
            )
        except FileNotFoundError:
            return Reinvent4Result(
                adapter_mode="reinvent4_not_found",
                tool_name="reinvent4",
                success=False,
                warnings=["reinvent4_binary_not_found"],
                exit_code=-1,
                runtime_seconds=time.monotonic() - start_time,
                provenance=_reinvent4_provenance(
                    request,
                    execution_mode="local_cli",
                    command=cmd,
                    prior_file=prior_file,
                    device="cpu",
                ),
            )
        except OSError as exc:
            return Reinvent4Result(
                adapter_mode="reinvent4_execution_os_error",
                tool_name="reinvent4",
                success=False,
                warnings=[f"reinvent4_execution_os_error:{type(exc).__name__}"],
                exit_code=-1,
                runtime_seconds=time.monotonic() - start_time,
                provenance=_reinvent4_provenance(
                    request,
                    execution_mode="local_cli",
                    command=cmd,
                    prior_file=prior_file,
                    device="cpu",
                ),
            )

        # Parse output
        generated_smiles, scores = _parse_reinvent4_output(output_file)

        # Copy output to request output_dir
        output_dir = Path(request.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        if output_file.exists():
            import shutil
            shutil.copy2(output_file, output_dir / "reinvent4_output.csv")

        success = exit_code == 0 and len(generated_smiles) > 0
        return Reinvent4Result(
            adapter_mode="reinvent4_local",
            tool_name="reinvent4",
            success=success,
            generated_smiles=generated_smiles,
            scores=scores,
            labels=_reinvent4_labels(success, "reinvent4_local"),
            warnings=_reinvent4_warnings(request, exit_code, generated_smiles),
            stdout=stdout[:2000],
            stderr=stderr[:2000],
            exit_code=exit_code,
            runtime_seconds=time.monotonic() - start_time,
            provenance=_reinvent4_provenance(
                request,
                execution_mode="local_cli",
                command=cmd,
                prior_file=prior_file,
                device="cpu",
            ),
        )


# ---------------------------------------------------------------------------
# Docker execution
# ---------------------------------------------------------------------------

def _run_reinvent4_docker(request: Reinvent4Request, docker_image: str) -> Reinvent4Result:
    """Run REINVENT4 via Docker container."""
    import shutil

    start_time = time.monotonic()
    prior_file = _resolve_prior_file(request.prior_file)
    if prior_file is None:
        return Reinvent4Result(
            adapter_mode="reinvent4_model_not_configured",
            tool_name="reinvent4",
            success=False,
            warnings=["reinvent4_prior_not_configured"],
        )

    with docker_temporary_directory(prefix="reinvent4_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        config_file = tmp_path / "config.toml"
        output_file = tmp_path / "output.csv"

        # Generate TOML config
        use_gpu = _check_gpu_available(docker_image)
        mounts = DockerMountBuilder()
        data_path = mounts.bind(tmp_path, "/data")
        prior_path = mounts.bind(prior_file, "/data/model.prior", read_only=True)
        _write_reinvent4_config(
            config_file,
            request,
            PurePosixPath(data_path, "output.csv"),
            model_file=prior_path,
            device="cuda:0" if use_gpu else "cpu",
        )

        # Build Docker command
        cmd = _build_reinvent4_docker_command(
            docker_image=docker_image,
            data_dir=tmp_path,
            prior_file=prior_file,
            use_gpu=use_gpu,
            mounts=mounts,
            data_path=data_path,
            prior_path=prior_path,
        )

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
                provenance=_reinvent4_provenance(
                    request,
                    execution_mode="docker",
                    command=cmd,
                    prior_file=prior_file,
                    device="cuda:0" if use_gpu else "cpu",
                    docker_image=docker_image,
                ),
            )
        except FileNotFoundError:
            return Reinvent4Result(
                adapter_mode="docker_not_found",
                tool_name="reinvent4",
                success=False,
                warnings=["docker_not_installed"],
                exit_code=-1,
                runtime_seconds=time.monotonic() - start_time,
                provenance=_reinvent4_provenance(
                    request,
                    execution_mode="docker",
                    command=cmd,
                    prior_file=prior_file,
                    device="cuda:0" if use_gpu else "cpu",
                    docker_image=docker_image,
                ),
            )
        except OSError as exc:
            return Reinvent4Result(
                adapter_mode="reinvent4_docker_os_error",
                tool_name="reinvent4",
                success=False,
                warnings=[f"reinvent4_docker_os_error:{type(exc).__name__}"],
                exit_code=-1,
                runtime_seconds=time.monotonic() - start_time,
                provenance=_reinvent4_provenance(
                    request,
                    execution_mode="docker",
                    command=cmd,
                    prior_file=prior_file,
                    device="cuda:0" if use_gpu else "cpu",
                    docker_image=docker_image,
                ),
            )

        # Parse output
        generated_smiles, scores = _parse_reinvent4_output(output_file)

        # Copy output to request output_dir
        output_dir = Path(request.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        if output_file.exists():
            shutil.copy2(output_file, output_dir / "reinvent4_output.csv")

        success = exit_code == 0 and len(generated_smiles) > 0
        return Reinvent4Result(
            adapter_mode="reinvent4_docker",
            tool_name="reinvent4",
            success=success,
            generated_smiles=generated_smiles,
            scores=scores,
            labels=_reinvent4_labels(success, "reinvent4_docker"),
            warnings=_reinvent4_warnings(request, exit_code, generated_smiles, docker=True),
            stdout=stdout[:2000],
            stderr=stderr[:2000],
            exit_code=exit_code,
            runtime_seconds=time.monotonic() - start_time,
            provenance=_reinvent4_provenance(
                request,
                execution_mode="docker",
                command=cmd,
                prior_file=prior_file,
                device="cuda:0" if use_gpu else "cpu",
                docker_image=docker_image,
            ),
        )


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _write_reinvent4_config(
    config_path: Path,
    request: Reinvent4Request,
    output_path: Path | PurePosixPath,
    *,
    model_file: str,
    device: str,
) -> None:
    """Write REINVENT4 TOML configuration file."""
    config = "\n".join(
        [
            'run_type = "sampling"',
            f"device = {json.dumps(device)}",
            'json_out_config = "/data/sampling.json"'
            if str(output_path).startswith("/data/")
            else f"json_out_config = {json.dumps(str(output_path.with_suffix('.json')))}",
            "",
            "[parameters]",
            f"model_file = {json.dumps(model_file)}",
            f"output_file = {json.dumps(str(output_path))}",
            f"num_smiles = {int(request.num_molecules)}",
            "unique_molecules = true",
            "randomize_smiles = true",
            "",
        ]
    )
    config_path.write_text(config, encoding="utf-8")


# ---------------------------------------------------------------------------
# Transfer Learning config
# ---------------------------------------------------------------------------

def _write_transfer_learning_config(
    config_path: Path,
    request: Reinvent4Request,
    *,
    input_model: str,
    output_model: str,
    smiles_file: str,
    device: str,
) -> None:
    """Write REINVENT4 Transfer Learning TOML config."""
    lines = [
        'run_type = "transfer_learning"',
        f"device = {json.dumps(device)}",
        f"json_out_config = {json.dumps(str(config_path.with_suffix('.json')))}",
        "",
        "[parameters]",
        f"input_model_file = {json.dumps(input_model)}",
        f"output_model_file = {json.dumps(output_model)}",
        f"smiles_file = {json.dumps(smiles_file)}",
        f"num_epochs = {request.tl_epochs}",
        "batch_size = 50",
        "num_refs = 100",
        "sample_batch_size = 100",
        f"save_every_n_epochs = {request.tl_epochs}",
        "shuffle_each_epoch = true",
        "randomize_smiles = true",
        "standardize_smiles = true",
        "isomeric_smiles = false",
        "max_sequence_length = 128",
        "",
    ]
    config_path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Staged Learning (RL) config
# ---------------------------------------------------------------------------

def _write_staged_learning_config(
    config_path: Path,
    request: Reinvent4Request,
    *,
    prior_file: str,
    agent_file: str,
    output_dir: str,
    device: str,
) -> None:
    """Write REINVENT4 Staged Learning (RL) TOML config."""
    components = request.scoring_components or default_scoring_components()
    scoring_toml = _build_scoring_toml(components)

    lines = [
        'run_type = "staged_learning"',
        f"device = {json.dumps(device)}",
        f"json_out_config = {json.dumps(str(config_path.with_suffix('.json')))}",
        "",
        "[parameters]",
        f"prior_file = {json.dumps(prior_file)}",
        f"agent_file = {json.dumps(agent_file)}",
        f"summary_csv_prefix = {json.dumps(str(Path(output_dir) / 'staged_learning'))}",
        f"batch_size = {request.rl_batch_size}",
        "unique_sequences = true",
        "randomize_smiles = true",
        "use_checkpoint = false",
        "purge_memories = false",
        "",
        "[learning_strategy]",
        'type = "dap"',
        f"sigma = {int(request.rl_sigma)}",
        "rate = 0.0001",
        "",
        "[diversity_filter]",
        'type = "IdenticalMurckoScaffold"',
        "bucket_size = 25",
        "minscore = 0.4",
        "minsimilarity = 0.4",
        "penalty_multiplier = 0.5",
        "",
        "[[stage]]",
        'chkpt_file = "stage1.chkpt"',
        'termination = "simple"',
        "max_score = 0.8",
        "min_steps = 25",
        f"max_steps = {request.rl_epochs}",
        "",
        "[stage.scoring]",
        'type = "geometric_mean"',
        scoring_toml,
        "",
    ]
    config_path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Scoring components
# ---------------------------------------------------------------------------

def default_scoring_components() -> list[dict[str, Any]]:
    """Default scoring components for REINVENT4 RL mode."""
    return [
        {
            "type": "SAScore",
            "name": "SA_score",
            "weight": 0.25,
            "transform": {
                "type": "reverse_sigmoid",
                "high": 6.0,
                "low": 2.0,
                "k": 0.5,
            },
        },
        {
            "type": "Qed",
            "name": "QED",
            "weight": 0.20,
        },
        {
            "type": "MolecularWeight",
            "name": "MW_penalty",
            "weight": 0.15,
            "transform": {
                "type": "double_sigmoid",
                "low": 200.0,
                "high": 500.0,
                "coef_div": 500.0,
                "coef_si": 20.0,
                "coef_se": 20.0,
            },
        },
        {
            "type": "CustomAlerts",
            "name": "PAINS_filter",
            "weight": 0.0,
            "smarts": [
                "[#7]1~[#6](~[#7])~[#7]~[#6]1~[#7]",
                "[#6]1~[#6](~[#8])~[#8]~[#6]1",
                "[#6]1~[#6](~[#8])~[#7]~[#6]1",
            ],
        },
    ]


def _build_scoring_toml(components: list[dict[str, Any]]) -> str:
    """Build REINVENT4 scoring TOML from structured component definitions."""
    lines: list[str] = []
    for comp in components:
        comp_type = comp["type"]
        name = comp.get("name", comp_type)
        weight = comp.get("weight", 1.0)
        transform = comp.get("transform")
        smarts = comp.get("smarts")

        lines.append("")
        lines.append("[[stage.scoring.component]]")
        lines.append(f"[stage.scoring.component.{comp_type}]")
        lines.append(f"[[stage.scoring.component.{comp_type}.endpoint]]")
        lines.append(f'name = "{name}"')
        lines.append(f"weight = {weight}")

        if smarts:
            smarts_str = ", ".join(f'"{s}"' for s in smarts)
            lines.append(f"params.smarts = [{smarts_str}]")

        if transform:
            lines.append(f'transform.type = "{transform["type"]}"')
            for k, v in transform.items():
                if k != "type":
                    lines.append(f"transform.{k} = {v}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# TL / RL run helpers
# ---------------------------------------------------------------------------

def _run_transfer_learning(
    request: Reinvent4Request,
    *,
    executable: str | None = None,
    docker_image: str | None = None,
) -> tuple[Path | None, list[str]]:
    """Run Transfer Learning to fine-tune the prior model on seed SMILES.

    Returns (output_model_path, warnings).
    """
    prior_file = _resolve_prior_file(request.prior_file)
    if prior_file is None:
        return None, ["reinvent4_prior_not_configured"]

    if not request.seed_smiles:
        return None, ["transfer_learning_requires_seed_smiles"]

    is_docker = docker_image is not None

    with (docker_temporary_directory if is_docker else tempfile.TemporaryDirectory)(
        prefix="reinvent4_tl_"
    ) as tmp_dir:
        tmp_path = Path(tmp_dir)
        config_file = tmp_path / "tl_config.toml"
        smiles_file = tmp_path / "seeds.smi"
        output_model = tmp_path / "agent.model"

        # Write seed SMILES
        smiles_file.write_text(
            "\n".join(request.seed_smiles),
            encoding="utf-8",
        )

        if is_docker:
            mounts = DockerMountBuilder()
            data_path = mounts.bind(tmp_path, "/data")
            prior_path = mounts.bind(prior_file, "/data/model.prior", read_only=True)
            use_gpu = _check_gpu_available(docker_image)
            device = "cuda:0" if use_gpu else "cpu"

            _write_transfer_learning_config(
                config_file,
                request,
                input_model=prior_path,
                output_model=str(PurePosixPath(data_path, "agent.model")),
                smiles_file=str(PurePosixPath(data_path, "seeds.smi")),
                device=device,
            )

            cmd = ["docker", "run", "--rm"]
            if use_gpu:
                cmd.extend(["--gpus", "all"])
            cmd.extend([
                *mounts.arguments,
                "-w", data_path,
                docker_image,
                str(PurePosixPath(data_path, "tl_config.toml")),
            ])
        else:
            device = "cpu"
            _write_transfer_learning_config(
                config_file,
                request,
                input_model=str(prior_file),
                output_model=str(output_model),
                smiles_file=str(smiles_file),
                device=device,
            )
            cmd = [executable, str(config_file)]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=request.timeout_seconds,
                cwd=str(tmp_path),
            )
            if proc.returncode != 0:
                return None, [f"transfer_learning_failed:exit_{proc.returncode}"]
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            return None, [f"transfer_learning_error:{type(exc).__name__}"]

        # For Docker, we need to copy the model out
        if is_docker:
            # The model is in the temp dir which was mounted
            model_path = tmp_path / "agent.model"
        else:
            model_path = output_model

        if model_path.exists() and model_path.stat().st_size > 0:
            # Copy model to a persistent location
            persistent_model = Path(request.output_dir) / "tl_agent.model"
            persistent_model.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(model_path, persistent_model)
            return persistent_model, []

        # Check for alternative naming patterns
        for pattern in ["*.model", "*.chkpt", "*.pt"]:
            candidates = list(tmp_path.glob(pattern))
            if candidates:
                best = max(candidates, key=lambda p: p.stat().st_size)
                persistent_model = Path(request.output_dir) / "tl_agent.model"
                persistent_model.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(best, persistent_model)
                return persistent_model, []

        return None, ["transfer_learning_no_output_model"]


def _run_staged_learning(
    request: Reinvent4Request,
    agent_model: Path,
    *,
    executable: str | None = None,
    docker_image: str | None = None,
) -> Reinvent4Result:
    """Run Staged Learning (RL) with scoring function."""
    start_time = time.monotonic()
    prior_file = _resolve_prior_file(request.prior_file)
    if prior_file is None:
        return Reinvent4Result(
            adapter_mode="reinvent4_model_not_configured",
            tool_name="reinvent4",
            success=False,
            warnings=["reinvent4_prior_not_configured"],
        )

    is_docker = docker_image is not None

    with (docker_temporary_directory if is_docker else tempfile.TemporaryDirectory)(
        prefix="reinvent4_rl_"
    ) as tmp_dir:
        tmp_path = Path(tmp_dir)
        config_file = tmp_path / "rl_config.toml"
        output_dir = tmp_path / "output"
        output_dir.mkdir(exist_ok=True)

        if is_docker:
            mounts = DockerMountBuilder()
            data_path = mounts.bind(tmp_path, "/data")
            prior_path = mounts.bind(prior_file, "/data/model.prior", read_only=True)
            agent_path = mounts.bind(agent_model, "/data/agent.model", read_only=True)
            use_gpu = _check_gpu_available(docker_image)
            device = "cuda:0" if use_gpu else "cpu"

            _write_staged_learning_config(
                config_file,
                request,
                prior_file=prior_path,
                agent_file=agent_path,
                output_dir=str(PurePosixPath(data_path, "output")),
                device=device,
            )

            cmd = ["docker", "run", "--rm"]
            if use_gpu:
                cmd.extend(["--gpus", "all"])
            cmd.extend([
                *mounts.arguments,
                "-w", data_path,
                docker_image,
                str(PurePosixPath(data_path, "rl_config.toml")),
            ])
        else:
            device = "cpu"
            _write_staged_learning_config(
                config_file,
                request,
                prior_file=str(prior_file),
                agent_file=str(agent_model),
                output_dir=str(output_dir),
                device=device,
            )
            cmd = [executable, str(config_file)]

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
                adapter_mode="reinvent4_rl_timeout",
                tool_name="reinvent4",
                success=False,
                warnings=["reinvent4_rl_timeout"],
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
        except OSError as exc:
            return Reinvent4Result(
                adapter_mode="reinvent4_rl_os_error",
                tool_name="reinvent4",
                success=False,
                warnings=[f"reinvent4_rl_os_error:{type(exc).__name__}"],
                exit_code=-1,
                runtime_seconds=time.monotonic() - start_time,
            )

        # Parse output — RL mode outputs CSV in the summary_csv_prefix location
        generated_smiles, scores = _parse_reinvent4_output(output_dir)

        # Also check for output in tmp_path root (some REINVENT4 versions)
        if not generated_smiles:
            for csv_file in tmp_path.glob("**/staged_learning*.csv"):
                generated_smiles, scores = _parse_reinvent4_output(csv_file)
                if generated_smiles:
                    break

        # Copy output
        final_output_dir = Path(request.output_dir)
        final_output_dir.mkdir(parents=True, exist_ok=True)
        if output_dir.exists():
            for f in output_dir.iterdir():
                if f.is_file():
                    shutil.copy2(f, final_output_dir / f.name)

        success = exit_code == 0 and len(generated_smiles) > 0
        mode_label = "reinvent4_staged_learning_docker" if is_docker else "reinvent4_staged_learning"
        return Reinvent4Result(
            adapter_mode=mode_label,
            tool_name="reinvent4",
            success=success,
            generated_smiles=generated_smiles,
            scores=scores,
            labels=_reinvent4_labels(success, mode_label),
            warnings=[] if success else ["reinvent4_rl_no_output"],
            stdout=stdout[:2000],
            stderr=stderr[:2000],
            exit_code=exit_code,
            runtime_seconds=time.monotonic() - start_time,
            provenance={
                "execution_mode": "docker" if is_docker else "local_cli",
                "run_type": "staged_learning",
                "command": cmd,
                "prior_file": str(prior_file),
                "agent_file": str(agent_model),
                "device": device,
                "timeout_seconds": request.timeout_seconds,
                "rl_epochs": request.rl_epochs,
                "rl_sigma": request.rl_sigma,
                "scoring_components": request.scoring_components or default_scoring_components(),
            },
        )


def _build_reinvent4_docker_command(
    *,
    docker_image: str,
    data_dir: Path,
    prior_file: Path,
    use_gpu: bool,
    mounts: DockerMountBuilder | None = None,
    data_path: str | None = None,
    prior_path: str | None = None,
) -> list[str]:
    mounts = mounts or DockerMountBuilder()
    data_path = data_path or mounts.bind(data_dir.resolve(), "/data")
    if prior_path is None:
        mounts.bind(prior_file.resolve(), "/data/model.prior", read_only=True)
    command = ["docker", "run", "--rm"]
    if use_gpu:
        command.extend(["--gpus", "all"])
    command.extend(
        [
            *mounts.arguments,
            "-w",
            data_path,
            docker_image,
            str(PurePosixPath(data_path, "config.toml")),
        ]
    )
    return command


def _resolve_prior_file(value: str | None = None) -> Path | None:
    configured = value or os.environ.get("REINVENT4_PRIOR_FILE")
    if not configured:
        configured = get_settings().reinvent4_prior_file
    if not configured:
        return None
    path = Path(configured).expanduser().resolve()
    try:
        return path if path.is_file() and path.stat().st_size > 0 else None
    except OSError:
        return None


def _reinvent4_warnings(
    request: Reinvent4Request,
    exit_code: int,
    generated_smiles: list[str],
    *,
    docker: bool = False,
) -> list[str]:
    warnings: list[str] = []
    if request.run_type == "sampling":
        warnings.append("reinvent4_prior_sampling_not_target_optimized")
        if request.seed_smiles:
            warnings.append("reinvent4_seed_smiles_not_used_by_sampling_mode")
        if request.scoring_strategy != "simple":
            warnings.append("reinvent4_scoring_strategy_not_applied_in_sampling_mode")
    if exit_code != 0:
        warnings.append("reinvent4_docker_failed" if docker else "reinvent4_execution_failed")
    elif not generated_smiles:
        warnings.append("reinvent4_output_missing_or_empty")
    return warnings


def _reinvent4_labels(success: bool, mode_label: str) -> list[str]:
    outcome = "reinvent4_generated" if success else "reinvent4_generation_failed"
    return [outcome, mode_label]


def _reinvent4_provenance(
    request: Reinvent4Request,
    *,
    execution_mode: str,
    command: list[str],
    prior_file: Path,
    device: str,
    docker_image: str | None = None,
) -> dict[str, Any]:
    run_type = request.run_type
    return {
        "execution_mode": execution_mode,
        "docker_image": docker_image,
        "command": command,
        "run_type": run_type,
        "target_optimized": run_type != "sampling",
        "score_semantics": (
            "rl_optimized_scoring"
            if run_type == "staged_learning"
            else "not_available_for_prior_sampling"
        ),
        "prior_file": str(prior_file),
        "prior_file_size": _file_size(prior_file),
        "device": device,
        "timeout_seconds": request.timeout_seconds,
    }


def _file_size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


def _reinvent_version() -> str:
    for package_name in ["reinvent4", "reinvent"]:
        try:
            package = importlib.import_module(package_name)
            return str(getattr(package, "__version__", "unknown"))
        except ImportError:
            continue
    return "unknown"


def _check_gpu_available(docker_image: str) -> bool:
    try:
        proc = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--gpus",
                "all",
                "--entrypoint",
                "nvidia-smi",
                docker_image,
                "-L",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return proc.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _parse_reinvent4_output(
    output_path: Path,
) -> tuple[list[str], list[float | None]]:
    """Parse REINVENT4 output CSV."""
    smiles_list: list[str] = []
    scores: list[float | None] = []

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
                            parsed_score = float(score)
                            scores.append(
                                parsed_score if math.isfinite(parsed_score) else None
                            )
                        except ValueError:
                            scores.append(None)
                    else:
                        scores.append(None)
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
        "runtime_available": status.get("runtime_available", False),
        "model_configured": status.get("model_configured", False),
        "prior_file": status.get("prior_file"),
        "gpu_available": status.get("gpu_available", False),
        "warning": status.get("warning"),
        "configured_command": status.get("configured_command"),
        "docker_image_candidates": status.get("docker_image_candidates", []),
        "configured_timeout_seconds": status.get("configured_timeout_seconds", 600),
        "config_source": status.get("config_source"),
        "config_loaded": status.get("config_loaded", False),
        "config_environment_overrides": status.get("config_environment_overrides", []),
    }
