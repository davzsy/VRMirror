"""Main window: wiring between the device list, the capture session and the view."""

from __future__ import annotations

import logging
import time
from datetime import datetime

from PySide6.QtCore import QByteArray, QRect, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QSplitter,
    QToolBar,
    QWidget,
)

from .. import APP_NAME, __version__
from ..adb.client import Adb, Device, DeviceInfo
from ..capture.session import CaptureOptions, CaptureSession, Stats
from ..config import Config
from ..presets import preset_for
from .device_panel import DevicePanel
from .settings_dialog import SettingsDialog
from .video_view import VideoView

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, adb: Adb, config: Config) -> None:
        super().__init__()
        self.adb = adb
        self.config = config
        self.session = CaptureSession(self)
        self.device: Device | None = None
        self.device_info: DeviceInfo | None = None
        self._device_model = ""
        self._fullscreen = False
        self._saved_sizes: list[int] = []
        self._last_message_at = 0.0

        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(1180, 760)

        self._build_ui()
        self._build_toolbar()
        self._build_statusbar()
        self._connect_signals()
        self._restore_geometry()

        self.device_panel.start()
        self._update_actions()

    # --------------------------------------------------------------- building

    def _build_ui(self) -> None:
        self.splitter = QSplitter(Qt.Horizontal)

        self.device_panel = DevicePanel(self.adb)
        self.device_panel.setMinimumWidth(240)
        self.device_panel.setMaximumWidth(380)
        self.splitter.addWidget(self.device_panel)

        self.video = VideoView()
        self.splitter.addWidget(self.video)

        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([280, 900])
        self.setCentralWidget(self.splitter)

        self.video.set_smooth(self.config.view.smooth)
        self.video.set_fit_mode(self.config.view.fit_mode)

    def _build_toolbar(self) -> None:
        bar = QToolBar("Main")
        bar.setMovable(False)
        bar.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.addToolBar(bar)
        self.toolbar = bar

        self.act_start = QAction("Start mirroring", self)
        self.act_start.setShortcut(QKeySequence("Ctrl+R"))
        self.act_start.triggered.connect(self.toggle_capture)
        bar.addAction(self.act_start)

        bar.addSeparator()

        self.act_record = QAction("Record", self)
        self.act_record.setCheckable(True)
        self.act_record.setShortcut(QKeySequence("Ctrl+Shift+R"))
        self.act_record.triggered.connect(self.toggle_recording)
        bar.addAction(self.act_record)

        self.act_shot = QAction("Screenshot", self)
        self.act_shot.setShortcut(QKeySequence("Ctrl+S"))
        self.act_shot.triggered.connect(self.save_screenshot)
        bar.addAction(self.act_shot)

        bar.addSeparator()

        self.act_autocrop = QAction("Auto-crop", self)
        self.act_autocrop.setToolTip("Trim the black borders around the rendered area.")
        self.act_autocrop.triggered.connect(self.auto_crop)
        bar.addAction(self.act_autocrop)

        self.act_eye = QAction("Left eye", self)
        self.act_eye.setToolTip("Halve the view horizontally for a stereo source.")
        self.act_eye.triggered.connect(self.crop_left_eye)
        bar.addAction(self.act_eye)

        self.act_reset_crop = QAction("Reset crop", self)
        self.act_reset_crop.triggered.connect(self.reset_crop)
        bar.addAction(self.act_reset_crop)

        bar.addSeparator()

        self.fit_group = QActionGroup(self)
        for label, mode in (("Fit", "fit"), ("Fill", "fill"), ("1:1", "actual")):
            action = QAction(label, self)
            action.setCheckable(True)
            action.setData(mode)
            action.setChecked(self.config.view.fit_mode == mode)
            action.triggered.connect(lambda _checked, m=mode: self.set_fit_mode(m))
            self.fit_group.addAction(action)
            bar.addAction(action)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        spacer.setStyleSheet("background: transparent;")
        bar.addWidget(spacer)

        self.act_on_top = QAction("On top", self)
        self.act_on_top.setCheckable(True)
        self.act_on_top.setChecked(self.config.view.always_on_top)
        self.act_on_top.triggered.connect(self.set_always_on_top)
        bar.addAction(self.act_on_top)

        self.act_fullscreen = QAction("Fullscreen", self)
        self.act_fullscreen.setShortcut(QKeySequence(Qt.Key_F11))
        self.act_fullscreen.triggered.connect(self.toggle_fullscreen)
        bar.addAction(self.act_fullscreen)

        self.act_settings = QAction("Settings", self)
        self.act_settings.triggered.connect(self.open_settings)
        bar.addAction(self.act_settings)

        escape = QAction(self)
        escape.setShortcut(QKeySequence(Qt.Key_Escape))
        escape.triggered.connect(self._leave_fullscreen)
        self.addAction(escape)

        if self.config.view.always_on_top:
            self.set_always_on_top(True)

    def _build_statusbar(self) -> None:
        self.status_device = QLabel("No device")
        self.status_device.setObjectName("status")
        self.status_stream = QLabel("Idle")
        self.status_stream.setObjectName("status")
        self.status_rate = QLabel("")
        self.status_rate.setObjectName("status")

        bar = self.statusBar()
        bar.addWidget(self.status_device, 2)
        bar.addWidget(self.status_stream, 2)
        bar.addPermanentWidget(self.status_rate)

    def _connect_signals(self) -> None:
        self.device_panel.deviceSelected.connect(self.on_device_selected)
        self.device_panel.message.connect(self.show_message)

        self.session.frameReady.connect(self.on_frame)
        self.session.statsUpdated.connect(self.on_stats)
        self.session.stateChanged.connect(self.on_state)
        self.session.failed.connect(self.on_failure)
        self.session.recordingFinished.connect(
            lambda path: self.show_message(f"Saved recording to {path}")
        )

        self.video.tapped.connect(self.on_tap)
        self.video.swiped.connect(self.on_swipe)
        self.video.doubleClicked.connect(self.toggle_fullscreen)

    # ---------------------------------------------------------------- devices

    def on_device_selected(self, info: DeviceInfo | None) -> None:
        self.device_info = info
        if info is None or not info.is_usable:
            self.device = None
            self._device_model = ""
            self.status_device.setText("No device" if info is None else f"Device {info.state}")
            self._update_actions()
            return

        self.device = self.adb.device(info.serial)
        self.config.last_serial = info.serial

        # Reading properties touches the device, so keep it off the click path.
        QTimer.singleShot(0, self._describe_device)
        self._update_actions()

    def _describe_device(self) -> None:
        device = self.device
        if device is None:
            return
        try:
            model = device.model or (self.device_info.model if self.device_info else "")
            manufacturer = device.manufacturer
            size = device.screen_size()
        except Exception as exc:
            self.status_device.setText(f"Device error: {exc}")
            return

        self._device_model = model
        preset = preset_for(model, manufacturer)
        resolution = f"{size[0]}x{size[1]}" if size else "unknown size"
        self.status_device.setText(f"{model or device.serial}  ·  {resolution}  ·  {preset.name}")

        saved = self.config.crop_for(model)
        self.video.set_crop(saved)

        if preset.note:
            self.show_message(preset.note, sticky=False)

    # ---------------------------------------------------------------- capture

    def toggle_capture(self) -> None:
        if self.session.is_running:
            self.stop_capture()
        else:
            self.start_capture()

    def start_capture(self) -> None:
        if self.device is None:
            self.show_message("Select a connected device first.")
            return
        options = CaptureOptions(
            engine=self.config.capture.engine,
            bitrate_bps=int(self.config.capture.bitrate_mbps * 1_000_000),
            fps=self.config.capture.fps,
            max_size=self.config.capture.max_size,
            time_limit_s=self.config.capture.time_limit_s,
        )
        self.status_stream.setText("Starting...")
        self.session.start(self.device, options)
        self._update_actions()

    def stop_capture(self) -> None:
        self.act_record.setChecked(False)
        self.session.stop()
        self.video.clear()
        self.status_stream.setText("Idle")
        self.status_rate.setText("")
        self._update_actions()

    def on_frame(self, image) -> None:
        self.video.set_frame(image)
        self.session.frame_rendered()

    def on_stats(self, stats: Stats) -> None:
        parts = [f"{stats.fps:.0f} fps", f"{stats.kbps / 1000:.1f} Mbps"]
        if stats.width:
            parts.append(f"{stats.width}x{stats.height}")
        crop = self.video.crop
        if not crop.isEmpty():
            parts.append(f"crop {crop.width()}x{crop.height()}")
        parts.append(stats.engine)
        if stats.recording:
            parts.append(f"REC {stats.recorded_mb:.0f} MB")
        self.status_rate.setText("   ".join(parts))

    def on_state(self, state: str) -> None:
        labels = {
            "starting": "Starting encoder on device...",
            "streaming": "Mirroring",
            "stopped": "Idle",
        }
        self.status_stream.setText(labels.get(state, state))
        if state == "stopped":
            self.status_rate.setText("")
        self._update_actions()

    def on_failure(self, message: str) -> None:
        self.status_stream.setText("Stopped")
        self._update_actions()
        QMessageBox.warning(self, "Mirroring stopped", message)

    # -------------------------------------------------------------- recording

    def toggle_recording(self, checked: bool) -> None:
        if checked:
            if not self.session.is_running:
                self.act_record.setChecked(False)
                self.show_message("Start mirroring before recording.")
                return
            directory = self.config.resolved_capture_dir()
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            name = (self._device_model or "device").replace(" ", "-")
            destination = directory / f"{name}-{stamp}.mp4"
            self.session.start_recording(destination, fps=self.config.capture.fps)
            self.show_message(f"Recording to {destination}")
        else:
            self.session.stop_recording()
            self.show_message("Finishing recording...")

    def save_screenshot(self) -> None:
        if not self.video.has_frame:
            self.show_message("Nothing to capture yet.")
            return
        image = self.video.frame.copy(self.video.source_rect())
        directory = self.config.resolved_capture_dir()
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        name = (self._device_model or "device").replace(" ", "-")
        path = directory / f"{name}-{stamp}.png"
        if image.save(str(path)):
            self.show_message(f"Saved {path}")
        else:
            self.show_message("Could not save the screenshot.")

    # ------------------------------------------------------------------- view

    def auto_crop(self) -> None:
        if not self.video.has_frame:
            self.show_message("Start mirroring first.")
            return
        rect = self.video.auto_crop()
        if rect is None:
            self.show_message("No black borders detected.")
            return
        self._apply_crop(rect)
        self.show_message(f"Cropped to {rect.width()}x{rect.height()}.")

    def crop_left_eye(self) -> None:
        if not self.video.has_frame:
            self.show_message("Start mirroring first.")
            return
        rect = self.video.crop_to_left_eye()
        if rect is None:
            return
        self._apply_crop(rect)

    def reset_crop(self) -> None:
        self.video.set_crop(None)
        self.config.set_crop(self._device_model, None)

    def _apply_crop(self, rect: QRect) -> None:
        self.video.set_crop(rect)
        self.config.set_crop(
            self._device_model, [rect.x(), rect.y(), rect.width(), rect.height()]
        )

    def set_fit_mode(self, mode: str) -> None:
        self.config.view.fit_mode = mode
        self.video.set_fit_mode(mode)

    def set_always_on_top(self, checked: bool) -> None:
        self.config.view.always_on_top = bool(checked)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, bool(checked))
        self.show()

    def toggle_fullscreen(self) -> None:
        if self._fullscreen:
            self._leave_fullscreen()
        else:
            self._enter_fullscreen()

    def _enter_fullscreen(self) -> None:
        if self._fullscreen:
            return
        self._fullscreen = True
        self._saved_sizes = self.splitter.sizes()
        self.device_panel.hide()
        self.toolbar.hide()
        self.statusBar().hide()
        self.showFullScreen()

    def _leave_fullscreen(self) -> None:
        if not self._fullscreen:
            return
        self._fullscreen = False
        self.showNormal()
        self.device_panel.show()
        self.toolbar.show()
        self.statusBar().show()
        if self._saved_sizes:
            self.splitter.setSizes(self._saved_sizes)

    # ---------------------------------------------------------------- control

    def on_tap(self, x: int, y: int) -> None:
        if self.device is None:
            return
        try:
            self.device.input_tap(x, y)
        except Exception as exc:
            log.debug("tap failed: %s", exc)

    def on_swipe(self, x1: int, y1: int, x2: int, y2: int) -> None:
        if self.device is None:
            return
        try:
            self.device.input_swipe(x1, y1, x2, y2)
        except Exception as exc:
            log.debug("swipe failed: %s", exc)

    # --------------------------------------------------------------- settings

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.config, self)
        if dialog.exec() != SettingsDialog.Accepted:
            return
        dialog.apply_to(self.config)
        self.video.set_smooth(self.config.view.smooth)
        self.config.save()
        if self.session.is_running:
            self.show_message("Settings apply the next time you start mirroring.")

    # ---------------------------------------------------------------- helpers

    def _update_actions(self) -> None:
        running = self.session.is_running
        self.act_start.setText("Stop mirroring" if running else "Start mirroring")
        self.act_start.setEnabled(self.device is not None or running)
        self.act_record.setEnabled(running)
        self.act_shot.setEnabled(self.video.has_frame)
        for action in (self.act_autocrop, self.act_eye, self.act_reset_crop):
            action.setEnabled(self.video.has_frame)

    def show_message(self, text: str, sticky: bool = True) -> None:
        if not text:
            return
        self.statusBar().showMessage(text, 0 if sticky else 6000)
        self._last_message_at = time.monotonic()

    # ------------------------------------------------------------- lifecycle

    def _restore_geometry(self) -> None:
        blob = self.config.window_geometry
        if blob:
            try:
                self.restoreGeometry(QByteArray.fromBase64(blob.encode("ascii")))
            except Exception:
                pass

    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            self.config.window_geometry = bytes(self.saveGeometry().toBase64()).decode("ascii")
            self.config.save()
        except Exception:
            pass
        self.device_panel.stop()
        self.session.stop(timeout=2.0)
        super().closeEvent(event)
