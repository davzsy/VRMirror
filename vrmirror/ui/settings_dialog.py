"""Capture settings."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)

from ..capture.engines import NativeEngine
from ..config import Config

SIZE_CHOICES = [
    ("Automatic (headset preset)", 0),
    ("Device native", -1),
    ("2048 px", 2048),
    ("1600 px", 1600),
    ("1440 px", 1440),
    ("1280 px", 1280),
    ("1024 px", 1024),
    ("800 px", 800),
]


class SettingsDialog(QDialog):
    def __init__(self, config: Config, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Capture settings")
        self.setMinimumWidth(420)
        self._config = config

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)

        self.engine = QComboBox()
        native_ready = NativeEngine.is_available()
        self.engine.addItem("Automatic", "auto")
        self.engine.addItem("screenrecord (no install on device)", "screenrecord")
        self.engine.addItem(
            "Native server (low latency)" + ("" if native_ready else " - not built"),
            "native",
        )
        if not native_ready:
            try:
                self.engine.model().item(2).setEnabled(False)
            except AttributeError:
                pass
        index = self.engine.findData(config.capture.engine)
        self.engine.setCurrentIndex(index if index >= 0 else 0)
        form.addRow("Engine", self.engine)

        self.bitrate = QDoubleSpinBox()
        self.bitrate.setRange(1.0, 60.0)
        self.bitrate.setSingleStep(1.0)
        self.bitrate.setSuffix(" Mbps")
        self.bitrate.setValue(config.capture.bitrate_mbps)
        form.addRow("Bitrate", self.bitrate)

        self.max_size = QComboBox()
        for label, value in SIZE_CHOICES:
            self.max_size.addItem(label, value)
        size_index = self.max_size.findData(config.capture.max_size)
        self.max_size.setCurrentIndex(size_index if size_index >= 0 else 0)
        form.addRow("Max dimension", self.max_size)

        self.fps = QSpinBox()
        self.fps.setRange(15, 120)
        self.fps.setValue(config.capture.fps)
        self.fps.setSuffix(" fps")
        form.addRow("Target frame rate", self.fps)

        self.time_limit = QSpinBox()
        self.time_limit.setRange(60, 21600)
        self.time_limit.setSingleStep(60)
        self.time_limit.setValue(config.capture.time_limit_s)
        self.time_limit.setSuffix(" s")
        self.time_limit.setToolTip(
            "How long each screenrecord invocation may run. Older Android builds "
            "cap this at 180 seconds; VRMirror detects that and restarts the "
            "stream automatically."
        )
        form.addRow("Segment length", self.time_limit)

        self.smooth = QCheckBox("Smooth scaling")
        self.smooth.setChecked(config.view.smooth)
        form.addRow("", self.smooth)

        layout.addLayout(form)

        note = QLabel(
            "Higher bitrate costs bandwidth, not latency. If the picture stutters "
            "over Wi-Fi, lower the max dimension first."
        )
        note.setObjectName("hint")
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def apply_to(self, config: Config) -> None:
        config.capture.engine = self.engine.currentData()
        config.capture.bitrate_mbps = float(self.bitrate.value())
        config.capture.max_size = int(self.max_size.currentData())
        config.capture.fps = int(self.fps.value())
        config.capture.time_limit_s = int(self.time_limit.value())
        config.view.smooth = self.smooth.isChecked()
