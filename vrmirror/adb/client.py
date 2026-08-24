"""High level ADB operations built on the raw protocol."""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass

from .protocol import DEFAULT_HOST, DEFAULT_PORT, AdbConnection, AdbError, AdbTimeout

# st_mode values sent with a sync SEND request.
MODE_EXEC = 0o100755
MODE_FILE = 0o100644

SYNC_CHUNK = 64 * 1024


@dataclass(frozen=True)
class DeviceInfo:
    serial: str
    state: str
    model: str = ""
    product: str = ""
    device: str = ""
    transport_id: str = ""

    @property
    def is_wireless(self) -> bool:
        return ":" in self.serial and not self.serial.startswith("emulator")

    @property
    def is_usable(self) -> bool:
        return self.state == "device"

    @property
    def label(self) -> str:
        name = self.model.replace("_", " ") if self.model else self.serial
        return f"{name} ({'Wi-Fi' if self.is_wireless else 'USB'})"


def _parse_devices(payload: str) -> list[DeviceInfo]:
    devices: list[DeviceInfo] = []
    for line in payload.splitlines():
        line = line.strip()
        if not line or line.startswith("List of devices"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        fields = {}
        for token in parts[2:]:
            if ":" in token:
                key, _, value = token.partition(":")
                fields[key] = value
        devices.append(
            DeviceInfo(
                serial=parts[0],
                state=parts[1],
                model=fields.get("model", ""),
                product=fields.get("product", ""),
                device=fields.get("device", ""),
                transport_id=fields.get("transport_id", ""),
            )
        )
    return devices


class Adb:
    """Host level services: listing, connecting and pairing devices."""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
        self.host = host
        self.port = port

    def connection(self, timeout: float | None = 10.0) -> AdbConnection:
        return AdbConnection(self.host, self.port, timeout)

    def _query(self, service: str, timeout: float = 10.0) -> str:
        with self.connection(timeout) as conn:
            conn.request(service)
            return conn.read_message()

    def server_version(self) -> int:
        return int(self._query("host:version") or "0", 16)

    def devices(self) -> list[DeviceInfo]:
        return _parse_devices(self._query("host:devices-l"))

    def connect(self, address: str) -> str:
        if ":" not in address:
            address = f"{address}:5555"
        try:
            return self._query(f"host:connect:{address}", timeout=20.0).strip()
        except AdbError as exc:
            return str(exc)

    def disconnect(self, address: str) -> str:
        try:
            return self._query(f"host:disconnect:{address}", timeout=10.0).strip()
        except AdbError as exc:
            return str(exc)

    def pair(self, address: str, code: str) -> str:
        """Android 11+ wireless debugging pairing (`adb pair host:port code`)."""
        try:
            return self._query(f"host:pair:{code}:{address}", timeout=30.0).strip()
        except AdbError as exc:
            return str(exc)

    def device(self, serial: str) -> "Device":
        return Device(self, serial)

    # ------------------------------------------------------------- device feed

    def track_devices(self, on_change, should_stop) -> None:
        """Block on host:track-devices, calling on_change(list[DeviceInfo]).

        The adb server pushes a fresh, length-prefixed device list every time
        anything is plugged in, unplugged or authorised, so the UI never has to
        poll. Reconnects on its own if the server restarts.
        """
        # track-devices-l carries the model name; older adb servers only know
        # the plain form, so fall back rather than showing nothing.
        services = ["host:track-devices-l", "host:track-devices"]
        service_index = 0

        while not should_stop():
            conn = None
            try:
                conn = self.connection(timeout=None)
                try:
                    conn.request(services[service_index])
                except AdbError:
                    if service_index + 1 < len(services):
                        service_index += 1
                        conn.close()
                        continue
                    raise

                while not should_stop():
                    conn.set_timeout(1.0)
                    try:
                        header = conn.read_exact(4)
                    except AdbTimeout:
                        continue
                    try:
                        length = int(header, 16)
                    except ValueError:
                        raise AdbError("device feed desynchronised")
                    if length > (1 << 20):
                        raise AdbError("device feed desynchronised")
                    conn.set_timeout(10.0)
                    payload = conn.read_exact(length).decode("utf-8", "replace") if length else ""
                    on_change(_parse_devices(payload))
            except AdbError:
                if should_stop():
                    break
                time.sleep(1.5)
            finally:
                if conn is not None:
                    conn.close()


class Device:
    """Operations that run against one device via host:transport."""

    def __init__(self, adb: Adb, serial: str) -> None:
        self.adb = adb
        self.serial = serial
        self._prop_cache: dict[str, str] = {}
        self._lock = threading.Lock()

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Device {self.serial}>"

    # ------------------------------------------------------------- primitives

    def open(self, service: str, timeout: float | None = 15.0) -> AdbConnection:
        """Attach to the device and start a local service on the same socket."""
        conn = self.adb.connection(timeout if timeout is not None else 15.0)
        try:
            conn.request(f"host:transport:{self.serial}")
            conn.request(service)
        except AdbError:
            conn.close()
            raise
        conn.set_timeout(timeout)
        return conn

    def shell(self, command: str, timeout: float = 15.0) -> str:
        """Run a command and return its combined output as text."""
        with self.open(f"shell:{command}", timeout) as conn:
            raw = conn.read_until_eof()
        return raw.decode("utf-8", "replace").replace("\r\n", "\n")

    def exec_stream(self, command: str, timeout: float | None = 10.0) -> AdbConnection:
        """Open a raw binary stdout stream (equivalent to `adb exec-out`).

        No pty is allocated, so bytes arrive untouched. This is what carries the
        H.264 feed in the screenrecord engine.
        """
        return self.open(f"exec:{command}", timeout)

    # ------------------------------------------------------------- properties

    def getprop(self, name: str, default: str = "") -> str:
        with self._lock:
            if name in self._prop_cache:
                return self._prop_cache[name]
        try:
            value = self.shell(f"getprop {name}", timeout=8.0).strip()
        except AdbError:
            return default
        with self._lock:
            self._prop_cache[name] = value
        return value or default

    @property
    def model(self) -> str:
        return self.getprop("ro.product.model")

    @property
    def manufacturer(self) -> str:
        return self.getprop("ro.product.manufacturer")

    @property
    def sdk(self) -> int:
        try:
            return int(self.getprop("ro.build.version.sdk", "0"))
        except ValueError:
            return 0

    def screen_size(self) -> tuple[int, int] | None:
        """Physical display size as reported by wm."""
        try:
            out = self.shell("wm size", timeout=8.0)
        except AdbError:
            return None
        match = re.search(r"Physical size:\s*(\d+)x(\d+)", out)
        override = re.search(r"Override size:\s*(\d+)x(\d+)", out)
        chosen = override or match
        if not chosen:
            return None
        return int(chosen.group(1)), int(chosen.group(2))

    def wifi_ip(self) -> str | None:
        """Best effort wlan0 address, used to switch a USB device to Wi-Fi."""
        probes = [
            "ip -f inet addr show wlan0",
            "ip route",
            "ifconfig wlan0",
        ]
        for probe in probes:
            try:
                out = self.shell(probe, timeout=8.0)
            except AdbError:
                continue
            match = re.search(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b", out.replace("src ", ""))
            if match and not match.group(1).startswith("127."):
                return match.group(1)
        for prop in ("dhcp.wlan0.ipaddress", "wifi.interface.ipaddress"):
            value = self.getprop(prop)
            if value and value.count(".") == 3:
                return value
        return None

    # --------------------------------------------------------------- services

    def tcpip(self, port: int = 5555) -> str:
        """Restart adbd in TCP mode so the device can be used without a cable."""
        with self.open(f"tcpip:{port}", timeout=20.0) as conn:
            return conn.read_until_eof().decode("utf-8", "replace").strip()

    def reverse(self, remote: str, local: str) -> None:
        """Map a device-side socket back to a port on this machine."""
        conn = self.adb.connection(10.0)
        try:
            conn.request(f"host:transport:{self.serial}")
            conn.request(f"reverse:forward:{remote};{local}")
            # The forward services answer OKAY twice: once to accept the
            # request and once when the mapping is installed.
            try:
                conn.read_status()
            except AdbError:
                pass
        finally:
            conn.close()

    def reverse_remove(self, remote: str) -> None:
        conn = self.adb.connection(10.0)
        try:
            conn.request(f"host:transport:{self.serial}")
            conn.request(f"reverse:killforward:{remote}")
            try:
                conn.read_status()
            except AdbError:
                pass
        except AdbError:
            pass
        finally:
            conn.close()

    def push_bytes(self, data: bytes, remote: str, mode: int = MODE_EXEC) -> None:
        """Upload a blob with the sync protocol (used for the device server)."""
        conn = self.open("sync:", timeout=30.0)
        try:
            header = f"{remote},{mode}".encode("utf-8")
            conn.send_raw(b"SEND" + len(header).to_bytes(4, "little") + header)
            for offset in range(0, len(data), SYNC_CHUNK):
                chunk = data[offset : offset + SYNC_CHUNK]
                conn.send_raw(b"DATA" + len(chunk).to_bytes(4, "little") + chunk)
            conn.send_raw(b"DONE" + int(time.time()).to_bytes(4, "little"))
            status = conn.read_exact(4)
            length = int.from_bytes(conn.read_exact(4), "little")
            if status != b"OKAY":
                detail = conn.read_exact(length).decode("utf-8", "replace") if length else ""
                raise AdbError(f"push to {remote} failed: {detail}")
        finally:
            conn.close()

    # ---------------------------------------------------------------- control

    def input_tap(self, x: int, y: int) -> None:
        self.shell(f"input tap {int(x)} {int(y)}", timeout=5.0)

    def input_swipe(self, x1: int, y1: int, x2: int, y2: int, ms: int = 120) -> None:
        self.shell(
            f"input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(ms)}", timeout=8.0
        )

    def input_keyevent(self, keycode: int | str) -> None:
        self.shell(f"input keyevent {keycode}", timeout=5.0)
