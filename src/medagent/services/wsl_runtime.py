"""Helpers for invoking Linux chemistry runtimes from the Windows service."""

from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path
from typing import Mapping, Sequence


_WINDOWS_DRIVE_PATH = re.compile(r"^([A-Za-z]):[\\/](.*)$")
_WSL_MOUNT_PATH = re.compile(r"^/mnt/([A-Za-z])(?:/(.*))?$")


def windows_path_to_wsl(value: str | Path) -> str:
    """Convert a local Windows drive path to the path exposed by WSL."""
    raw = str(value)
    match = _WINDOWS_DRIVE_PATH.match(raw)
    if match is None:
        return raw.replace("\\", "/")
    drive, remainder = match.groups()
    return f"/mnt/{drive.lower()}/{remainder.replace(chr(92), '/')}"


def windows_path_from_wsl(value: str | Path) -> Path:
    """Convert a WSL-mounted Windows drive path back to a host path."""
    raw = str(value)
    match = _WSL_MOUNT_PATH.match(raw)
    if match is None:
        return Path(raw)
    drive, remainder = match.groups()
    suffix = (remainder or "").replace("/", "\\")
    return Path(f"{drive.upper()}:\\{suffix}")


def build_wsl_command(
    arguments: Sequence[str],
    *,
    distribution: str = "Ubuntu",
    user: str = "root",
    cwd: str | None = None,
    environment: Mapping[str, str] | None = None,
) -> list[str]:
    """Build a safely quoted `wsl ... bash -lc` command."""
    environment_args = [f"{key}={value}" for key, value in (environment or {}).items()]
    invocation = ["env", *environment_args, *map(str, arguments)]
    shell_command = f"exec {shlex.join(invocation)}"
    if cwd:
        shell_command = f"cd {shlex.quote(cwd)} && {shell_command}"
    return [
        "wsl",
        "-d",
        distribution,
        "-u",
        user,
        "--",
        "bash",
        "-lc",
        shell_command,
    ]


def wsl_file_exists(
    path: str,
    *,
    distribution: str = "Ubuntu",
    user: str = "root",
    timeout_seconds: int = 15,
) -> bool:
    """Return whether a regular file exists inside the configured WSL distro."""
    try:
        completed = subprocess.run(
            ["wsl", "-d", distribution, "-u", user, "--", "test", "-f", path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0
