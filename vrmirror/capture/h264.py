"""Just enough Annex-B parsing to record a clean file.

The decoder does not need this: libavcodec's parser happily accepts arbitrary
byte chunks. But a recording has to *start* on a keyframe preceded by its
parameter sets, otherwise the first seconds are garbage. screenrecord uses a
10 second I-frame interval, so waiting naively for the next keyframe could cost
10 seconds of footage; instead we cache the parameter sets we have already seen
and splice them in front of the next IDR.
"""

from __future__ import annotations

NAL_SLICE_IDR = 5
NAL_SEI = 6
NAL_SPS = 7
NAL_PPS = 8
NAL_AUD = 9

_START_CODE = b"\x00\x00\x01"


def nal_type(nal: bytes) -> int:
    """NAL unit type of a unit that still carries its start code."""
    index = 0
    if nal.startswith(b"\x00\x00\x00\x01"):
        index = 4
    elif nal.startswith(_START_CODE):
        index = 3
    if index >= len(nal):
        return -1
    return nal[index] & 0x1F


class NalScanner:
    """Split a byte stream into complete Annex-B NAL units."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def reset(self) -> None:
        self._buffer.clear()

    def feed(self, data: bytes) -> list[bytes]:
        """Return every NAL unit that is now complete.

        The trailing (possibly partial) unit is held back until the next start
        code arrives, which is why this must never be used to feed the decoder.
        """
        self._buffer += data
        units: list[bytes] = []

        starts = []
        position = self._buffer.find(_START_CODE)
        while position != -1:
            begin = position - 1 if position > 0 and self._buffer[position - 1] == 0 else position
            starts.append(begin)
            position = self._buffer.find(_START_CODE, position + 3)

        if len(starts) < 2:
            return units

        for index in range(len(starts) - 1):
            units.append(bytes(self._buffer[starts[index] : starts[index + 1]]))
        del self._buffer[: starts[-1]]
        return units


class RecordGate:
    """Buffers parameter sets, then opens on the first keyframe."""

    def __init__(self) -> None:
        self.sps: bytes | None = None
        self.pps: bytes | None = None
        self._open = False

    @property
    def is_open(self) -> bool:
        return self._open

    def reset(self) -> None:
        self._open = False

    def observe(self, nal: bytes) -> None:
        kind = nal_type(nal)
        if kind == NAL_SPS:
            self.sps = nal
        elif kind == NAL_PPS:
            self.pps = nal

    def take(self, nal: bytes) -> bytes | None:
        """Return the bytes to write for this NAL, or None to skip it."""
        self.observe(nal)
        if self._open:
            return nal

        kind = nal_type(nal)
        if kind in (NAL_SPS, NAL_PPS):
            # Held back; they are emitted together with the first keyframe.
            return None
        if kind == NAL_SLICE_IDR and self.sps and self.pps:
            self._open = True
            return self.sps + self.pps + nal
        return None
