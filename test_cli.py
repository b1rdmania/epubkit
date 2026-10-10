import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image, ImageDraw

from cli import find_epub_files, batch_optimize, create_parser, main
from test_pipeline import build_epub


@pytest.fixture
def sample_epubs_dir():
    """Create a temporary directory with a structure of sample EPUBs."""
    tmp_dir = tempfile.mkdtemp()
    sub_dir = os.path.join(tmp_dir, "subdir")
    os.makedirs(sub_dir, exist_ok=True)

    # 2 EPUBs in root
    build_epub(os.path.join(tmp_dir, "book1.epub"))
    build_epub(os.path.join(tmp_dir, "book2.epub"))

    # 1 EPUB in subdir
    build_epub(os.path.join(sub_dir, "book3.epub"))

    # 1 non-epub file and 1 kepub file
    with open(os.path.join(tmp_dir, "notes.txt"), "w") as f:
        f.write("test")
    with open(os.path.join(tmp_dir, "ignored.kepub.epub"), "w") as f:
        f.write("test")

    return Path(tmp_dir)


def test_find_epub_files(sample_epubs_dir):
    # Recursive search (default)
    found_recursive = find_epub_files([str(sample_epubs_dir)], recursive=True)
    names = [p.name for p in found_recursive]
    assert len(found_recursive) == 3
    assert "book1.epub" in names
    assert "book2.epub" in names
    assert "book3.epub" in names
    assert "ignored.kepub.epub" not in names
    assert "notes.txt" not in names

    # Non-recursive search
    found_flat = find_epub_files([str(sample_epubs_dir)], recursive=False)
    assert len(found_flat) == 2
    flat_names = [p.name for p in found_flat]
    assert "book1.epub" in flat_names
    assert "book2.epub" in flat_names
    assert "book3.epub" not in flat_names


def test_batch_optimize_quick_preset(sample_epubs_dir):
    out_dir = sample_epubs_dir / "out"
    success, fail, results = batch_optimize(
        input_paths=[str(sample_epubs_dir)],
        output_dir=str(out_dir),
        preset="quick",
        workers=2,
        quiet=True,
    )

    assert success == 3
    assert fail == 0
    assert len(results) == 3

    for src_p, dst_p, report, elapsed in results:
        assert report.success
        assert os.path.exists(dst_p)
        assert os.path.getsize(dst_p) > 0


def test_batch_optimize_full_preset(sample_epubs_dir):
    out_dir = sample_epubs_dir / "out_full"
    success, fail, results = batch_optimize(
        input_paths=[str(sample_epubs_dir / "book1.epub")],
        output_dir=str(out_dir),
        preset="full",
        device="x3",
        workers=1,
        quiet=True,
    )

    assert success == 1
    assert fail == 0
    assert len(results) == 1
    assert results[0][2].success


def test_cli_parser_options():
    parser = create_parser()
    args = parser.parse_args(["/path/to/books", "-p", "quick", "-d", "x4", "-w", "4", "-q", "80"])
    assert args.paths == ["/path/to/books"]
    assert args.preset == "quick"
    assert args.device == "x4"
    assert args.workers == 4
    assert args.quality == 80
    assert args.recursive is True


def test_cli_main_invocation(sample_epubs_dir):
    out_dir = sample_epubs_dir / "cli_out"
    test_args = [
        "epubkit",
        str(sample_epubs_dir),
        "-o", str(out_dir),
        "-p", "quick",
        "-w", "2",
        "--quiet",
    ]

    with patch.object(sys, "argv", test_args):
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0

    assert os.path.exists(out_dir / "book1.epub")
    assert os.path.exists(out_dir / "book2.epub")
    assert os.path.exists(out_dir / "book3.epub")
