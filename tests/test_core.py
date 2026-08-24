"""Tests for the parts that need no Qt and no ffmpeg.

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrmirror.adb.client import _parse_devices  # noqa: E402
from vrmirror.capture.h264 import (  # noqa: E402
    NAL_PPS,
    NAL_SLICE_IDR,
    NAL_SPS,
    NalScanner,
    RecordGate,
    nal_type,
)
from vrmirror.presets import GENERIC, preset_for  # noqa: E402


def nal(kind: int, payload: bytes = b"\x00" * 4, long_start: bool = True) -> bytes:
    start = b"\x00\x00\x00\x01" if long_start else b"\x00\x00\x01"
    return start + bytes([kind & 0x1F]) + payload


class ParseDevicesTest(unittest.TestCase):
    def test_devices_l_output(self) -> None:
        payload = (
            "1WMHH8123456\tdevice product:hollywood model:Quest_3 "
            "device:hollywood transport_id:2\n"
            "192.168.1.42:5555\tdevice product:hollywood model:Quest_3 transport_id:3\n"
            "abc123\tunauthorized transport_id:4\n"
        )
        devices = _parse_devices(payload)
        self.assertEqual(len(devices), 3)

        usb, wireless, unauthorized = devices
        self.assertEqual(usb.serial, "1WMHH8123456")
        self.assertEqual(usb.model, "Quest_3")
        self.assertTrue(usb.is_usable)
        self.assertFalse(usb.is_wireless)
        self.assertIn("Quest 3", usb.label)

        self.assertTrue(wireless.is_wireless)
        self.assertIn("Wi-Fi", wireless.label)

        self.assertFalse(unauthorized.is_usable)
        self.assertEqual(unauthorized.state, "unauthorized")

    def test_ignores_header_and_blanks(self) -> None:
        self.assertEqual(_parse_devices("List of devices attached\n\n"), [])


class NalTypeTest(unittest.TestCase):
    def test_long_and_short_start_codes(self) -> None:
        self.assertEqual(nal_type(nal(NAL_SPS)), NAL_SPS)
        self.assertEqual(nal_type(nal(NAL_PPS, long_start=False)), NAL_PPS)

    def test_truncated_unit(self) -> None:
        self.assertEqual(nal_type(b"\x00\x00\x01"), -1)


class NalScannerTest(unittest.TestCase):
    def test_splits_on_start_codes(self) -> None:
        scanner = NalScanner()
        stream = nal(NAL_SPS) + nal(NAL_PPS) + nal(NAL_SLICE_IDR)
        units = scanner.feed(stream)
        # The final unit is held back until the next start code arrives.
        self.assertEqual([nal_type(u) for u in units], [NAL_SPS, NAL_PPS])
        units = scanner.feed(nal(1))
        self.assertEqual([nal_type(u) for u in units], [NAL_SLICE_IDR])

    def test_survives_arbitrary_chunk_boundaries(self) -> None:
        stream = nal(NAL_SPS) + nal(NAL_PPS) + nal(NAL_SLICE_IDR) + nal(1) + nal(1)
        for split in range(1, len(stream)):
            scanner = NalScanner()
            units = scanner.feed(stream[:split]) + scanner.feed(stream[split:])
            self.assertEqual(
                [nal_type(u) for u in units],
                [NAL_SPS, NAL_PPS, NAL_SLICE_IDR, 1],
                f"failed with a split at byte {split}",
            )

    def test_reassembles_exact_bytes(self) -> None:
        scanner = NalScanner()
        first, second = nal(NAL_SPS, b"\x11\x22"), nal(NAL_PPS, b"\x33")
        units = scanner.feed(first + second + nal(1))
        self.assertEqual(units[0], first)
        self.assertEqual(units[1], second)


class RecordGateTest(unittest.TestCase):
    def test_waits_for_parameter_sets_and_keyframe(self) -> None:
        gate = RecordGate()
        self.assertIsNone(gate.take(nal(1)))  # mid-stream P slice, dropped
        sps, pps = nal(NAL_SPS), nal(NAL_PPS)
        self.assertIsNone(gate.take(sps))
        self.assertIsNone(gate.take(pps))
        self.assertFalse(gate.is_open)

        idr = nal(NAL_SLICE_IDR)
        opened = gate.take(idr)
        self.assertEqual(opened, sps + pps + idr)
        self.assertTrue(gate.is_open)

        # Once open everything is written through, parameter sets included.
        following = nal(1)
        self.assertEqual(gate.take(following), following)

    def test_never_opens_without_parameter_sets(self) -> None:
        gate = RecordGate()
        self.assertIsNone(gate.take(nal(NAL_SLICE_IDR)))
        self.assertFalse(gate.is_open)


class PresetTest(unittest.TestCase):
    def test_headsets_get_vr_presets(self) -> None:
        self.assertEqual(preset_for("Quest 3", "Oculus").name, "Meta Quest 3")
        self.assertEqual(preset_for("Quest 2", "Oculus").name, "Meta Quest 2")
        self.assertIsNot(preset_for("Pico 4", "Pico"), GENERIC)

    def test_phones_get_generic(self) -> None:
        self.assertIs(preset_for("Pixel 8", "Google"), GENERIC)

    def test_frame_rates_are_sane(self) -> None:
        for model in ("Quest 3", "Quest 2", "Pixel 8"):
            preset = preset_for(model)
            self.assertGreaterEqual(preset.fps, 30)
            self.assertLessEqual(preset.fps, 120)
            self.assertGreater(preset.bitrate_mbps, 0)


if __name__ == "__main__":
    unittest.main()
