"""Runtime configuration for external scientific tools.

Environment variables override ``configs/tools.yaml`` so production deployments
can change images and timeouts without editing the repository.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import yaml


@dataclass(frozen=True)
class ToolRuntimeConfig:
    name: str
    command: str | None
    docker_images: tuple[str, ...]
    timeout_seconds: int
    config_source: str
    config_loaded: bool
    environment_overrides: tuple[str, ...] = ()

    @property
    def docker_image(self) -> str | None:
        return self.docker_images[0] if self.docker_images else None

    def as_status(self) -> dict[str, Any]:
        return {
            "configured_command": self.command,
            "docker_image_candidates": list(self.docker_images),
            "configured_timeout_seconds": self.timeout_seconds,
            "config_source": self.config_source,
            "config_loaded": self.config_loaded,
            "config_environment_overrides": list(self.environment_overrides),
        }


def get_tool_runtime_config(
    name: str,
    *,
    default_command: str | None = None,
    default_images: Iterable[str] = (),
    default_timeout_seconds: int,
) -> ToolRuntimeConfig:
    normalized_name = name.strip().lower()
    env_prefix = normalized_name.upper().replace("-", "_")
    section, config_source, config_loaded = _tool_section(normalized_name)
    overrides: list[str] = []

    command = _environment_value(
        [f"MEDAGENT_{env_prefix}_COMMAND", f"{env_prefix}_COMMAND"],
        overrides,
    )
    if command is None:
        configured_command = section.get("command")
        command = str(configured_command).strip() if configured_command else default_command

    image = _environment_value(
        [f"MEDAGENT_{env_prefix}_IMAGE", f"{env_prefix}_IMAGE"],
        overrides,
    )
    if image:
        docker_images = (image,)
    else:
        docker_images = _configured_images(section, default_images)

    timeout_value = _environment_value(
        [
            f"MEDAGENT_{env_prefix}_TIMEOUT_SECONDS",
            f"{env_prefix}_TIMEOUT_SECONDS",
        ],
        overrides,
    )
    if timeout_value is None:
        timeout_value = section.get("timeout_seconds")
    timeout_seconds = _positive_int(timeout_value, default_timeout_seconds)

    return ToolRuntimeConfig(
        name=normalized_name,
        command=command,
        docker_images=docker_images,
        timeout_seconds=timeout_seconds,
        config_source=config_source,
        config_loaded=config_loaded,
        environment_overrides=tuple(overrides),
    )


def _tool_section(name: str) -> tuple[dict[str, Any], str, bool]:
    config_path = _resolve_tools_config_path()
    if config_path is None:
        return {}, "built_in_defaults", False
    document, config_loaded = _load_tools_document(str(config_path))
    tools = document.get("tools") if isinstance(document, dict) else None
    section = tools.get(name) if isinstance(tools, dict) else None
    return (
        section if isinstance(section, dict) else {},
        str(config_path),
        config_loaded,
    )


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
    if not isinstance(parsed, dict):
        return {}, False
    return parsed, True


def _configured_images(section: dict[str, Any], defaults: Iterable[str]) -> tuple[str, ...]:
    values: list[str] = []
    configured_images = section.get("docker_images")
    if isinstance(configured_images, list):
        values.extend(str(value).strip() for value in configured_images if value)
    configured_image = section.get("docker_image")
    if configured_image:
        values.append(str(configured_image).strip())
    values.extend(str(value).strip() for value in defaults if value)
    return tuple(dict.fromkeys(value for value in values if value))


def _environment_value(names: list[str], overrides: list[str]) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value is not None and value.strip():
            overrides.append(name)
            return value.strip()
    return None


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default
