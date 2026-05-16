"""Tests for the CLI entry point.

Argument parsing and validation are unit-tested here. End-to-end golden
tests against real EPUB fixtures are a follow-up (need to add fixtures
to tests/fixtures/ — see issue tracker).
"""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout

import pytest

from cli import build_parser, main


def test_main_without_input_or_output_returns_exit_2():
    """--input/--output are required for processing runs but optional at the
    parser level so --list-presets works standalone. main() enforces it."""
    err = io.StringIO()
    with redirect_stderr(err):
        rc = main([])
    assert rc == 2
    assert "required" in err.getvalue().lower()


def test_parser_accepts_minimum_args(tmp_path):
    parser = build_parser()
    args = parser.parse_args(
        ["--input", str(tmp_path / "in.epub"), "--output", str(tmp_path / "out.epub")]
    )
    assert args.preset == "xteink-x4"
    assert args.quality is None
    assert args.light_novel is False
    assert args.keep_fonts is False


def test_parser_rejects_unknown_preset(tmp_path):
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "--input", str(tmp_path / "in.epub"),
                "--output", str(tmp_path / "out.epub"),
                "--preset", "nonexistent-device",
            ]
        )


def test_list_presets_exits_zero_and_prints_each():
    out = io.StringIO()
    with redirect_stdout(out):
        rc = main(["--list-presets"])
    assert rc == 0
    text = out.getvalue()
    assert "xteink-x3" in text
    assert "xteink-x4" in text


def test_missing_input_returns_exit_2(tmp_path):
    err = io.StringIO()
    with redirect_stderr(err):
        rc = main(
            [
                "--input", str(tmp_path / "does-not-exist.epub"),
                "--output", str(tmp_path / "out.epub"),
            ]
        )
    assert rc == 2
    assert "not found" in err.getvalue()


def test_invalid_quality_returns_exit_2(tmp_path):
    fake_input = tmp_path / "in.epub"
    fake_input.write_bytes(b"not really an epub")
    err = io.StringIO()
    with redirect_stderr(err):
        rc = main(
            [
                "--input", str(fake_input),
                "--output", str(tmp_path / "out.epub"),
                "--quality", "150",
            ]
        )
    assert rc == 2
    assert "quality" in err.getvalue().lower()
