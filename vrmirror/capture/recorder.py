"""Recording without re-encoding.

The device already handed us H.264, so recording is just writing those bytes to
disk and then wrapping them in an MP4 container. No second encode means no
quality loss and almost no CPU cost.
"""

from __future__ import annotations

import logging
import threading
from fractions import Fraction
from pathlib import Path

from .h264 import NalScanner, RecordGate

log = logging.getLogger(__name__)


class Recorder:
    """Gated writer for the raw elementary stream, plus an MP4 remux on stop."""

    def __init__(self, destination: Path, fps: int = 60) -> None:
        self.destination = Path(destination)
        self.fps = max(1, int(fps))
        self.raw_path = self.destination.with_suffix(".h264")
        self._file = open(self.raw_path, "wb")
        self._scanner = NalScanner()
        self._gate = RecordGate()
        self._bytes = 0
        self._closed = False

    @property
    def started(self) -> bool:
        return self._gate.is_open

    @property
    def bytes_written(self) -> int:
        return self._bytes

    def feed(self, data: bytes) -> None:
        if self._closed:
            return
        for nal in self._scanner.feed(data):
            payload = self._gate.take(nal)
            if payload:
                self._file.write(payload)
                self._bytes += len(payload)

    def restart_boundary(self) -> None:
        """The capture engine restarted; keep writing into the same file."""
        self._scanner.reset()

    def close(self, remux: bool = True) -> Path:
        if self._closed:
            return self.destination
        self._closed = True
        try:
            self._file.close()
        except OSError:
            pass

        if not remux or self._bytes == 0:
            return self.raw_path

        try:
            self._remux()
        except Exception as exc:
            log.warning("MP4 remux failed, keeping the raw stream: %s", exc)
            return self.raw_path

        try:
            self.raw_path.unlink()
        except OSError:
            pass
        return self.destination

    def _remux(self) -> None:
        """Wrap the elementary stream in MP4 without touching the video data.

        An Annex-B stream carries no timestamps at all, so the demuxer hands
        back packets with pts and dts unset. We stamp them ourselves at the
        capture frame rate: the frames are already in decode order and the
        device encoded at a fixed rate, so a linear stamp is correct.
        """
        import av

        container_in = av.open(
            str(self.raw_path), format="h264", options={"framerate": str(self.fps)}
        )
        try:
            stream_in = container_in.streams.video[0]
            container_out = av.open(str(self.destination), "w")
            try:
                # PyAV 14 replaced add_stream(template=...) with a dedicated
                # method. Both mean "copy this stream, do not re-encode".
                if hasattr(container_out, "add_stream_from_template"):
                    stream_out = container_out.add_stream_from_template(stream_in)
                else:
                    stream_out = container_out.add_stream(template=stream_in)

                time_base = Fraction(1, self.fps)
                index = 0
                for packet in container_in.demux(stream_in):
                    if packet.size == 0:
                        continue  # the flush packet at end of stream
                    packet.stream = stream_out
                    packet.time_base = time_base
                    packet.pts = index
                    packet.dts = index
                    packet.duration = 1
                    container_out.mux(packet)
                    index += 1
                if index == 0:
                    raise RuntimeError("no packets were written")
            finally:
                container_out.close()
        finally:
            container_in.close()


def remux_async(recorder: Recorder, on_done=None) -> None:
    """Close and remux off the capture thread so the UI never stalls."""

    def worker() -> None:
        path = recorder.close(remux=True)
        if on_done is not None:
            on_done(path)

    threading.Thread(target=worker, name="vrmirror-remux", daemon=True).start()
