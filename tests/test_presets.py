"""Tests for the device preset registry."""

from __future__ import annotations

import pytest

from presets import DevicePreset, PRESETS, get_preset


def test_x4_preset_matches_legacy_constants():
    """The X4 preset must match the values previously hardcoded as
    X4_WIDTH/X4_HEIGHT in image_processor — backwards compatibility."""
    p = get_preset("xteink-x4")
    assert p.max_width == 800
    assert p.max_height == 480


def test_x3_preset_dimensions():
    p = get_preset("xteink-x3")
    assert p.max_width == 555
    assert p.max_height == 740


@pytest.mark.parametrize("name", sorted(PRESETS))
def test_every_preset_has_valid_fields(name: str):
    p = PRESETS[name]
    assert isinstance(p, DevicePreset)
    assert p.name == name
    assert p.description, "description must be non-empty"
    assert p.max_width > 0
    assert p.max_height > 0
    assert 1 <= p.quality <= 100
    assert p.contrast_factor > 0


def test_get_preset_unknown_lists_alternatives():
    with pytest.raises(KeyError) as exc_info:
        get_preset("xteink-x99")
    msg = str(exc_info.value)
    assert "xteink-x99" in msg
    assert "xteink-x3" in msg
    assert "xteink-x4" in msg


def test_presets_dict_is_keyed_by_name():
    """name field and PRESETS key must agree — avoids subtle lookup bugs."""
    for key, preset in PRESETS.items():
        assert key == preset.name
