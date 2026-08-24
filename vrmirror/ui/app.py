"""Application entry point."""

from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from .. import APP_NAME, __version__
from ..adb.binary import AdbNotFound, ensure_server
from ..adb.client import Adb
from ..config import Config, config_dir
from . import theme


def _setup_logging() -> None:
    log_dir = config_dir()
    handlers: list[logging.Handler] = []
    # A windowed frozen build has no stderr at all, and logging to None fails
    # silently on every record. The file handler is what matters there.
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler(sys.stderr))
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_dir / "vrmirror.log", encoding="utf-8"))
    except OSError:
        pass
    if not handlers:
        handlers.append(logging.NullHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers,
    )


def main() -> int:
    _setup_logging()
    log = logging.getLogger(__name__)
    log.info("%s %s starting", APP_NAME, __version__)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    theme.apply(app)

    try:
        import av  # noqa: F401
    except Exception as exc:
        QMessageBox.critical(
            None,
            APP_NAME,
            "The video decoder (PyAV) could not be loaded.\n\n"
            f"{exc}\n\nInstall it with:  pip install av",
        )
        return 2

    try:
        ensure_server()
    except AdbNotFound as exc:
        QMessageBox.critical(None, APP_NAME, str(exc))
        return 2

    config = Config.load()
    adb = Adb()

    from .main_window import MainWindow

    window = MainWindow(adb, config)
    window.show()

    if config.last_serial:
        window.device_panel.select_serial(config.last_serial)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
