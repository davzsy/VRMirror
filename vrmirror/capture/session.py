"""The capture pipeline: device bytes in, QImages out.

Everything below runs on a worker thread. Frames reach the UI through Qt
signals, which are delivered as queued calls on the main thread, so no locking
is needed on the widget side.

Two deliberate choices:

  * The decoder is fed the raw socket chunks, not parsed NAL units. libavcodec's
    parser buffers internally, so handing it bytes the moment they arrive keeps
    latency at a minimum. The NAL scanner runs only for recording, where a
    frame of extra delay is irrelevant.
  * Frames are dropped rather than queued when the UI falls behind. A backlog of
    stale frames is worse than a missed one for a live view.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

from ..adb.client import Device
from .decoder import H264Decoder, frame_to_rgb
from .engines import EngineOptions, EngineUnavailable, build_engine
from .recorder import Recorder, remux_async

log = logging.getLogger(__name__)

MAX_FRAMES_IN_FLIGHT = 2


@dataclass
class CaptureOptions:
    engine: str = "auto"
    bitrate_bps: int = 12_000_000
    fps: int = 60
    max_size: int = 0
    time_limit_s: int = 1800

    def to_engine_options(self) -> EngineOptions:
        return EngineOptions(
            bitrate_bps=self.bitrate_bps,
            fps=self.fps,
            max_size=self.max_size,
            time_limit_s=self.time_limit_s,
        )


@dataclass
class Stats:
    fps: float = 0.0
    kbps: float = 0.0
    width: int = 0
    height: int = 0
    engine: str = ""
    dropped: int = 0
    recording: bool = False
    recorded_mb: float = 0.0


class CaptureSession(QObject):
    frameReady = Signal(QImage)
    statsUpdated = Signal(object)
    stateChanged = Signal(str)
    failed = Signal(str)
    recordingFinished = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: threading.Thread | None = None
        self._engine = None
        self._stop = threading.Event()
        self._inflight = 0
        self._inflight_lock = threading.Lock()
        self._recorder: Recorder | None = None
        self._recorder_lock = threading.Lock()
        self._stats = Stats()
        self.device: Device | None = None

    # ------------------------------------------------------------------ state

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def stats(self) -> Stats:
        return self._stats

    # -------------------------------------------------------------- lifecycle

    def start(self, device: Device, options: CaptureOptions) -> None:
        if self.is_running:
            self.stop()
        self.device = device
        self._stop.clear()
        self._inflight = 0
        self._stats = Stats()
        self._thread = threading.Thread(
            target=self._run, args=(device, options), name="vrmirror-capture", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 4.0) -> None:
        self._stop.set()
        engine = self._engine
        if engine is not None:
            try:
                engine.request_stop()
            except Exception:
                pass
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout)
        self._thread = None
        self._engine = None
        self.stop_recording()

    # -------------------------------------------------------------- recording

    def start_recording(self, destination: Path, fps: int = 60) -> None:
        with self._recorder_lock:
            if self._recorder is not None:
                return
            self._recorder = Recorder(destination, fps=fps)
        self._stats.recording = True

    def stop_recording(self) -> None:
        with self._recorder_lock:
            recorder = self._recorder
            self._recorder = None
        if recorder is None:
            return
        self._stats.recording = False
        remux_async(recorder, on_done=lambda path: self.recordingFinished.emit(str(path)))

    # ------------------------------------------------------------ frame budget

    def frame_rendered(self) -> None:
        with self._inflight_lock:
            if self._inflight > 0:
                self._inflight -= 1

    def _may_emit(self) -> bool:
        with self._inflight_lock:
            if self._inflight >= MAX_FRAMES_IN_FLIGHT:
                return False
            self._inflight += 1
            return True

    # ------------------------------------------------------------------- work

    def _run(self, device: Device, options: CaptureOptions) -> None:
        try:
            decoder = H264Decoder()
        except Exception as exc:
            self.failed.emit(str(exc))
            self.stateChanged.emit("stopped")
            return

        engine = build_engine(device, options.to_engine_options(), options.engine)
        self._engine = engine
        self._stats.engine = engine.name
        self.stateChanged.emit("starting")

        frames = 0
        received = 0
        dropped = 0
        window_start = time.monotonic()
        first_frame = True

        try:
            for chunk in engine.stream():
                if self._stop.is_set():
                    break

                if chunk is None:
                    # The engine restarted: new parameter sets are on the way.
                    decoder.reset()
                    with self._recorder_lock:
                        if self._recorder is not None:
                            self._recorder.restart_boundary()
                    continue

                received += len(chunk)

                with self._recorder_lock:
                    if self._recorder is not None:
                        self._recorder.feed(chunk)

                for frame in decoder.decode(chunk):
                    frames += 1
                    if first_frame:
                        first_frame = False
                        self.stateChanged.emit("streaming")
                    if not self._may_emit():
                        dropped += 1
                        continue
                    try:
                        data, width, height, stride = frame_to_rgb(frame)
                    except Exception as exc:
                        log.debug("colour conversion failed: %s", exc)
                        self.frame_rendered()
                        continue
                    image = QImage(data, width, height, stride, QImage.Format_RGB888).copy()
                    self._stats.width = width
                    self._stats.height = height
                    self.frameReady.emit(image)

                now = time.monotonic()
                elapsed = now - window_start
                if elapsed >= 1.0:
                    self._stats.fps = frames / elapsed
                    self._stats.kbps = received * 8 / 1000 / elapsed
                    self._stats.dropped = dropped
                    with self._recorder_lock:
                        if self._recorder is not None:
                            self._stats.recorded_mb = self._recorder.bytes_written / (1 << 20)
                    self.statsUpdated.emit(self._stats)
                    frames = 0
                    received = 0
                    window_start = now

        except EngineUnavailable as exc:
            if not self._stop.is_set():
                self.failed.emit(str(exc))
        except Exception as exc:  # pragma: no cover - defensive
            if not self._stop.is_set():
                log.exception("capture thread failed")
                self.failed.emit(f"capture stopped: {exc}")
        finally:
            self.stateChanged.emit("stopped")
