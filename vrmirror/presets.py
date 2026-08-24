"""Device presets, mostly for standalone VR headsets.

A headset's "display 0" is not a phone screen: the compositor output is
letterboxed, sometimes doubled, and usually much larger than anything you want
to stream. These presets give sane starting values; the auto-crop button in the
UI then trims the black borders for the specific headset and system version.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Preset:
    name: str
    max_size: int
    bitrate_mbps: float
    fps: int
    note: str = ""


GENERIC = Preset(
    name="Generic Android",
    max_size=1600,
    bitrate_mbps=10.0,
    fps=60,
    note="Balanced defaults for a phone or tablet.",
)

VR_DEFAULT = Preset(
    name="Standalone VR headset",
    max_size=1280,
    bitrate_mbps=14.0,
    fps=72,
    note=(
        "Headsets render a wide compositor surface with black borders. "
        "Start the stream, then use Auto-crop to trim them."
    ),
)

# Matched against ro.product.model, case insensitive, substring match.
_MODEL_PRESETS: list[tuple[str, Preset]] = [
    (
        "quest 3",
        Preset("Meta Quest 3", 1440, 16.0, 72, "Crop to one eye for the clearest view."),
    ),
    (
        "quest 3s",
        Preset("Meta Quest 3S", 1440, 16.0, 72, "Crop to one eye for the clearest view."),
    ),
    (
        "quest pro",
        Preset("Meta Quest Pro", 1440, 16.0, 72, "Crop to one eye for the clearest view."),
    ),
    (
        "quest 2",
        Preset("Meta Quest 2", 1280, 12.0, 72, "1280 keeps the encoder comfortable."),
    ),
    ("quest", VR_DEFAULT),
    ("pico", Preset("Pico headset", 1280, 12.0, 72, "Enable USB debugging in Pico settings.")),
    ("vive", Preset("HTC Vive XR", 1280, 12.0, 72, "")),
]


def preset_for(model: str, manufacturer: str = "") -> Preset:
    haystack = f"{manufacturer} {model}".lower()
    for needle, preset in _MODEL_PRESETS:
        if needle in haystack:
            return preset
    if any(word in haystack for word in ("oculus", "meta", "vr", "hmd")):
        return VR_DEFAULT
    return GENERIC


def is_headset(model: str, manufacturer: str = "") -> bool:
    return preset_for(model, manufacturer) is not GENERIC
