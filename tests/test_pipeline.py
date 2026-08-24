"""Whole-pipeline test: fake device bytes in, rendered frames out.

Skipped when Qt or ffmpeg are missing, so the rest of the suite still runs on a
bare Python install.
"""

from __future__ import annotations

import io
import os
import sys
import unittest
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import av
    import numpy as np
    from PySide6.QtWidgets import QApplication

    DEPS_ERROR = None
except Exception as exc:  # pragma: no cover - depends on the install
    DEPS_ERROR = str(exc)

from fake_adb import FakeAdbServer  # noqa: E402

from vrmirror.adb.client import Adb  # noqa: E402

WIDTH, HEIGHT, FRAMES = 320, 240, 20


def encode_test_stream() -> bytes:
    """A short Annex-B stream, standing in for the device's encoder output."""
    buffer = io.BytesIO()
    container = av.open(buffer, "w", format="h264")
    stream = container.add_stream("libx264", rate=30)
    stream.width, stream.height = WIDTH, HEIGHT
    stream.pix_fmt = "yuv420p"
    stream.options = {"preset": "ultrafast", "tune": "zerolatency", "g": "10"}
    stream.time_base = Fraction(1, 30)

    for index in range(FRAMES):
        array = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        array[40:HEIGHT - 40, 60:WIDTH - 60] = (20, 200, 120)
        frame = av.VideoFrame.from_ndarray(array, format="rgb24")
        frame.pts = index
        frame.time_base = Fraction(1, 30)
        for packet in stream.encode(frame):
            container.mux(packet)
    for packet in stream.encode(None):
        container.mux(packet)
    container.close()
    return buffer.getvalue()


@unittest.skipIf(DEPS_ERROR, f"needs PySide6 and av ({DEPS_ERROR})")
class PipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        cls.stream = encode_test_stream()

    def test_frames_reach_the_view(self) -> None:
        from vrmirror.capture.session import CaptureOptions, CaptureSession

        server = FakeAdbServer(video=self.stream)
        server.stream_chunk = 512  # force many partial reads
        self.addCleanup(server.close)

        adb = Adb(port=server.port)
        session = CaptureSession()
        self.addCleanup(session.stop)

        images = []
        states = []
        errors = []
        session.frameReady.connect(lambda image: (images.append(image), session.frame_rendered()))
        session.stateChanged.connect(states.append)
        session.failed.connect(errors.append)

        session.start(
            adb.device("1WMHH8123456"),
            CaptureOptions(engine="screenrecord", bitrate_bps=8_000_000, max_size=0),
        )

        deadline = 20.0
        step = 0.02
        waited = 0.0
        while waited < deadline and len(images) < FRAMES - 4:
            self.app.processEvents()
            import time

            time.sleep(step)
            waited += step
        session.stop()
        self.app.processEvents()

        self.assertEqual(errors, [], f"session reported: {errors}")
        self.assertGreaterEqual(len(images), FRAMES - 4, "not enough frames arrived")
        self.assertIn("streaming", states)

        first = images[0]
        self.assertEqual((first.width(), first.height()), (WIDTH, HEIGHT))
        colour = first.pixelColor(WIDTH // 2, HEIGHT // 2)
        self.assertGreater(colour.green(), 150)
        self.assertLess(colour.red(), 80)
        corner = first.pixelColor(3, 3)
        self.assertLess(corner.green(), 40)

    def test_recording_while_streaming_produces_a_playable_file(self) -> None:
        import tempfile

        from vrmirror.capture.session import CaptureOptions, CaptureSession

        server = FakeAdbServer(video=self.stream)
        self.addCleanup(server.close)

        adb = Adb(port=server.port)
        session = CaptureSession()
        self.addCleanup(session.stop)

        directory = Path(tempfile.mkdtemp())
        destination = directory / "clip.mp4"
        finished = []
        session.recordingFinished.connect(finished.append)
        session.frameReady.connect(lambda _image: session.frame_rendered())

        session.start(
            adb.device("1WMHH8123456"),
            CaptureOptions(engine="screenrecord", fps=30),
        )
        session.start_recording(destination, fps=30)

        import time

        waited = 0.0
        while waited < 20.0 and not (session.stats.recorded_mb or session.stats.fps):
            self.app.processEvents()
            time.sleep(0.02)
            waited += 0.02

        session.stop_recording()
        waited = 0.0
        while waited < 20.0 and not finished:
            self.app.processEvents()
            time.sleep(0.02)
            waited += 0.02
        session.stop()

        self.assertTrue(finished, "the recording never finished")
        self.assertTrue(destination.exists(), f"expected {destination}, got {finished}")

        container = av.open(str(destination))
        video = container.streams.video[0]
        decoded = sum(1 for _ in container.decode(video))
        container.close()
        self.assertEqual(video.codec_context.name, "h264")
        self.assertGreater(decoded, 0)


if __name__ == "__main__":
    unittest.main()
