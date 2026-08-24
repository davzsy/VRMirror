"""A scripted stand-in for the adb server.

Enough of the real protocol to exercise the client end to end without a device:
host services, transport switching, shell, exec streaming, sync push, reverse
and the device tracking feed. Every request it receives is recorded, so tests
can assert on what the client actually sent.
"""

from __future__ import annotations

import socket
import threading

DEFAULT_DEVICES = (
    "1WMHH8123456\tdevice product:hollywood model:Quest_3 device:hollywood transport_id:1\n"
)

SHELL_RESPONSES = {
    "getprop ro.product.model": "Quest 3\n",
    "getprop ro.product.manufacturer": "Oculus\n",
    "getprop ro.build.version.sdk": "32\n",
    "wm size": "Physical size: 1920x1080\n",
    "ip -f inet addr show wlan0": "    inet 192.168.1.42/24 brd 192.168.1.255 scope global wlan0\n",
}


class FakeAdbServer:
    def __init__(self, video: bytes = b"", devices: str = DEFAULT_DEVICES) -> None:
        self.video = video
        self.devices = devices
        self.requests: list[str] = []
        self.pushed: dict[str, bytes] = {}
        self.reverses: list[str] = []
        self.exec_commands: list[str] = []
        self.stream_chunk = 4096
        self.stream_delay = 0.0

        self._sock = socket.socket()
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(8)
        self.port = self._sock.getsockname()[1]

        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    # ------------------------------------------------------------- lifecycle

    def close(self) -> None:
        self._stop.set()
        try:
            self._sock.close()
        except OSError:
            pass

    def __enter__(self) -> "FakeAdbServer":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ---------------------------------------------------------------- server

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                client, _ = self._sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(client,), daemon=True).start()

    def _read_request(self, client: socket.socket) -> str | None:
        header = self._read_exact(client, 4)
        if header is None:
            return None
        try:
            length = int(header, 16)
        except ValueError:
            return None
        payload = self._read_exact(client, length)
        if payload is None:
            return None
        request = payload.decode()
        self.requests.append(request)
        return request

    @staticmethod
    def _read_exact(client: socket.socket, count: int) -> bytes | None:
        chunks = []
        remaining = count
        while remaining > 0:
            try:
                chunk = client.recv(remaining)
            except OSError:
                return None
            if not chunk:
                return None
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    @staticmethod
    def _okay(client: socket.socket) -> None:
        client.sendall(b"OKAY")

    @staticmethod
    def _payload(client: socket.socket, text: str) -> None:
        data = text.encode()
        client.sendall(b"%04x" % len(data) + data)

    def _handle(self, client: socket.socket) -> None:
        try:
            request = self._read_request(client)
            if request is None:
                return

            if request == "host:version":
                self._okay(client)
                self._payload(client, "0029")
                return

            if request in ("host:devices", "host:devices-l"):
                self._okay(client)
                self._payload(client, self.devices)
                return

            if request in ("host:track-devices", "host:track-devices-l"):
                self._okay(client)
                self._payload(client, self.devices)
                while not self._stop.is_set():
                    if self._stop.wait(0.05):
                        break
                return

            if request.startswith("host:connect:"):
                self._okay(client)
                self._payload(client, f"connected to {request.split(':', 2)[2]}")
                return

            if request.startswith("host:transport:"):
                self._okay(client)
                self._handle_transport(client)
                return

            client.sendall(b"FAIL")
            self._payload(client, f"unknown service {request}")
        except OSError:
            pass
        finally:
            try:
                client.close()
            except OSError:
                pass

    def _handle_transport(self, client: socket.socket) -> None:
        request = self._read_request(client)
        if request is None:
            return

        if request.startswith("shell:"):
            command = request[len("shell:") :]
            self._okay(client)
            client.sendall(SHELL_RESPONSES.get(command, "").encode())
            return

        if request.startswith("exec:"):
            command = request[len("exec:") :]
            self.exec_commands.append(command)
            self._okay(client)
            self._stream_video(client)
            return

        if request.startswith("reverse:"):
            self.reverses.append(request)
            self._okay(client)
            self._okay(client)
            return

        if request.startswith("tcpip:"):
            self._okay(client)
            client.sendall(b"restarting in TCP mode port: 5555\n")
            return

        if request == "sync:":
            self._okay(client)
            self._handle_sync(client)
            return

        client.sendall(b"FAIL")
        self._payload(client, f"unknown service {request}")

    def _stream_video(self, client: socket.socket) -> None:
        import time

        for offset in range(0, len(self.video), self.stream_chunk):
            if self._stop.is_set():
                return
            try:
                client.sendall(self.video[offset : offset + self.stream_chunk])
            except OSError:
                return
            if self.stream_delay:
                time.sleep(self.stream_delay)
        # End of stream, exactly as screenrecord's stdout closing looks.

    def _handle_sync(self, client: socket.socket) -> None:
        header = self._read_exact(client, 8)
        if header is None or header[:4] != b"SEND":
            return
        path_length = int.from_bytes(header[4:], "little")
        path_and_mode = self._read_exact(client, path_length).decode()
        path = path_and_mode.rsplit(",", 1)[0]

        body = bytearray()
        while True:
            chunk_header = self._read_exact(client, 8)
            if chunk_header is None:
                return
            kind = chunk_header[:4]
            size = int.from_bytes(chunk_header[4:], "little")
            if kind == b"DATA":
                data = self._read_exact(client, size)
                if data is None:
                    return
                body += data
            elif kind == b"DONE":
                self.pushed[path] = bytes(body)
                client.sendall(b"OKAY" + (0).to_bytes(4, "little"))
                return
            else:
                return
