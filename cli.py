"""
Command-line interface (CLI) for batch optimizing EPUB files.
High-performance batch processing with multiprocessing and multithreading.
"""

import os
import sys
import time
import argparse
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Optional, List, Tuple, Union, Dict

from epub_processor import (
    process_epub,
    ProcessingOptions,
    ProcessingReport,
    PRESETS,
    _fmt_size,
)
from image_processor import DEVICE_PROFILES, DEFAULT_DEVICE
from metadata_handler import FILENAME_FORMATS


def find_epub_files(
    paths: List[str],
    recursive: bool = True,
    exclude_paths: Optional[List[Union[str, Path]]] = None,
) -> List[Path]:
    """Find all valid .epub files in the given paths (files or directories)."""
    found: List[Path] = []
    seen = set()
    excludes = [Path(e).expanduser().resolve() for e in (exclude_paths or [])]

    for p_str in paths:
        p = Path(p_str).expanduser().resolve()
        if not p.exists():
            print(f"Warning: Path does not exist: {p_str}", file=sys.stderr)
            continue

        if p.is_file():
            if p.suffix.lower() == '.epub' and not p.name.lower().endswith('.kepub.epub'):
                if any(p == ex or ex in p.parents for ex in excludes):
                    continue
                if p not in seen:
                    seen.add(p)
                    found.append(p)
        elif p.is_dir():
            if any(p == ex for ex in excludes):
                continue
            pattern = '**/*.epub' if recursive else '*.epub'
            for match in p.glob(pattern):
                if match.is_file() and not match.name.lower().endswith('.kepub.epub'):
                    # Skip files in hidden directories relative to input root p
                    try:
                        rel = match.relative_to(p)
                    except ValueError:
                        continue
                    if any(part.startswith('.') for part in rel.parts):
                        continue
                    # Skip files located within excluded directories
                    if any(match == ex or ex in match.parents for ex in excludes):
                        continue
                    if match not in seen:
                        seen.add(match)
                        found.append(match)

    return sorted(found)


def _process_single_epub_task(args: Tuple[str, str, ProcessingOptions, bool]) -> Tuple[str, str, ProcessingReport, float]:
    """Worker task for multiprocessing batch execution."""
    src_path, dst_path, options, overwrite = args
    t0 = time.perf_counter()

    os.makedirs(os.path.dirname(os.path.abspath(dst_path)), exist_ok=True)

    if not overwrite and os.path.exists(dst_path) and os.path.getsize(dst_path) > 0:
        report = ProcessingReport(
            success=True,
            original_size=os.path.getsize(src_path),
            optimized_size=os.path.getsize(dst_path),
            output_filename=os.path.basename(dst_path),
        )
        return src_path, dst_path, report, 0.0

    try:
        report = process_epub(src_path, dst_path, options)
    except Exception as e:
        report = ProcessingReport(
            success=False,
            error=str(e),
            original_size=os.path.getsize(src_path) if os.path.exists(src_path) else 0,
        )

    elapsed = time.perf_counter() - t0
    return src_path, dst_path, report, elapsed


def batch_optimize(
    input_paths: List[str],
    output_dir: Optional[str] = None,
    preset: str = 'quick',
    device: str = DEFAULT_DEVICE,
    workers: Optional[int] = None,
    recursive: bool = True,
    overwrite: bool = True,
    options_overrides: Optional[dict] = None,
    quiet: bool = False,
    verbose: bool = False,
) -> Tuple[int, int, List[Tuple[str, str, ProcessingReport, float]]]:
    """
    Batch optimize all EPUB files in the specified input paths.
    Returns (success_count, fail_count, results).
    """
    if output_dir:
        out_path = Path(output_dir).expanduser().resolve()
        out_path.mkdir(parents=True, exist_ok=True)
    else:
        # If single directory was provided, default to <dir>/optimized
        first_input = Path(input_paths[0]).expanduser().resolve()
        if first_input.is_dir():
            out_path = first_input / "optimized"
            out_path.mkdir(parents=True, exist_ok=True)
        else:
            out_path = first_input.parent / "optimized"
            out_path.mkdir(parents=True, exist_ok=True)

    epub_files = find_epub_files(input_paths, recursive=recursive, exclude_paths=[out_path])
    if not epub_files:
        if not quiet:
            print("No EPUB files found in the specified paths.")
        return 0, 0, []

    # Build options
    overrides = options_overrides or {}
    overrides['device'] = device
    base_options = ProcessingOptions.for_preset(preset, **overrides)

    if workers is None or workers <= 0:
        cpu_cnt = os.cpu_count() or 4
        # Limit worker count to file count
        workers = min(cpu_cnt, len(epub_files))

    if not quiet:
        print(f"\n=======================================================")
        print(f" epubkit Batch Optimizer")
        print(f" - Found files  : {len(epub_files)} EPUBs")
        print(f" - Preset       : {preset.upper()}")
        print(f" - Target Device: {DEVICE_PROFILES.get(device, {}).get('label', device)}")
        print(f" - Output Dir   : {out_path}")
        print(f" - Parallelism  : {workers} workers")
        print(f"=======================================================\n")

    # Map input directories to preserve relative subpaths
    input_dirs = [
        Path(p_str).expanduser().resolve()
        for p_str in input_paths
        if Path(p_str).expanduser().resolve().is_dir()
    ]

    # Prepare tasks
    tasks = []
    seen_destinations: Dict[str, str] = {}
    for src in epub_files:
        rel_path = None
        for in_dir in input_dirs:
            try:
                rel_path = src.relative_to(in_dir)
                break
            except ValueError:
                continue

        if rel_path is not None:
            dst = out_path / rel_path
        else:
            dst = out_path / src.name

        dst_str = str(dst)
        if dst_str in seen_destinations:
            raise ValueError(
                f"Duplicate destination path '{dst_str}' for distinct inputs: '{seen_destinations[dst_str]}' and '{src}'"
            )
        seen_destinations[dst_str] = str(src)

        # Clone options for this specific file
        file_opts = ProcessingOptions(**vars(base_options))
        file_opts.original_filename = src.name
        tasks.append((str(src), dst_str, file_opts, overwrite))

    start_time = time.perf_counter()
    results: List[Tuple[str, str, ProcessingReport, float]] = []
    success_count = 0
    fail_count = 0

    if workers == 1 or len(tasks) == 1:
        # Sequential execution
        for i, task_args in enumerate(tasks, start=1):
            src_p = Path(task_args[0]).name
            if not quiet and not verbose:
                print(f"[{i}/{len(tasks)}] Optimizing {src_p}...", end="", flush=True)
            res = _process_single_epub_task(task_args)
            results.append(res)
            _, _, report, elapsed = res
            if report.success:
                success_count += 1
                if not quiet:
                    saved_pct = ((1 - report.optimized_size / max(report.original_size, 1)) * 100) if report.original_size else 0
                    print(f"\r[{i}/{len(tasks)}] ✓ {src_p} ({_fmt_size(report.original_size)} → {_fmt_size(report.optimized_size)}, -{saved_pct:.1f}%) in {elapsed:.2f}s")
            else:
                fail_count += 1
                if not quiet:
                    print(f"\r[{i}/{len(tasks)}] ✗ {src_p} failed: {report.error}")
    else:
        # Multiprocess parallel execution
        with ProcessPoolExecutor(max_workers=workers) as executor:
            future_to_file = {executor.submit(_process_single_epub_task, task): task[0] for task in tasks}
            completed = 0
            for future in as_completed(future_to_file):
                completed += 1
                res = future.result()
                results.append(res)
                src_path, dst_path, report, elapsed = res
                src_p = Path(src_path).name

                if report.success:
                    success_count += 1
                    if not quiet:
                        saved_pct = ((1 - report.optimized_size / max(report.original_size, 1)) * 100) if report.original_size else 0
                        print(f"[{completed}/{len(tasks)}] ✓ {src_p} ({_fmt_size(report.original_size)} → {_fmt_size(report.optimized_size)}, -{saved_pct:.1f}%) in {elapsed:.2f}s")
                        if verbose:
                            print(f"    └─ Summary: {report.summary()}")
                else:
                    fail_count += 1
                    if not quiet:
                        print(f"[{completed}/{len(tasks)}] ✗ {src_p} failed: {report.error}")

    total_time = time.perf_counter() - start_time

    # Summary calculation
    total_orig = sum(r[2].original_size for r in results if r[2].success)
    total_opt = sum(r[2].optimized_size for r in results if r[2].success)
    total_saved = max(0, total_orig - total_opt)
    total_reduction = ((1 - total_opt / max(total_orig, 1)) * 100) if total_orig else 0

    if not quiet:
        print("\n" + "=" * 55)
        print(f" Optimization Summary")
        print(f" - Succeeded    : {success_count}/{len(tasks)}")
        if fail_count > 0:
            print(f" - Failed       : {fail_count}/{len(tasks)}")
        print(f" - Total Size   : {_fmt_size(total_orig)} → {_fmt_size(total_opt)} (-{total_reduction:.1f}%, saved {_fmt_size(total_saved)})")
        print(f" - Total Time   : {total_time:.2f}s (avg {total_time / max(len(tasks), 1):.2f}s/book)")
        if total_time > 0 and total_orig > 0:
            throughput_mb = (total_orig / (1024 * 1024)) / total_time
            print(f" - Throughput   : {len(tasks) / total_time:.1f} books/s ({throughput_mb:.2f} MB/s)")
        print("=" * 55 + "\n")

    return success_count, fail_count, results


def create_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="epubkit",
        description="Fast batch EPUB optimizer tailored for E-ink readers (Xteink X4, X3, etc.).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "paths",
        nargs="+",
        help="Input folder(s), EPUB file(s), or glob pattern to optimize.",
    )
    parser.add_argument(
        "-o", "--output-dir",
        default=None,
        help="Output directory to store optimized EPUBs (defaults to <input_dir>/optimized).",
    )
    parser.add_argument(
        "-p", "--preset",
        choices=list(PRESETS.keys()),
        default="quick",
        help="Optimization preset profile.",
    )
    parser.add_argument(
        "-d", "--device",
        choices=list(DEVICE_PROFILES.keys()),
        default=DEFAULT_DEVICE,
        help="Target E-ink device profile.",
    )
    parser.add_argument(
        "-w", "--workers",
        type=int,
        default=None,
        help="Number of concurrent worker processes (defaults to CPU count).",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_false",
        dest="recursive",
        help="Do not scan subdirectories recursively.",
    )
    parser.add_argument(
        "--no-overwrite",
        action="store_false",
        dest="overwrite",
        help="Skip processing if output file already exists.",
    )
    parser.add_argument(
        "-q", "--quality",
        type=int,
        default=70,
        help="JPEG image quality (1-100).",
    )
    parser.add_argument(
        "--no-grayscale",
        action="store_false",
        dest="grayscale",
        help="Keep original image colors without converting to grayscale.",
    )
    parser.add_argument(
        "--no-contrast",
        action="store_false",
        dest="contrast_boost",
        help="Disable contrast enhancement.",
    )
    parser.add_argument(
        "--contrast-factor",
        type=float,
        default=1.5,
        help="Contrast boost multiplier factor.",
    )
    parser.add_argument(
        "--remove-fonts",
        action="store_true",
        default=None,
        help="Strip embedded font files to reduce size.",
    )
    parser.add_argument(
        "--keep-fonts",
        action="store_false",
        dest="remove_fonts",
        help="Keep embedded fonts intact.",
    )
    parser.add_argument(
        "--remove-css",
        action="store_true",
        dest="remove_unused_css",
        default=None,
        help="Strip unused CSS rules.",
    )
    parser.add_argument(
        "--keep-css",
        action="store_false",
        dest="remove_unused_css",
        help="Keep all CSS rules intact.",
    )
    parser.add_argument(
        "--clean-metadata",
        action="store_true",
        default=None,
        help="Strip store metadata and advertising tags.",
    )
    parser.add_argument(
        "--light-novel",
        action="store_true",
        dest="light_novel_mode",
        help="Enable Light Novel mode (rotate/split landscape double-page spreads).",
    )
    parser.add_argument(
        "--format",
        dest="filename_format",
        choices=sorted(list(FILENAME_FORMATS)),
        default="author-title",
        help="Output filename naming convention format.",
    )
    parser.add_argument(
        "--template",
        dest="filename_template",
        default="",
        help="Custom template when --format is custom (e.g., '{author} - {title}').",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show detailed optimization report for each file.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress normal progress output.",
    )

    return parser


def main():
    """Main CLI entrypoint."""
    parser = create_parser()
    args = parser.parse_args()

    # Collect overrides
    overrides = {
        'quality': args.quality,
        'contrast_factor': args.contrast_factor,
        'filename_format': args.filename_format,
        'filename_template': args.filename_template,
    }

    if args.grayscale is False:
        overrides['grayscale'] = False
    if args.contrast_boost is False:
        overrides['contrast_boost'] = False
    if args.remove_fonts is not None:
        overrides['remove_fonts'] = args.remove_fonts
    if args.remove_unused_css is not None:
        overrides['remove_unused_css'] = args.remove_unused_css
    if args.clean_metadata is not None:
        overrides['clean_metadata'] = args.clean_metadata
    if args.light_novel_mode:
        overrides['light_novel_mode'] = True

    success_cnt, fail_cnt, _ = batch_optimize(
        input_paths=args.paths,
        output_dir=args.output_dir,
        preset=args.preset,
        device=args.device,
        workers=args.workers,
        recursive=args.recursive,
        overwrite=args.overwrite,
        options_overrides=overrides,
        quiet=args.quiet,
        verbose=args.verbose,
    )

    if fail_cnt > 0 and success_cnt == 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
