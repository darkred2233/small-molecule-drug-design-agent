"""Translate API-container paths into paths visible to sibling tool containers."""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


class DockerPathNotSharedError(RuntimeError):
    """Raised when a container-private path cannot be mounted by the host daemon."""


@dataclass(frozen=True)
class ContainerMount:
    mount_type: str
    source: str
    destination: str
    name: str | None = None
    read_write: bool = True


def docker_temporary_directory(prefix: str) -> tempfile.TemporaryDirectory[str]:
    root = os.environ.get("MEDAGENT_DOCKER_WORK_ROOT")
    if not root:
        return tempfile.TemporaryDirectory(prefix=prefix)
    work_root = Path(root).expanduser().resolve()
    work_root.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(prefix=prefix, dir=work_root)


class DockerMountBuilder:
    def __init__(
        self,
        mounts: Iterable[ContainerMount] | None = None,
        *,
        containerized: bool | None = None,
    ) -> None:
        self._containerized = _is_containerized() if containerized is None else containerized
        self._mounts = sorted(
            list(current_container_mounts() if mounts is None else mounts),
            key=lambda mount: len(mount.destination),
            reverse=True,
        )
        self._arguments: list[str] = []
        self._mounted_volumes: dict[str, str] = {}

    @property
    def arguments(self) -> list[str]:
        return list(self._arguments)

    def bind(self, source: str | Path, target: str, *, read_only: bool = False) -> str:
        source_path = Path(source).expanduser().resolve()
        mount = self._find_mount(source_path)
        if mount is None:
            if self._containerized:
                raise DockerPathNotSharedError(
                    f"Path is private to the API container and cannot be shared: {source_path}"
                )
            suffix = ":ro" if read_only else ""
            self._arguments.extend(["-v", f"{source_path}:{target}{suffix}"])
            return target

        relative_path = _relative_to_container_mount(source_path, mount.destination)
        if mount.mount_type == "volume" and mount.name:
            volume_root = self._mount_volume(mount)
            return str(PurePosixPath(volume_root, *relative_path.parts))

        if mount.mount_type == "bind":
            host_source = Path(mount.source, *relative_path.parts)
            suffix = ":ro" if read_only or not mount.read_write else ""
            self._arguments.extend(["-v", f"{host_source}:{target}{suffix}"])
            return target

        raise DockerPathNotSharedError(
            f"Unsupported API container mount type for {source_path}: {mount.mount_type}"
        )

    def _find_mount(self, source_path: Path) -> ContainerMount | None:
        source_text = source_path.as_posix()
        for mount in self._mounts:
            destination = PurePosixPath(mount.destination).as_posix().rstrip("/")
            if source_text == destination or source_text.startswith(destination + "/"):
                return mount
        return None

    def _mount_volume(self, mount: ContainerMount) -> str:
        assert mount.name
        if mount.name in self._mounted_volumes:
            return self._mounted_volumes[mount.name]
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", mount.name)
        target = f"/medagent-volumes/{safe_name}"
        spec = f"type=volume,src={mount.name},dst={target}"
        if not mount.read_write:
            spec += ",readonly"
        self._arguments.extend(["--mount", spec])
        self._mounted_volumes[mount.name] = target
        return target


@lru_cache(maxsize=1)
def current_container_mounts() -> tuple[ContainerMount, ...]:
    if not _is_containerized():
        return ()
    container_id = os.environ.get("MEDAGENT_DOCKER_CONTAINER_ID") or socket.gethostname()
    try:
        completed = subprocess.run(
            ["docker", "inspect", "--format", "{{json .Mounts}}", container_id],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return ()
    if completed.returncode != 0:
        return ()
    try:
        raw_mounts: list[dict[str, Any]] = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError):
        return ()
    mounts = []
    for raw in raw_mounts:
        destination = raw.get("Destination")
        source = raw.get("Source")
        if not destination or not source or destination == "/var/run/docker.sock":
            continue
        mounts.append(
            ContainerMount(
                mount_type=str(raw.get("Type") or ""),
                source=str(source),
                destination=str(destination),
                name=raw.get("Name"),
                read_write=bool(raw.get("RW", True)),
            )
        )
    return tuple(mounts)


def _is_containerized() -> bool:
    return Path("/.dockerenv").exists() or bool(os.environ.get("MEDAGENT_DOCKER_CONTAINER_ID"))


def _relative_to_container_mount(path: Path, destination: str) -> Path:
    path_text = path.as_posix()
    destination_text = PurePosixPath(destination).as_posix().rstrip("/")
    relative = path_text[len(destination_text) :].lstrip("/")
    return Path(relative) if relative else Path()
