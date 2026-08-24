"""Device sidebar: discovery, wireless setup and connection state."""

from __future__ import annotations

import threading
import time

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..adb.client import Adb, DeviceInfo

STATE_HINTS = {
    "unauthorized": "Accept the USB debugging prompt on the device.",
    "offline": "Device is offline. Reconnect the cable or re-run Wi-Fi setup.",
    "no permissions": "Your user lacks USB permissions for this device.",
}


class DeviceWatcher(QObject):
    """Pushes device lists from host:track-devices onto the UI thread."""

    devicesChanged = Signal(list)

    def __init__(self, adb: Adb, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._adb = adb
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="vrmirror-watch", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        self._adb.track_devices(
            on_change=lambda devices: self.devicesChanged.emit(devices),
            should_stop=self._stop.is_set,
        )


class DevicePanel(QWidget):
    deviceSelected = Signal(object)  # DeviceInfo or None
    message = Signal(str)

    def __init__(self, adb: Adb, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._adb = adb
        self._devices: list[DeviceInfo] = []
        self._pending_serial: str = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        devices_box = QGroupBox("Devices")
        devices_layout = QVBoxLayout(devices_box)
        devices_layout.setSpacing(8)

        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.SingleSelection)
        self.list.currentItemChanged.connect(self._on_selection_changed)
        devices_layout.addWidget(self.list, 1)

        self.hint = QLabel("Looking for devices...")
        self.hint.setObjectName("hint")
        self.hint.setWordWrap(True)
        devices_layout.addWidget(self.hint)

        layout.addWidget(devices_box, 1)

        wireless_box = QGroupBox("Wireless")
        wireless_layout = QVBoxLayout(wireless_box)
        wireless_layout.setSpacing(6)

        self.btn_go_wireless = QPushButton("Untether selected device")
        self.btn_go_wireless.setToolTip(
            "With the headset on USB, switch its adb to Wi-Fi and reconnect over "
            "the network. You can then unplug the cable."
        )
        self.btn_go_wireless.clicked.connect(self._go_wireless)
        wireless_layout.addWidget(self.btn_go_wireless)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.btn_connect = QPushButton("Connect IP")
        self.btn_connect.clicked.connect(self._connect_ip)
        row.addWidget(self.btn_connect)

        self.btn_pair = QPushButton("Pair")
        self.btn_pair.setToolTip("Android 11+ pairing code flow.")
        self.btn_pair.clicked.connect(self._pair)
        row.addWidget(self.btn_pair)
        wireless_layout.addLayout(row)

        layout.addWidget(wireless_box)

        self.watcher = DeviceWatcher(adb, self)
        self.watcher.devicesChanged.connect(self.set_devices)

    # -------------------------------------------------------------- lifecycle

    def start(self) -> None:
        self.watcher.start()

    def stop(self) -> None:
        self.watcher.stop()

    # ---------------------------------------------------------------- devices

    @property
    def current(self) -> DeviceInfo | None:
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def select_serial(self, serial: str) -> None:
        self._pending_serial = serial
        for index in range(self.list.count()):
            item = self.list.item(index)
            info: DeviceInfo = item.data(Qt.UserRole)
            if info.serial == serial:
                self.list.setCurrentRow(index)
                return

    def set_devices(self, devices: list[DeviceInfo]) -> None:
        previous = self.current.serial if self.current else self._pending_serial
        self._devices = devices

        self.list.blockSignals(True)
        self.list.clear()
        for info in devices:
            item = QListWidgetItem(self._describe(info))
            item.setData(Qt.UserRole, info)
            if not info.is_usable:
                item.setForeground(QBrush(QColor("#8a8f9a")))
            self.list.addItem(item)
        self.list.blockSignals(False)

        restored = False
        if previous:
            for index in range(self.list.count()):
                if self.list.item(index).data(Qt.UserRole).serial == previous:
                    self.list.setCurrentRow(index)
                    restored = True
                    break
        if not restored:
            usable = next(
                (i for i, info in enumerate(devices) if info.is_usable), 0 if devices else -1
            )
            if usable >= 0:
                self.list.setCurrentRow(usable)
            else:
                self.deviceSelected.emit(None)

        self._update_hint()

    def _describe(self, info: DeviceInfo) -> str:
        if info.is_usable:
            return f"{info.label}\n{info.serial}"
        return f"{info.label}  [{info.state}]\n{info.serial}"

    def _update_hint(self) -> None:
        if not self._devices:
            self.hint.setText(
                "No devices found.\n\n"
                "Headset: enable Developer Mode in the phone app, turn on USB "
                "debugging, plug in the cable, then accept the prompt inside the "
                "headset."
            )
            return
        current = self.current
        if current is not None and not current.is_usable:
            self.hint.setText(STATE_HINTS.get(current.state, f"Device state: {current.state}"))
            return
        count = len(self._devices)
        self.hint.setText(f"{count} device{'s' if count != 1 else ''} available.")

    def _on_selection_changed(self, current, _previous) -> None:
        info = current.data(Qt.UserRole) if current is not None else None
        self._update_hint()
        self.deviceSelected.emit(info)

    # --------------------------------------------------------------- wireless

    def _go_wireless(self) -> None:
        info = self.current
        if info is None or not info.is_usable:
            self.message.emit("Select a connected device first.")
            return
        if info.is_wireless:
            self.message.emit("That device is already on Wi-Fi.")
            return

        device = self._adb.device(info.serial)
        try:
            address = device.wifi_ip()
        except Exception as exc:
            self.message.emit(f"Could not read the device IP: {exc}")
            return
        if not address:
            self.message.emit(
                "The device has no Wi-Fi address. Connect it to the same network "
                "as this computer and try again."
            )
            return

        try:
            device.tcpip(5555)
        except Exception as exc:
            self.message.emit(f"Could not switch to TCP mode: {exc}")
            return

        # adbd needs a moment to restart before it accepts the connection.
        result = ""
        for _ in range(6):
            time.sleep(0.8)
            result = self._adb.connect(f"{address}:5555")
            if "connected" in result.lower():
                break

        self.message.emit(result or f"Tried to connect to {address}:5555")
        if "connected" in result.lower():
            self.select_serial(f"{address}:5555")
            QMessageBox.information(
                self,
                "Wireless ready",
                f"Connected to {address}:5555.\n\nYou can unplug the cable now. "
                "After a headset reboot, use Connect IP with the same address.",
            )

    def _connect_ip(self) -> None:
        address, ok = QInputDialog.getText(
            self, "Connect over Wi-Fi", "Device address (ip or ip:port):"
        )
        if not ok or not address.strip():
            return
        self.message.emit(self._adb.connect(address.strip()))

    def _pair(self) -> None:
        address, ok = QInputDialog.getText(
            self,
            "Pair device",
            "Pairing address shown on the device (ip:port):",
        )
        if not ok or not address.strip():
            return
        code, ok = QInputDialog.getText(self, "Pair device", "Six digit pairing code:")
        if not ok or not code.strip():
            return
        self.message.emit(self._adb.pair(address.strip(), code.strip()))
