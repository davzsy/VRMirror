#!/usr/bin/env python3
"""Build a standalone VRMirror application.

    python tools/build.py                 # build for the current platform
    python tools/build.py --onefile       # single executable, slower to start
    python tools/build.py --skip-adb      # do not download platform-tools

PyInstaller is not a cross compiler: a Windows .exe has to be produced on
Windows. If you are on macOS or Linux and want the .exe, push to GitHub and let
.github/workflows/build.yml do it, or run this inside a Windows VM.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(command: list[str]) -> None:
    print(f"$ {' '.join(command)}")
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def ensure_pyinstaller() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is missing, installing it...")
        run([sys.executable, "-m", "pip", "install", "pyinstaller>=6.3"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--onefile", action="store_true", help="produce a single executable")
    parser.add_argument("--skip-adb", action="store_true", help="do not bundle adb")
    parser.add_argument("--clean", action="store_true", help="wipe build/ and dist/ first")
    args = parser.parse_args()

    if args.clean:
        for directory in ("build", "dist"):
            shutil.rmtree(ROOT / directory, ignore_errors=True)

    if not args.skip_adb:
        tools = ROOT / "assets" / "platform-tools"
        if not tools.is_dir() or not any(tools.iterdir()):
            print("fetching adb...")
            run([sys.executable, str(ROOT / "tools" / "fetch_adb.py")])
        else:
            print(f"adb already present in {tools}")

    ensure_pyinstaller()

    if args.onefile:
        # The spec file builds a directory; onefile is simple enough to express
        # on the command line instead of maintaining a second spec.
        command = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--windowed",
            "--name",
            "VRMirror",
            "--hidden-import",
            "av",
        ]
        tools = ROOT / "assets" / "platform-tools"
        separator = ";" if os.name == "nt" else ":"
        if tools.is_dir():
            command += ["--add-data", f"{tools}{separator}assets/platform-tools"]
        dex = ROOT / "assets" / "vrmirror-server.dex"
        if dex.is_file():
            command += ["--add-data", f"{dex}{separator}assets"]
        icon = ROOT / "assets" / ("icon.ico" if os.name == "nt" else "icon.icns")
        if icon.is_file():
            command += ["--icon", str(icon)]
        command.append(str(ROOT / "run.py"))
        run(command)
    else:
        run(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--clean",
                str(ROOT / "tools" / "VRMirror.spec"),
            ]
        )

    dist = ROOT / "dist"
    print("\nBuild finished. Artifacts in:")
    for entry in sorted(dist.glob("*")):
        print(f"  {entry}")

    if sys.platform != "win32":
        print(
            "\nThis is a build for "
            f"{sys.platform}. For a Windows .exe, run this script on Windows or "
            "use the GitHub Actions workflow in .github/workflows/build.yml."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
