"""AiZynthFinder adapter status, execution, and safe fallback helpers."""

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from importlib import metadata, util
from pathlib import Path, PurePosixPath
from typing import Any

from medagent.services.docker_runtime import DockerMountBuilder, docker_temporary_directory


@dataclass(frozen=True)
class AiZynthFinderRequest:
    smiles: str
    output_dir: str
    config_file: str | None = None
    max_steps: int = 6
    docker_image: str = "aizynthfinder:latest"
    timeout_seconds: int = 900


@dataclass
class AiZynthFinderResult:
    adapter_mode: str
    tool_name: str
    success: bool
    route_found: bool = False
    num_steps: int | None = None
    route_score: float | None = None
    route_summary: str | None = None
    route_plan: list[dict[str, Any]] = field(default_factory=list)
    starting_materials: list[str] = field(default_factory=list)
    route_trees: list[dict[str, Any]] = field(default_factory=list)
    stock_info: dict[str, Any] = field(default_factory=dict)
    route_metadata: dict[str, Any] = field(default_factory=dict)
    labels: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    runtime_seconds: float = 0.0


def check_aizynthfinder_available() -> dict[str, Any]:
    result: dict[str, Any] = {
        "available": False,
        "mode": None,
        "version": None,
        "path": None,
        "docker_image": None,
        "model_configured": False,
    }

    package_status = _python_package_status()
    if package_status is not None:
        return {**result, **package_status}

    cli_status = _cli_status()
    if cli_status is not None:
        return {**result, **cli_status}

    docker_status = _docker_status()
    if docker_status is not None:
        return {**result, **docker_status}

    return result


def aizynthfinder_tool_status() -> dict[str, Any]:
    status = check_aizynthfinder_available()
    return {
        "available": status["available"],
        "mode": status.get("mode"),
        "version": status.get("version"),
        "path": status.get("path"),
        "docker_image": status.get("docker_image"),
        "model_configured": status.get("model_configured", False),
        "runtime_available": status.get("runtime_available", status["available"]),
        "gpu_available": status.get("gpu_available", False),
        "warning": status.get("warning"),
    }


def run_aizynthfinder_retrosynthesis(
    request: AiZynthFinderRequest,
    status: dict[str, Any] | None = None,
) -> AiZynthFinderResult:
    start_time = time.monotonic()
    status = status or check_aizynthfinder_available()

    if not status.get("available"):
        return AiZynthFinderResult(
            adapter_mode="aizynthfinder_unavailable",
            tool_name="aizynthfinder",
            success=False,
            warnings=["aizynthfinder_not_installed"],
            runtime_seconds=time.monotonic() - start_time,
        )

    config_file = _resolve_config_file(request.config_file)
    if config_file is None:
        return AiZynthFinderResult(
            adapter_mode="aizynthfinder_model_not_configured",
            tool_name="aizynthfinder",
            success=False,
            warnings=["aizynthfinder_config_not_configured"],
            runtime_seconds=time.monotonic() - start_time,
        )
    if not config_file.is_file():
        return AiZynthFinderResult(
            adapter_mode="aizynthfinder_config_missing",
            tool_name="aizynthfinder",
            success=False,
            warnings=["aizynthfinder_config_missing"],
            runtime_seconds=time.monotonic() - start_time,
        )
    if config_file.stat().st_size == 0:
        return AiZynthFinderResult(
            adapter_mode="aizynthfinder_config_empty",
            tool_name="aizynthfinder",
            success=False,
            warnings=["aizynthfinder_config_empty"],
            runtime_seconds=time.monotonic() - start_time,
        )

    mode = status.get("mode")
    if mode == "docker":
        return _run_aizynthfinder_docker(request, status, config_file, start_time)
    if mode in {"local_cli", "python_package"}:
        return _run_aizynthfinder_local(request, status, config_file, start_time)

    return AiZynthFinderResult(
        adapter_mode="aizynthfinder_mode_unsupported",
        tool_name="aizynthfinder",
        success=False,
        warnings=[f"aizynthfinder_mode_unsupported:{mode}"],
        runtime_seconds=time.monotonic() - start_time,
    )


def _python_package_status() -> dict[str, Any] | None:
    if util.find_spec("aizynthfinder") is None:
        return None

    try:
        version = metadata.version("aizynthfinder")
    except metadata.PackageNotFoundError:
        version = "unknown"

    return {
        "available": True,
        "mode": "python_package",
        "version": version,
        "path": None,
        "model_configured": _default_config_available(),
    }


def _cli_status() -> dict[str, Any] | None:
    for command in ["aizynthcli", "aizynthapp"]:
        path = shutil.which(command)
        if path is not None:
            return {
                "available": True,
                "mode": "local_cli",
                "version": "unknown",
                "path": path,
                "model_configured": _default_config_available(),
            }
    return None


def _docker_status() -> dict[str, Any] | None:
    for image in ["aizynthfinder:latest", "molecularai/aizynthfinder:latest"]:
        try:
            proc = subprocess.run(
                ["docker", "image", "inspect", image],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None
        if proc.returncode == 0:
            runtime_probe = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--entrypoint",
                    "aizynthcli",
                    image,
                    "--help",
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            runtime_available = runtime_probe.returncode == 0
            return {
                "available": runtime_available,
                "runtime_available": runtime_available,
                "mode": "docker",
                "docker_image": image,
                "model_configured": _default_config_available(),
                "gpu_available": _check_gpu_available(image),
                "warning": None
                if runtime_available
                else "aizynthfinder_runtime_probe_failed",
            }
    return None


def _default_config_path() -> Path | None:
    env_path = os.environ.get("AIZYNTHFINDER_CONFIG") or os.environ.get(
        "MEDAGENT_AIZYNTHFINDER_CONFIG"
    )
    if env_path:
        return Path(env_path).expanduser().resolve()

    default_config = Path.cwd().resolve() / "data" / "aizynthfinder" / "config.yml"
    if default_config.exists():
        return default_config
    return None


def _default_config_available() -> bool:
    path = _default_config_path()
    return bool(path and _config_file_ready(path))


def _config_file_ready(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _resolve_config_file(config_file: str | None) -> Path | None:
    if config_file:
        return Path(config_file).expanduser().resolve()
    return _default_config_path()


def _run_aizynthfinder_local(
    request: AiZynthFinderRequest,
    status: dict[str, Any],
    config_file: Path,
    start_time: float,
) -> AiZynthFinderResult:
    output_dir = Path(request.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "aizynthfinder_routes.json"
    _remove_stale_output(output_file)

    with docker_temporary_directory(prefix="aizynthfinder_") as tmp_dir:
        smiles_file = Path(tmp_dir) / "targets.smi"
        _write_smiles_input(smiles_file, request.smiles)
        command = _build_aizynthfinder_local_command(
            status=status,
            config_file=config_file,
            smiles_file=smiles_file,
            output_file=output_file,
        )
        adapter_mode = (
            "aizynthfinder_python_package"
            if status.get("mode") == "python_package"
            else "aizynthfinder_local"
        )
        return _run_command(
            command=command,
            adapter_mode=adapter_mode,
            start_time=start_time,
            timeout_seconds=request.timeout_seconds,
            output_file=output_file,
            max_steps=request.max_steps,
            cwd=config_file.parent,
        )


def _run_aizynthfinder_docker(
    request: AiZynthFinderRequest,
    status: dict[str, Any],
    config_file: Path,
    start_time: float,
) -> AiZynthFinderResult:
    output_dir = Path(request.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "aizynthfinder_routes.json"
    _remove_stale_output(output_file)

    with docker_temporary_directory(prefix="aizynthfinder_") as tmp_dir:
        smiles_file = Path(tmp_dir) / "targets.smi"
        _write_smiles_input(smiles_file, request.smiles)
        command = _build_aizynthfinder_docker_command(
            request=request,
            status=status,
            config_file=config_file,
            smiles_file=smiles_file,
            output_dir=output_dir,
        )
        return _run_command(
            command=command,
            adapter_mode="aizynthfinder_docker",
            start_time=start_time,
            timeout_seconds=request.timeout_seconds,
            output_file=output_file,
            max_steps=request.max_steps,
        )


def _write_smiles_input(path: Path, smiles: str) -> None:
    path.write_text(smiles.strip() + "\n", encoding="utf-8")


def _remove_stale_output(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _build_aizynthfinder_local_command(
    status: dict[str, Any],
    config_file: Path,
    smiles_file: Path,
    output_file: Path,
) -> list[str]:
    if status.get("mode") == "python_package":
        executable = [sys.executable, "-m", "aizynthfinder.interfaces.aizynthcli"]
    else:
        executable = [status.get("path") or "aizynthcli"]

    return executable + [
        "--config",
        str(config_file),
        "--smiles",
        str(smiles_file),
        "--output",
        str(output_file),
    ]


def _build_aizynthfinder_docker_command(
    request: AiZynthFinderRequest,
    status: dict[str, Any],
    config_file: Path,
    smiles_file: Path,
    output_dir: Path,
) -> list[str]:
    import time
    image = status.get("docker_image") or request.docker_image
    container_name = f"aizynthfinder_{int(time.time() * 1000)}"

    has_gpu = bool(status.get("gpu_available"))
    mounts = DockerMountBuilder()
    input_path = mounts.bind(smiles_file.parent.resolve(), "/data/input", read_only=True)
    output_path = mounts.bind(output_dir.resolve(), "/data/output")
    config_path = mounts.bind(config_file.parent.resolve(), "/data/config", read_only=True)

    command = [
        "docker",
        "run",
        "--rm",
        "--name",
        container_name,
    ]

    # Add GPU support if available (AiZynthFinder can benefit from GPU)
    if has_gpu:
        command.extend(["--gpus", "all"])

    data_dir = _resolve_data_dir(config_file)
    if data_dir is not None:
        mounts.bind(data_dir, "/data/aizynthfinder", read_only=True)

    command += [
        *mounts.arguments,
        "-w",
        config_path,
        "--entrypoint",
        "aizynthcli",
        image,
        "--config",
        str(PurePosixPath(config_path, config_file.name)),
        "--smiles",
        str(PurePosixPath(input_path, smiles_file.name)),
        "--output",
        str(PurePosixPath(output_path, "aizynthfinder_routes.json")),
    ]
    return command


def _resolve_data_dir(config_file: Path) -> Path | None:
    env_path = os.environ.get("AIZYNTHFINDER_DATA_DIR") or os.environ.get(
        "MEDAGENT_AIZYNTHFINDER_DATA_DIR"
    )
    candidates = []
    if env_path:
        candidates.append(Path(env_path).expanduser().resolve())
    candidates.append(config_file.parent.resolve())
    repo_data_dir = Path.cwd().resolve() / "data" / "aizynthfinder"
    candidates.append(repo_data_dir)

    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def _run_command(
    command: list[str],
    adapter_mode: str,
    start_time: float,
    timeout_seconds: int,
    output_file: Path,
    max_steps: int,
    cwd: Path | None = None,
) -> AiZynthFinderResult:
    container_name = _extract_container_name(command)
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=str(cwd) if cwd else None,
        )
    except subprocess.TimeoutExpired:
        # Clean up Docker container on timeout
        if container_name:
            _cleanup_docker_container(container_name)
        return AiZynthFinderResult(
            adapter_mode=f"{adapter_mode}_timeout",
            tool_name="aizynthfinder",
            success=False,
            warnings=["aizynthfinder_timeout"],
            exit_code=-1,
            runtime_seconds=time.monotonic() - start_time,
        )
    except FileNotFoundError:
        return AiZynthFinderResult(
            adapter_mode="aizynthfinder_not_found",
            tool_name="aizynthfinder",
            success=False,
            warnings=["aizynthfinder_binary_not_found"],
            exit_code=-1,
            runtime_seconds=time.monotonic() - start_time,
        )

    execution_ok = proc.returncode == 0
    parsed = _parse_aizynthfinder_output(output_file, max_steps) if execution_ok else {}
    warnings = list(parsed.get("warnings", []))
    if not execution_ok:
        warnings.append("aizynthfinder_execution_failed")
    elif not output_file.exists() and "aizynthfinder_output_missing" not in warnings:
        warnings.append("aizynthfinder_output_missing")

    output_parsed = bool(parsed.get("parsed", False))
    success = execution_ok and output_parsed
    route_found = bool(parsed.get("route_found", False))
    labels = ["aizynthfinder_executed"]
    if route_found:
        labels.append("aizynthfinder_route")

    return AiZynthFinderResult(
        adapter_mode=adapter_mode,
        tool_name="aizynthfinder",
        success=success,
        route_found=route_found,
        num_steps=parsed.get("num_steps"),
        route_score=parsed.get("route_score"),
        route_summary=parsed.get("route_summary"),
        route_plan=parsed.get("route_plan") or [],
        starting_materials=parsed.get("starting_materials") or [],
        route_trees=parsed.get("route_trees") or [],
        stock_info=parsed.get("stock_info") or {},
        route_metadata=parsed.get("route_metadata") or {},
        labels=labels if success else [],
        warnings=warnings,
        stdout=proc.stdout[:2000],
        stderr=proc.stderr[:2000],
        exit_code=proc.returncode,
        runtime_seconds=time.monotonic() - start_time,
    )


def _parse_aizynthfinder_output(output_file: Path, max_steps: int) -> dict[str, Any]:
    if not output_file.exists():
        return {"parsed": False, "warnings": ["aizynthfinder_output_missing"]}

    try:
        payload = json.loads(output_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"parsed": False, "warnings": ["aizynthfinder_output_parse_failed"]}

    record = _extract_first_record(payload)
    if record is None:
        return {"parsed": False, "warnings": ["aizynthfinder_output_empty"]}

    is_solved = _coerce_bool(record.get("is_solved"))
    solved_routes = _coerce_int(record.get("number_of_solved_routes"))
    if solved_routes is not None and solved_routes > 0:
        is_solved = True

    num_steps = _coerce_int(record.get("number_of_steps"))
    route_score = _coerce_float(record.get("top_score"))
    trees = _coerce_list(record.get("trees"))
    stock_info = _coerce_dict(record.get("stock_info"))
    selected_tree = _select_representative_tree(trees)
    route_plan = _route_plan_from_tree(selected_tree) if selected_tree else []
    starting_materials = _starting_materials_from_tree(
        selected_tree,
        stock_info=stock_info,
        availability_by_material=_availability_from_record(record),
    )
    if not starting_materials:
        starting_materials = _starting_materials_from_record(record, stock_info)

    warnings: list[str] = []
    route_found = is_solved
    if is_solved and num_steps is not None and num_steps > max_steps:
        route_found = False
        warnings.append("aizynthfinder_route_exceeds_max_steps")

    if route_found:
        route_summary = _route_found_summary(num_steps, route_score)
    elif is_solved:
        route_summary = (
            f"AiZynthFinder found a route, but it exceeds max_steps={max_steps}."
        )
    else:
        route_summary = "AiZynthFinder completed, but no solved route was found."

    return {
        "parsed": True,
        "route_found": route_found,
        "num_steps": num_steps,
        "route_score": route_score,
        "route_summary": route_summary,
        "route_plan": route_plan,
        "starting_materials": starting_materials,
        "route_trees": trees[:10],
        "stock_info": stock_info,
        "route_metadata": {
            "target": record.get("target"),
            "number_of_routes": _coerce_int(record.get("number_of_routes")),
            "number_of_solved_routes": solved_routes,
            "number_of_precursors": _coerce_int(record.get("number_of_precursors")),
            "number_of_precursors_in_stock": _coerce_int(
                record.get("number_of_precursors_in_stock")
            ),
            "precursors_in_stock": record.get("precursors_in_stock"),
            "precursors_not_in_stock": record.get("precursors_not_in_stock"),
            "precursors_availability": record.get("precursors_availability"),
            "selected_tree_index": trees.index(selected_tree) if selected_tree in trees else None,
        },
        "warnings": warnings,
    }


def _extract_first_record(payload: Any) -> dict[str, Any] | None:
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list) and data:
            first = data[0]
            return first if isinstance(first, dict) else None
        if "is_solved" in payload or "number_of_solved_routes" in payload:
            return payload
    return None


def _route_found_summary(num_steps: int | None, route_score: float | None) -> str:
    if num_steps is not None and route_score is not None:
        return f"AiZynthFinder found a route in {num_steps} steps; top score={route_score:.3g}."
    if num_steps is not None:
        return f"AiZynthFinder found a route in {num_steps} steps."
    if route_score is not None:
        return f"AiZynthFinder found a route; top score={route_score:.3g}."
    return "AiZynthFinder found a retrosynthesis route."


def _coerce_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _coerce_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _select_representative_tree(trees: list[Any]) -> dict[str, Any] | None:
    candidates = [tree for tree in trees if isinstance(tree, dict)]
    if not candidates:
        return None

    def score(tree: dict[str, Any]) -> tuple[bool, int, int, float, float]:
        scores = _coerce_dict(tree.get("scores"))
        metadata = _coerce_dict(tree.get("metadata"))
        precursor_count = _coerce_int(scores.get("number of pre-cursors")) or 0
        stock_count = _coerce_int(scores.get("number of pre-cursors in stock")) or 0
        state_score = _coerce_float(scores.get("state score")) or 0.0
        policy_probability = max(
            [_reaction_policy_probability(reaction) for reaction in _reaction_nodes(tree)]
            or [0.0]
        )
        return (
            _coerce_bool(metadata.get("is_solved")),
            stock_count,
            -max(precursor_count - stock_count, 0),
            policy_probability,
            state_score,
        )

    return max(candidates, key=score)


def _route_plan_from_tree(tree: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(tree, dict):
        return []
    steps: list[dict[str, Any]] = []
    _append_route_steps(tree, steps)
    for index, step in enumerate(steps, start=1):
        step["step"] = index
    return steps


def _append_route_steps(mol_node: dict[str, Any], steps: list[dict[str, Any]]) -> None:
    if not isinstance(mol_node, dict):
        return
    parent_smiles = str(mol_node.get("smiles") or "").strip()
    for reaction in _reaction_children(mol_node):
        precursor_nodes = _mol_children(reaction)
        for precursor in precursor_nodes:
            if _reaction_children(precursor):
                _append_route_steps(precursor, steps)
        precursor_smiles = [
            str(precursor.get("smiles") or "").strip()
            for precursor in precursor_nodes
            if str(precursor.get("smiles") or "").strip()
        ]
        metadata = _coerce_dict(reaction.get("metadata"))
        policy = str(metadata.get("policy_name") or "unknown").strip() or "unknown"
        policy_probability = _coerce_float(metadata.get("policy_probability"))
        probability_text = (
            f" p={policy_probability:.3f}" if policy_probability is not None else ""
        )
        reaction_smiles = str(reaction.get("smiles") or "").strip()
        steps.append(
            {
                "step": 0,
                "stage": "AiZynthFinder disconnection",
                "input": precursor_smiles,
                "operation": (
                    f"Forward reaction from AiZynthFinder template {policy}"
                    f"{probability_text}."
                ),
                "output": parent_smiles,
                "rationale": f"reaction_smiles={reaction_smiles}" if reaction_smiles else None,
            }
        )


def _starting_materials_from_tree(
    tree: dict[str, Any] | None,
    *,
    stock_info: dict[str, Any],
    availability_by_material: dict[str, str],
) -> list[str]:
    if not isinstance(tree, dict):
        return []
    materials: list[str] = []
    for node in _leaf_mol_nodes(tree):
        smiles = str(node.get("smiles") or "").strip()
        if not smiles:
            continue
        materials.append(
            _format_starting_material(smiles, stock_info, availability_by_material)
        )
    return _dedupe_strings(materials)


def _starting_materials_from_record(
    record: dict[str, Any],
    stock_info: dict[str, Any],
) -> list[str]:
    availability_by_material = _availability_from_record(record)
    materials = [
        _format_starting_material(smiles, stock_info, availability_by_material)
        for smiles in _split_precursors(record.get("precursors_in_stock"))
    ]
    return _dedupe_strings(materials)


def _availability_from_record(record: dict[str, Any]) -> dict[str, str]:
    precursors = _split_precursors(record.get("precursors_in_stock"))
    availability = [
        item.strip()
        for item in str(record.get("precursors_availability") or "").split(";")
        if item.strip()
    ]
    return {
        precursor: availability[index]
        for index, precursor in enumerate(precursors)
        if index < len(availability)
    }


def _format_starting_material(
    smiles: str,
    stock_info: dict[str, Any],
    availability_by_material: dict[str, str],
) -> str:
    availability = stock_info.get(smiles)
    if isinstance(availability, list):
        sources = ", ".join(str(item) for item in availability if str(item).strip())
    elif isinstance(availability, str):
        sources = availability.strip()
    else:
        sources = availability_by_material.get(smiles, "")
    return f"{smiles} ({sources})" if sources else smiles


def _split_precursors(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [
        item.strip()
        for item in str(value or "").split(",")
        if item.strip()
    ]


def _leaf_mol_nodes(node: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(node, dict):
        return []
    reactions = _reaction_children(node)
    if not reactions:
        return [node] if node.get("type") == "mol" or node.get("is_chemical") else []
    leaves: list[dict[str, Any]] = []
    for reaction in reactions:
        for child in _mol_children(reaction):
            leaves.extend(_leaf_mol_nodes(child))
    return leaves


def _reaction_nodes(node: dict[str, Any]) -> list[dict[str, Any]]:
    reactions = _reaction_children(node)
    for child in _mol_children_from_reactions(reactions):
        reactions.extend(_reaction_nodes(child))
    return reactions


def _mol_children_from_reactions(reactions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    children: list[dict[str, Any]] = []
    for reaction in reactions:
        children.extend(_mol_children(reaction))
    return children


def _reaction_children(node: dict[str, Any]) -> list[dict[str, Any]]:
    children = node.get("children")
    if not isinstance(children, list):
        return []
    return [
        child
        for child in children
        if isinstance(child, dict) and (child.get("type") == "reaction" or child.get("is_reaction"))
    ]


def _mol_children(node: dict[str, Any]) -> list[dict[str, Any]]:
    children = node.get("children")
    if not isinstance(children, list):
        return []
    return [
        child
        for child in children
        if isinstance(child, dict) and (child.get("type") == "mol" or child.get("is_chemical"))
    ]


def _reaction_policy_probability(reaction: dict[str, Any]) -> float:
    metadata = _coerce_dict(reaction.get("metadata"))
    return _coerce_float(metadata.get("policy_probability")) or 0.0


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _coerce_int(value: Any) -> int | None:
    value = _first_scalar(value)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    value = _first_scalar(value)
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_bool(value: Any) -> bool:
    value = _first_scalar(value)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "solved"}
    return bool(value)


def _first_scalar(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _extract_container_name(command: list[str]) -> str | None:
    """Extract container name from Docker command if present."""
    try:
        if "docker" in command and "run" in command:
            # Look for --name flag
            if "--name" in command:
                name_index = command.index("--name")
                if name_index + 1 < len(command):
                    return command[name_index + 1]
    except (ValueError, IndexError):
        pass
    return None


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


def _check_gpu_available(docker_image: str = "aizynthfinder:latest") -> bool:
    """Check whether this image can actually use ONNX Runtime's CUDA provider."""
    try:
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--gpus",
                "all",
                "--entrypoint",
                "python",
                docker_image,
                "-c",
                (
                    "import onnxruntime as ort; "
                    "raise SystemExit(0 if 'CUDAExecutionProvider' "
                    "in ort.get_available_providers() else 2)"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False
