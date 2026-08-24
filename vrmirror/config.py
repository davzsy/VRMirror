"""Settings, persisted as JSON in the platform config directory."""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import APP_NAME

log = logging.getLogger(__name__)


def config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP_NAME


def config_path() -> Path:
    return config_dir() / "settings.json"


def default_capture_dir() -> Path:
    videos = Path.home() / "Videos"
    if not videos.exists():
        videos = Path.home() / "Movies"
    if not videos.exists():
        videos = Path.home()
    return videos / APP_NAME


@dataclass
class CaptureConfig:
    engine: str = "auto"  # auto | screenrecord | native
    bitrate_mbps: float = 12.0
    fps: int = 60
    max_size: int = 0  # 0 keeps the device resolution
    time_limit_s: int = 1800


@dataclass
class ViewConfig:
    fit_mode: str = "fit"  # fit | fill | actual
    smooth: bool = True
    always_on_top: bool = False
    # Per device-model crop rectangles, stored as [x, y, w, h] in native pixels.
    crops: dict = field(default_factory=dict)


@dataclass
class Config:
    capture: CaptureConfig = field(default_factory=CaptureConfig)
    view: ViewConfig = field(default_factory=ViewConfig)
    last_serial: str = ""
    capture_dir: str = ""
    window_geometry: str = ""

    # ------------------------------------------------------------------- load

    @classmethod
    def load(cls) -> "Config":
        path = config_path()
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text("utf-8"))
        except Exception as exc:
            log.warning("could not read %s, using defaults: %s", path, exc)
            return cls()

        config = cls()
        for key, value in raw.items():
            if key == "capture" and isinstance(value, dict):
                config.capture = CaptureConfig(
                    **{k: v for k, v in value.items() if k in CaptureConfig.__annotations__}
                )
            elif key == "view" and isinstance(value, dict):
                config.view = ViewConfig(
                    **{k: v for k, v in value.items() if k in ViewConfig.__annotations__}
                )
            elif key in cls.__annotations__:
                setattr(config, key, value)
        return config

    # ------------------------------------------------------------------- save

    def save(self) -> None:
        path = config_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(asdict(self), indent=2), "utf-8")
            tmp.replace(path)
        except Exception as exc:
            log.warning("could not save settings: %s", exc)

    # ---------------------------------------------------------------- helpers

    def resolved_capture_dir(self) -> Path:
        directory = Path(self.capture_dir) if self.capture_dir else default_capture_dir()
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def crop_for(self, model: str) -> list[int] | None:
        value = self.view.crops.get(model)
        if isinstance(value, list) and len(value) == 4 and value[2] > 0 and value[3] > 0:
            return [int(v) for v in value]
        return None

    def set_crop(self, model: str, rect: list[int] | None) -> None:
        if not model:
            return
        if rect is None:
            self.view.crops.pop(model, None)
        else:
            self.view.crops[model] = [int(v) for v in rect]
