"""Locating and starting the adb executable.

Priority order:
  1. VRMIRROR_ADB environment variable
  2. adb bundled next to the app (assets/platform-tools/) so a packaged build
     is self contained and works with no Android SDK installed
  3. adb on PATH
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from .protocol import DEFAULT_HOST, DEFAULT_PORT


class AdbNotFound(RuntimeError):
    pass


def _resource_root() -> Path:
    """Directory that holds bundled assets, frozen or running from source."""
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return Path(bundled)
    return Path(__file__).resolve().parent.parent.parent


def _exe_name() -> str:
    return "adb.exe" if os.name == "nt" else "adb"


def adb_path() -> str:
    override = os.environ.get("VRMIRROR_ADB")
    if override and Path(override).exists():
        return override

    root = _resource_root()
    candidates = [
        root / "assets" / "platform-tools" / _exe_name(),
        root / "platform-tools" / _exe_name(),
        root / _exe_name(),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    found = shutil.which("adb")
    if found:
        return found

    raise AdbNotFound(
        "adb was not found. Install Android platform-tools and put adb on your "
        "PATH, drop it in assets/platform-tools/ next to VRMirror, or set the "
        "VRMIRROR_ADB environment variable."
    )


def _no_window_kwargs() -> dict:
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return {
        "startupinfo": startupinfo,
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
    }


def run_adb(args: list[str], timeout: float = 20.0) -> subprocess.CompletedProcess:
    """Run the adb executable directly. Used only for server lifecycle."""
    return subprocess.run(
        [adb_path(), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        **_no_window_kwargs(),
    )


def ensure_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    """Start the adb server if it is not already listening."""
    import socket

    with socket.socket() as probe:
        probe.settimeout(0.4)
        if probe.connect_ex((host, port)) == 0:
            return

    result = run_adb(["start-server"], timeout=30.0)
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        raise AdbNotFound(f"could not start the adb server: {message}")


def kill_server() -> None:
    try:
        run_adb(["kill-server"], timeout=10.0)
    except Exception:
        pass
