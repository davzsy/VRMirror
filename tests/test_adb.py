"""Client tests against a scripted fake adb server."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fake_adb import FakeAdbServer  # noqa: E402

from vrmirror.adb.client import Adb  # noqa: E402
from vrmirror.adb.protocol import AdbError  # noqa: E402


class AdbClientTest(unittest.TestCase):
    def setUp(self) -> None:
        self.server = FakeAdbServer()
        self.addCleanup(self.server.close)
        self.adb = Adb(port=self.server.port)

    def test_version_and_devices(self) -> None:
        self.assertEqual(self.adb.server_version(), 0x29)
        devices = self.adb.devices()
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].model, "Quest_3")
        self.assertIn("host:devices-l", self.server.requests)

    def test_shell_and_properties(self) -> None:
        device = self.adb.device("1WMHH8123456")
        self.assertEqual(device.model, "Quest 3")
        self.assertEqual(device.manufacturer, "Oculus")
        self.assertEqual(device.sdk, 32)
        self.assertEqual(device.screen_size(), (1920, 1080))
        self.assertEqual(device.wifi_ip(), "192.168.1.42")
        self.assertIn("host:transport:1WMHH8123456", self.server.requests)

    def test_properties_are_cached(self) -> None:
        device = self.adb.device("1WMHH8123456")
        device.model
        device.model
        shells = [r for r in self.server.requests if r == "shell:getprop ro.product.model"]
        self.assertEqual(len(shells), 1)

    def test_connect(self) -> None:
        self.assertIn("connected", self.adb.connect("192.168.1.42").lower())
        self.assertIn("host:connect:192.168.1.42:5555", self.server.requests)

    def test_tcpip(self) -> None:
        device = self.adb.device("1WMHH8123456")
        self.assertIn("TCP mode", device.tcpip(5555))

    def test_reverse(self) -> None:
        device = self.adb.device("1WMHH8123456")
        device.reverse("localabstract:vrmirror", "tcp:41234")
        self.assertIn(
            "reverse:forward:localabstract:vrmirror;tcp:41234", self.server.reverses
        )

    def test_push_roundtrip(self) -> None:
        device = self.adb.device("1WMHH8123456")
        payload = bytes(range(256)) * 700  # larger than one 64 KB sync chunk
        device.push_bytes(payload, "/data/local/tmp/vrmirror-server.dex")
        self.assertEqual(self.server.pushed["/data/local/tmp/vrmirror-server.dex"], payload)

    def test_unknown_service_raises(self) -> None:
        with self.assertRaises(AdbError):
            self.adb._query("host:nonsense")

    def test_missing_server_is_reported(self) -> None:
        with self.assertRaises(AdbError):
            Adb(port=1).server_version()


class ScreenrecordEngineTest(unittest.TestCase):
    def test_command_and_stream(self) -> None:
        from vrmirror.capture.engines import EngineOptions, ScreenrecordEngine

        payload = b"\x00\x00\x00\x01" + b"video" * 5000
        server = FakeAdbServer(video=payload)
        self.addCleanup(server.close)

        adb = Adb(port=server.port)
        device = adb.device("1WMHH8123456")
        engine = ScreenrecordEngine(
            device, EngineOptions(bitrate_bps=8_000_000, max_size=1280, time_limit_s=600)
        )

        received = bytearray()
        for chunk in engine.stream():
            if chunk is None:  # restart boundary after the fake stream ends
                engine.request_stop()
                break
            received += chunk

        self.assertEqual(bytes(received), payload)

        command = server.exec_commands[0]
        self.assertIn("screenrecord", command)
        self.assertIn("--output-format=h264", command)
        self.assertIn("--bit-rate=8000000", command)
        # 1920x1080 capped to 1280 on the long side, rounded to even numbers.
        self.assertIn("--size 1280x720", command)
        self.assertIn("--time-limit 600", command)

    def test_falls_back_when_the_device_rejects_the_time_limit(self) -> None:
        from vrmirror.capture.engines import EngineOptions, ScreenrecordEngine

        # An empty video stream models screenrecord exiting without output,
        # which is what a build that caps --time-limit at 180 does.
        server = FakeAdbServer(video=b"")
        self.addCleanup(server.close)

        adb = Adb(port=server.port)
        engine = ScreenrecordEngine(
            adb.device("1WMHH8123456"), EngineOptions(time_limit_s=1800)
        )

        with self.assertRaises(Exception):
            for _ in engine.stream():
                pass

        self.assertGreaterEqual(len(server.exec_commands), 2)
        self.assertIn("--time-limit 1800", server.exec_commands[0])
        self.assertIn("--time-limit 180", server.exec_commands[1])


if __name__ == "__main__":
    unittest.main()
