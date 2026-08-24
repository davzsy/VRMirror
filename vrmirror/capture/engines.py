"""Capture engines: the two ways we get an H.264 stream off the device.

screenrecord
    Uses the `screenrecord` binary that ships with every Android build, asking
    it for a raw elementary stream on stdout. Nothing is installed on the
    device, it works on a stock headset in developer mode, and it is the safe
    default. Costs: a few hundred ms of extra latency, no audio, and a time
    limit per invocation on some builds (we restart transparently).

native
    Pushes our own tiny server (server/ in this repo, compiled to a .dex) and
    runs it with app_process. It grabs the display through SurfaceControl,
    encodes with MediaCodec and streams frames back over a reversed socket.
    This is what Vysor and scrcpy do, and it is where the low latency lives.
    Optional: the app falls back to screenrecord when the .dex is absent.

Both expose the same interface: iterate `stream()`, which yields either bytes
of Annex-B video or None to signal "the feed restarted, reset your decoder".
"""

from __future__ import annotations

import logging
import socket
import struct
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from ..adb.client import Device
from ..adb.protocol import AdbError, AdbTimeout

log = logging.getLogger(__name__)

DEVICE_SERVER_PATH = "/data/local/tmp/vrmirror-server.dex"
SERVER_SOCKET_NAME = "vrmirror"
SERVER_MAGIC = b"VRM1"


class EngineUnavailable(RuntimeError):
    """Raised when an engine cannot run on this device or build."""


@dataclass
class EngineOptions:
    bitrate_bps: int = 12_000_000
    fps: int = 60
    max_size: int = 0  # 0 keeps the device's native resolution
    time_limit_s: int = 1800


def _scaled_size(device: Device, max_size: int) -> tuple[int, int] | None:
    """Fit the device display inside max_size, keeping aspect and even sides."""
    if max_size <= 0:
        return None
    size = device.screen_size()
    if not size:
        return None
    width, height = size
    longest = max(width, height)
    if longest <= max_size:
        return None
    scale = max_size / longest
    return (max(2, int(width * scale) & ~1), max(2, int(height * scale) & ~1))


class ScreenrecordEngine:
    name = "screenrecord"

    def __init__(self, device: Device, options: EngineOptions) -> None:
        self.device = device
        self.options = options
        self._stop = False
        self._connection = None
        self._time_limit = options.time_limit_s or 1800

    def request_stop(self) -> None:
        self._stop = True
        connection = self._connection
        if connection is not None:
            connection.close()

    def _build_command(self, time_limit: int) -> str:
        parts = [
            "screenrecord",
            "--output-format=h264",
            f"--bit-rate={int(self.options.bitrate_bps)}",
        ]
        size = _scaled_size(self.device, self.options.max_size)
        if size:
            parts.append(f"--size {size[0]}x{size[1]}")
        if time_limit > 0:
            parts.append(f"--time-limit {int(time_limit)}")
        parts.append("-")
        return " ".join(parts)

    def stream(self):
        """Yield chunks forever, restarting screenrecord when it exits.

        Older builds cap --time-limit at 180 seconds and refuse to start with
        anything larger. We optimistically ask for the configured limit and,
        if the first attempt dies without producing a single byte, drop back to
        180 and remember that for the rest of the session.
        """
        time_limit = self._time_limit
        first_attempt = True

        while not self._stop:
            command = self._build_command(time_limit)
            log.info("starting capture: %s", command)
            produced = 0
            started = time.monotonic()

            try:
                self._connection = self.device.exec_stream(command, timeout=20.0)
            except AdbError as exc:
                raise EngineUnavailable(f"could not start screenrecord: {exc}") from exc

            try:
                while not self._stop:
                    try:
                        chunk = self._connection.read_some(65536)
                    except AdbTimeout:
                        # A static screen can go quiet for a while. Silence is
                        # not the same as the encoder having stopped.
                        continue
                    if not chunk:
                        break
                    produced += len(chunk)
                    yield chunk
            except AdbError as exc:
                if not self._stop:
                    log.warning("capture stream error: %s", exc)
            finally:
                if self._connection is not None:
                    self._connection.close()
                    self._connection = None

            if self._stop:
                break

            elapsed = time.monotonic() - started
            if produced == 0:
                if first_attempt and time_limit != 180:
                    log.info("device rejected --time-limit %s, falling back to 180", time_limit)
                    time_limit = 180
                    first_attempt = False
                    continue
                raise EngineUnavailable(
                    "screenrecord produced no video. On a headset make sure the "
                    "USB debugging prompt was accepted, and that no other "
                    "capture or casting session is running."
                )

            first_attempt = False
            if elapsed < 1.0:
                time.sleep(0.5)
            # New encoder instance: parameter sets change, so reset downstream.
            yield None


class NativeEngine:
    """Our own device-side server. Lowest latency, needs the compiled .dex."""

    name = "native"

    def __init__(self, device: Device, options: EngineOptions) -> None:
        self.device = device
        self.options = options
        self._stop = False
        self._listener: socket.socket | None = None
        self._client: socket.socket | None = None
        self._shell = None
        self.video_size: tuple[int, int] | None = None

    # ------------------------------------------------------------------ setup

    @staticmethod
    def server_dex() -> Path | None:
        root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
        for candidate in (
            root / "assets" / "vrmirror-server.dex",
            root / "server" / "build" / "vrmirror-server.dex",
        ):
            if candidate.exists():
                return candidate
        return None

    @classmethod
    def is_available(cls) -> bool:
        return cls.server_dex() is not None

    def request_stop(self) -> None:
        self._stop = True
        for resource in (self._client, self._listener):
            try:
                if resource is not None:
                    resource.close()
            except OSError:
                pass
        if self._shell is not None:
            self._shell.close()
            self._shell = None
        try:
            self.device.reverse_remove(f"localabstract:{SERVER_SOCKET_NAME}")
        except Exception:
            pass

    def _start_listener(self) -> int:
        self._listener = socket.socket()
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(1)
        self._listener.settimeout(10.0)
        return self._listener.getsockname()[1]

    def _launch(self) -> None:
        dex = self.server_dex()
        if dex is None:
            raise EngineUnavailable(
                "the device server has not been built. Run server/build.sh with "
                "an Android SDK installed, or use the screenrecord engine."
            )

        self.device.push_bytes(dex.read_bytes(), DEVICE_SERVER_PATH)

        port = self._start_listener()
        self.device.reverse(f"localabstract:{SERVER_SOCKET_NAME}", f"tcp:{port}")

        size = _scaled_size(self.device, self.options.max_size)
        args = [
            f"bitrate={int(self.options.bitrate_bps)}",
            f"fps={int(self.options.fps)}",
            f"max_size={int(self.options.max_size)}",
            f"socket={SERVER_SOCKET_NAME}",
        ]
        if size:
            args.append(f"size={size[0]}x{size[1]}")

        command = (
            f"CLASSPATH={DEVICE_SERVER_PATH} app_process / "
            f"com.vrmirror.server.Main " + " ".join(args)
        )
        self._shell = self.device.exec_stream(command, timeout=None)

    def _accept(self) -> None:
        assert self._listener is not None
        try:
            self._client, _ = self._listener.accept()
        except socket.timeout as exc:
            detail = ""
            if self._shell is not None:
                try:
                    self._shell.set_timeout(0.5)
                    detail = self._shell.read_some(4096).decode("utf-8", "replace").strip()
                except Exception:
                    detail = ""
            raise EngineUnavailable(
                "the device server did not connect back"
                + (f": {detail}" if detail else "")
            ) from exc
        self._client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._client.settimeout(10.0)

    def _read_exact(self, count: int) -> bytes | None:
        assert self._client is not None
        chunks = []
        remaining = count
        while remaining > 0:
            try:
                chunk = self._client.recv(remaining)
            except (socket.timeout, OSError):
                return None
            if not chunk:
                return None
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    # ----------------------------------------------------------------- stream

    def stream(self):
        self._launch()
        self._accept()

        header = self._read_exact(12)
        if not header or not header.startswith(SERVER_MAGIC):
            raise EngineUnavailable("the device server sent an unexpected header")
        width, height = struct.unpack(">II", header[4:12])
        self.video_size = (width, height)
        log.info("native engine streaming %sx%s", width, height)

        while not self._stop:
            meta = self._read_exact(12)
            if meta is None:
                break
            _pts, length = struct.unpack(">QI", meta)
            if length == 0 or length > 32 << 20:
                break
            payload = self._read_exact(length)
            if payload is None:
                break
            yield payload


def build_engine(device: Device, options: EngineOptions, preference: str = "auto"):
    """Pick an engine. 'auto' uses the native server when it is available."""
    if preference == "native":
        return NativeEngine(device, options)
    if preference == "screenrecord":
        return ScreenrecordEngine(device, options)
    if NativeEngine.is_available():
        return NativeEngine(device, options)
    return ScreenrecordEngine(device, options)
