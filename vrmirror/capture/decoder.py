"""H.264 decoding, tuned for latency rather than throughput.

PyAV ships its own ffmpeg build, so nothing has to be installed system wide.
Two settings matter for a live feed:

  * LOW_DELAY tells the decoder not to hold frames back looking for reordering
  * slice threading (instead of frame threading) avoids the extra frames of
    delay that frame threading buys its parallelism with
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

try:
    import av
    import av.logging

    av.logging.set_level(av.logging.FATAL)
    AV_IMPORT_ERROR: str | None = None
except Exception as exc:  # pragma: no cover - depends on the install
    av = None  # type: ignore[assignment]
    AV_IMPORT_ERROR = str(exc)


class DecoderUnavailable(RuntimeError):
    pass


class H264Decoder:
    def __init__(self) -> None:
        if av is None:
            raise DecoderUnavailable(
                "PyAV is not available, so video cannot be decoded "
                f"({AV_IMPORT_ERROR}). Install it with: pip install av"
            )
        self._context = None
        self.reset()

    # ------------------------------------------------------------------ setup

    def reset(self) -> None:
        """Throw away decoder state, for example after the feed restarted."""
        self._context = av.CodecContext.create("h264", "r")
        try:
            self._context.thread_type = "SLICE"
        except Exception:
            pass
        try:
            self._context.flags |= av.codec.context.Flags.LOW_DELAY
        except Exception:
            try:
                self._context.flags |= 1 << 19  # AV_CODEC_FLAG_LOW_DELAY
            except Exception:
                pass

    # ----------------------------------------------------------------- decode

    def decode(self, data: bytes):
        """Feed raw Annex-B bytes, yield decoded frames as they come out."""
        try:
            packets = self._context.parse(data)
        except Exception as exc:
            log.debug("parser error: %s", exc)
            return
        for packet in packets:
            try:
                frames = self._context.decode(packet)
            except Exception as exc:
                # A corrupt packet after a restart is normal; keep going.
                log.debug("decode error: %s", exc)
                continue
            for frame in frames:
                yield frame

    def flush(self):
        try:
            for frame in self._context.decode(None):
                yield frame
        except Exception:
            return


def frame_to_rgb(frame) -> tuple[bytes, int, int, int]:
    """Convert a decoded frame to packed RGB.

    Returns (data, width, height, stride). swscale does the colour conversion
    with SIMD, which is far cheaper than touching pixels from Python.
    """
    rgb = frame.reformat(format="rgb24")
    plane = rgb.planes[0]
    return bytes(plane), rgb.width, rgb.height, plane.line_size
