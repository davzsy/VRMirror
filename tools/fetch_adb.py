#!/usr/bin/env python3
"""Download Android platform-tools so the packaged app is self contained.

Run once before building. The files land in assets/platform-tools/ and are
picked up both when running from source and inside the frozen build.

Only adb and the libraries it needs are kept; the rest of platform-tools is
about 20 MB of things we never call.
"""

from __future__ import annotations

import argparse
import io
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

BASE = "https://dl.google.com/android/repository/platform-tools-latest-{}.zip"

PLATFORM_KEYS = {
    "win32": "windows",
    "darwin": "darwin",
    "linux": "linux",
}

# adb plus the runtime libraries it loads on each platform.
KEEP = {
    "windows": ["adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll", "libwinpthread-1.dll"],
    "darwin": ["adb"],
    "linux": ["adb", "libc++.so"],
}


def fetch(target_os: str, destination: Path) -> None:
    url = BASE.format(target_os)
    print(f"downloading {url}")
    with urllib.request.urlopen(url, timeout=120) as response:
        payload = response.read()
    print(f"  {len(payload) / (1 << 20):.1f} MB")

    destination.mkdir(parents=True, exist_ok=True)
    wanted = KEEP[target_os]
    written = []

    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for entry in archive.namelist():
            name = Path(entry).name
            if not name or name not in wanted:
                continue
            out = destination / name
            with archive.open(entry) as source, open(out, "wb") as sink:
                shutil.copyfileobj(source, sink)
            if not name.lower().endswith((".dll", ".so")):
                out.chmod(0o755)
            written.append(name)

    missing = [name for name in wanted if name not in written]
    print(f"  wrote {', '.join(written)} to {destination}")
    if missing:
        print(f"  note: not present in this release: {', '.join(missing)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--os",
        dest="target_os",
        choices=sorted(set(PLATFORM_KEYS.values())),
        default=PLATFORM_KEYS.get(sys.platform, "linux"),
        help="platform to download adb for (defaults to the current one)",
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "assets" / "platform-tools",
    )
    args = parser.parse_args()

    fetch(args.target_os, args.dest)
    print(
        "\nadb is redistributed under the Android Software Development Kit "
        "License Agreement. Keep this build for personal use, or ship without "
        "assets/platform-tools/ and let users supply their own adb."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
