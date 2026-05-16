"""Command-line entry point for EPUBKit.

Process an EPUB without the web UI. Useful for non-interactive workflows
(sending books to e-ink devices via Calibre, custom sync clients, etc.).

Example:
    epubkit-cli --input book.epub --output book-x3.epub --preset xteink-x3
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from epub_processor import ProcessingOptions, process_epub
from presets import PRESETS, get_preset


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="epubkit-cli",
        description="Optimize an EPUB for a target e-ink reader.",
    )
    # Not marked required at the parser level so --list-presets works
    # standalone; required-ness is enforced in main() after we know whether
    # the user is asking for a utility action instead of a processing run.
    p.add_argument(
        "--input", type=Path, metavar="EPUB",
        help="Input EPUB file (required unless --list-presets)",
    )
    p.add_argument(
        "--output", type=Path, metavar="EPUB",
        help="Output EPUB file, overwritten if it exists (required unless --list-presets)",
    )
    p.add_argument(
        "--preset", default="xteink-x4", choices=sorted(PRESETS),
        help="Device target (default: xteink-x4)",
    )
    p.add_argument(
        "--quality", type=int, default=None, metavar="N",
        help="JPEG quality 1-100 (default: from preset)",
    )
    p.add_argument(
        "--light-novel", action="store_true",
        help="Enable light-novel mode (rotate/split landscape images)",
    )
    p.add_argument(
        "--keep-fonts", action="store_true",
        help="Don't remove embedded fonts (default: remove)",
    )
    p.add_argument(
        "--verbose", "-v", action="store_true",
        help="Print pipeline progress to stderr",
    )
    p.add_argument(
        "--list-presets", action="store_true",
        help="List available presets and exit",
    )
    return p


def _print_presets() -> None:
    width = max(len(name) for name in PRESETS)
    for name in sorted(PRESETS):
        preset = PRESETS[name]
        print(f"{name:<{width}}  {preset.description}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list_presets:
        _print_presets()
        return 0

    if args.input is None or args.output is None:
        print(
            "Error: --input and --output are required (or use --list-presets)",
            file=sys.stderr,
        )
        return 2

    if not args.input.exists():
        print(f"Error: input file not found: {args.input}", file=sys.stderr)
        return 2

    preset = get_preset(args.preset)

    overrides: dict = {}
    if args.quality is not None:
        if not 1 <= args.quality <= 100:
            print(
                f"Error: --quality must be 1-100, got {args.quality}",
                file=sys.stderr,
            )
            return 2
        overrides["quality"] = args.quality
    if args.light_novel:
        overrides["light_novel_mode"] = True
    if args.keep_fonts:
        overrides["remove_fonts"] = False

    options = ProcessingOptions.from_preset(preset, **overrides)

    def progress(pct: int, msg: str) -> None:
        if args.verbose:
            print(f"[{pct:3d}%] {msg}", file=sys.stderr)

    report = process_epub(
        str(args.input), str(args.output), options, progress,
    )

    if not report.success:
        print(f"Error: {report.error}", file=sys.stderr)
        return 1

    print(report.summary())
    return 0


if __name__ == "__main__":
    sys.exit(main())
