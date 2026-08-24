"""Minimal client for the ADB server wire protocol.

We talk to the local adb *server* (the daemon listening on 127.0.0.1:5037)
directly over TCP instead of shelling out to the `adb` executable for every
operation. Two reasons:

  1. We need to hold a raw binary stream open for minutes at a time (the video
     feed). Piping that through a subprocess adds buffering and, on Windows,
     newline translation hazards.
  2. Spawning a process per command is slow and pops console windows.

Protocol summary (see AOSP: docs/dev/services.txt):
  * every request is "%04x" % len(payload) followed by the payload
  * the server answers with "OKAY" or "FAIL" + "%04x" length + message
  * host services ("host:...") answer on a fresh connection and then close
  * to talk to a device you first send "host:transport:<serial>", after which
    the same socket carries a local service such as "shell:" or "exec:"
"""

from __future__ import annotations

import socket

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5037


class AdbError(RuntimeError):
    """Any failure reported by the adb server or a broken connection."""


class AdbTimeout(AdbError):
    """No data arrived in time. Distinct from end of stream, which is not an error."""


class AdbConnection:
    """One socket to the adb server, plus the length-prefixed framing."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        timeout: float | None = 10.0,
    ) -> None:
        try:
            self._sock = socket.create_connection((host, port), timeout or 10.0)
        except OSError as exc:
            raise AdbError(f"cannot reach the adb server at {host}:{port} ({exc})") from exc
        self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._sock.settimeout(timeout)
        self._closed = False

    # ---------------------------------------------------------------- framing

    def request(self, service: str) -> None:
        """Send a service request and consume the OKAY/FAIL that follows."""
        payload = service.encode("utf-8")
        self._send(b"%04x" % len(payload) + payload)
        self.read_status()

    def read_status(self) -> None:
        status = self.read_exact(4)
        if status == b"OKAY":
            return
        if status == b"FAIL":
            raise AdbError(self.read_message())
        raise AdbError(f"unexpected adb reply {status!r}")

    def read_message(self) -> str:
        """Read a "%04x"-length-prefixed string."""
        raw = self.read_exact(4)
        try:
            length = int(raw, 16)
        except ValueError:
            return raw.decode("utf-8", "replace")
        if length == 0:
            return ""
        return self.read_exact(length).decode("utf-8", "replace")

    # ------------------------------------------------------------------ io

    def _send(self, data: bytes) -> None:
        try:
            self._sock.sendall(data)
        except OSError as exc:
            raise AdbError(f"adb write failed: {exc}") from exc

    def send_raw(self, data: bytes) -> None:
        self._send(data)

    def read_exact(self, count: int) -> bytes:
        chunks = []
        remaining = count
        while remaining > 0:
            try:
                chunk = self._sock.recv(remaining)
            except socket.timeout as exc:
                raise AdbTimeout("adb read timed out") from exc
            except OSError as exc:
                raise AdbError(f"adb read failed: {exc}") from exc
            if not chunk:
                raise AdbError("adb connection closed early")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def read_some(self, size: int = 65536) -> bytes:
        """Read whatever is available.

        Returns b'' at end of stream and raises AdbTimeout when the socket is
        merely quiet. Callers streaming video need that distinction: a silent
        second is normal, a closed socket means the capture died.
        """
        try:
            return self._sock.recv(size)
        except socket.timeout as exc:
            raise AdbTimeout("no data") from exc
        except OSError as exc:
            raise AdbError(f"adb read failed: {exc}") from exc

    def read_until_eof(self, limit: int = 8 << 20) -> bytes:
        out = bytearray()
        while len(out) < limit:
            try:
                chunk = self.read_some()
            except AdbTimeout:
                break
            if not chunk:
                break
            out += chunk
        return bytes(out)

    def set_timeout(self, timeout: float | None) -> None:
        self._sock.settimeout(timeout)

    # --------------------------------------------------------------- teardown

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self._sock.close()
        except OSError:
            pass

    def __enter__(self) -> "AdbConnection":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
