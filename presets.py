"""Device presets for EPUBKit.

Each preset captures the screen dimensions and tuning parameters for a target
e-reader. Adding a new device is one entry in PRESETS.

Backwards compatibility: the X4 preset matches the values previously hardcoded
as X4_WIDTH/X4_HEIGHT in image_processor.py, so callers that don't pick a
preset behave exactly as before.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DevicePreset:
    """A target device's screen + image-pipeline parameters."""

    name: str
    description: str
    max_width: int
    max_height: int
    # Higher contrast factor compensates for fewer grayscale levels.
    contrast_factor: float = 1.5
    # JPEG quality 1-100; lower = smaller files at some perceptual cost.
    quality: int = 70


PRESETS: dict[str, DevicePreset] = {
    "xteink-x4": DevicePreset(
        name="xteink-x4",
        description="Xteink X4 — 800×480 landscape, 4-level grayscale (SSD1677)",
        max_width=800,
        max_height=480,
    ),
    "xteink-x3": DevicePreset(
        name="xteink-x3",
        description="Xteink X3 — 555×740 portrait, 4-level grayscale (SSD1677)",
        max_width=555,
        max_height=740,
    ),
}


def get_preset(name: str) -> DevicePreset:
    """Look up a preset by name; raises KeyError with a helpful message."""
    try:
        return PRESETS[name]
    except KeyError:
        available = ", ".join(sorted(PRESETS))
        raise KeyError(
            f"Unknown preset {name!r}. Available: {available}"
        ) from None
