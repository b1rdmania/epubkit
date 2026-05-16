"""Tests for ProcessingOptions, particularly the from_preset factory."""

from __future__ import annotations

from epub_processor import ProcessingOptions
from presets import get_preset


def test_default_options_match_x4_legacy_behavior():
    """Default ProcessingOptions must produce the same image dimensions as
    before the preset system was added — backwards compatibility for the
    web UI and any other caller that doesn't pick a preset."""
    opts = ProcessingOptions()
    assert opts.max_width == 800
    assert opts.max_height == 480


def test_from_preset_uses_preset_dimensions():
    opts = ProcessingOptions.from_preset(get_preset("xteink-x3"))
    assert opts.max_width == 555
    assert opts.max_height == 740


def test_from_preset_carries_quality_and_contrast():
    preset = get_preset("xteink-x4")
    opts = ProcessingOptions.from_preset(preset)
    assert opts.quality == preset.quality
    assert opts.contrast_factor == preset.contrast_factor


def test_from_preset_overrides_win():
    opts = ProcessingOptions.from_preset(
        get_preset("xteink-x3"),
        quality=50,
        light_novel_mode=True,
        remove_fonts=False,
    )
    assert opts.quality == 50
    assert opts.light_novel_mode is True
    assert opts.remove_fonts is False
    # Preset dimensions still apply
    assert opts.max_width == 555
    assert opts.max_height == 740


def test_from_preset_overrides_dimensions_too():
    """Dimensions are overridable, though usually the preset is enough."""
    opts = ProcessingOptions.from_preset(
        get_preset("xteink-x4"),
        max_width=1024,
        max_height=600,
    )
    assert opts.max_width == 1024
    assert opts.max_height == 600
