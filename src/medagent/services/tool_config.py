"""Configuration for locally installed scientific tools.

External chemistry programs are deliberately launched from their local
executables or dedicated Python environments.  This module has no container
fallback: a tool is usable only when its configured local runtime and required
files can be inspected on the host.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ToolRuntimeConfig:
    name: str
    command: str | None
    python_executable: str | None
    working_directory: str | None
    timeout_seconds: int
    required_paths: tuple[str, ...]
    config_source: str
    config_loaded: bool
    runtime: str = "host"
    wsl_distribution: str = "Ubuntu"
    wsl_user: str = "root"
    runtime_environment: tuple[tuple[str, str], ...] = ()
    environment_overrides: tuple[str, ...] = ()

    def environment_dict(self) -> dict[str, str]:
        return dict(self.runtime_environment)

    def as_status(self) -> dict[str, Any]:
        return {
            "configured_command": self.command,
            "configured_python_executable": self.python_executable,
            "configured_working_directory": self.working_directory,
            "configured_required_paths": list(self.required_paths),
            "configured_timeout_seconds": self.timeout_seconds,
            "config_source": self.config_source,
            "config_loaded": self.config_loaded,
            "config_environment_overrides": list(self.environment_overrides),
            "runtime_scope": self.runtime,
            "wsl_distribution": self.wsl_distribution if self.runtime == "wsl" else None,
            "wsl_user": self.wsl_user if self.runtime == "wsl" else None,
            "runtime_environment": self.environment_dict(),
        }


def get_tool_runtime_config(
    name: str,
    *,
    default_command: str | None = None,
    default_timeout_seconds: int,
) -> ToolRuntimeConfig:
    normalized_name = name.strip().lower()
    env_prefix = normalized_name.upper().replace("-", "_")
    section, config_source, config_loaded = _tool_section(normalized_name)
    overrides: list[str] = []

    command = _environment_value(
        [f"MEDAGENT_{env_prefix}_COMMAND", f"{env_prefix}_COMMAND"], overrides
    )
    if command is None:
        configured_command = section.get("command")
        command = str(configured_command).strip() if configured_command else default_command

    python_executable = _environment_value(
        [f"MEDAGENT_{env_prefix}_PYTHON", f"{env_prefix}_PYTHON"], overrides
    )
    if python_executable is None and section.get("python_executable"):
        python_executable = str(section["python_executable"]).strip()

    working_directory = _environment_value(
        [f"MEDAGENT_{env_prefix}_WORKDIR", f"{env_prefix}_WORKDIR"], overrides
    )
    if working_directory is None and section.get("working_directory"):
        working_directory = str(section["working_directory"]).strip()

    timeout_value = _environment_value(
        [f"MEDAGENT_{env_prefix}_TIMEOUT_SECONDS", f"{env_prefix}_TIMEOUT_SECONDS"],
        overrides,
    )
    if timeout_value is None:
        timeout_value = section.get("timeout_seconds")

    required_paths = _string_list(section.get("required_paths"))
    runtime = (
        _environment_value([f"MEDAGENT_{env_prefix}_RUNTIME", f"{env_prefix}_RUNTIME"], overrides)
        or str(section.get("runtime") or "host").strip().lower()
    )
    if runtime not in {"host", "wsl"}:
        runtime = "host"
    wsl_distribution = (
        _environment_value([f"MEDAGENT_{env_prefix}_WSL_DISTRIBUTION"], overrides)
        or str(section.get("wsl_distribution") or "Ubuntu").strip()
    )
    wsl_user = (
        _environment_value([f"MEDAGENT_{env_prefix}_WSL_USER"], overrides)
        or str(section.get("wsl_user") or "root").strip()
    )
    return ToolRuntimeConfig(
        name=normalized_name,
        command=command,
        python_executable=python_executable,
        working_directory=working_directory,
        timeout_seconds=_positive_int(timeout_value, default_timeout_seconds),
        required_paths=required_paths,
        config_source=config_source,
        config_loaded=config_loaded,
        runtime=runtime,
        wsl_distribution=wsl_distribution,
        wsl_user=wsl_user,
        runtime_environment=_string_mapping(section.get("environment")),
        environment_overrides=tuple(overrides),
    )


def configured_paths_exist(config: ToolRuntimeConfig) -> tuple[bool, list[str]]:
    """Return whether every configured resource exists, with missing paths."""
    missing: list[str] = []
    for raw_path in config.required_paths:
        path = _resolve_path(raw_path)
        if not path.exists():
            missing.append(str(path))
    return not missing, missing


def resolve_configured_path(value: str | None) -> Path | None:
    return _resolve_path(value) if value else None


def _tool_section(name: str) -> tuple[dict[str, Any], str, bool]:
    config_path = _resolve_tools_config_path()
    if config_path is None:
        return {}, "built_in_defaults", False
    document, config_loaded = _load_tools_document(str(config_path))
    tools = document.get("tools") if isinstance(document, dict) else None
    section = tools.get(name) if isinstance(tools, dict) else None
    return section if isinstance(section, dict) else {}, str(config_path), config_loaded


def _resolve_tools_config_path() -> Path | None:
    configured = os.environ.get("MEDAGENT_TOOLS_CONFIG")
    if configured:
        return Path(configured).expanduser().resolve()
    repository_root = Path(__file__).resolve().parents[3]
    candidates = [repository_root / "configs" / "tools.yaml", Path.cwd() / "configs" / "tools.yaml"]
    for candidate in dict.fromkeys(path.resolve() for path in candidates):
        if candidate.is_file():
            return candidate
    return None


@lru_cache(maxsize=4)
def _load_tools_document(config_path: str) -> tuple[dict[str, Any], bool]:
    try:
        parsed = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}, False
    return (parsed, True) if isinstance(parsed, dict) else ({}, False)


def _environment_value(names: list[str], overrides: list[str]) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value is not None and value.strip():
            overrides.append(name)
            return value.strip()
    return None


def _string_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _string_mapping(value: Any) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, dict):
        return ()
    return tuple(
        (str(key).strip(), str(item).strip())
        for key, item in value.items()
        if str(key).strip() and str(item).strip()
    )


def _resolve_path(value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (Path(__file__).resolve().parents[3] / path).resolve()


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default
