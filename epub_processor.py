"""
Main EPUB processing pipeline for XTelnk X4 Optimizer.
Orchestrates all processing steps and generates validation reports.
"""

import os
import shutil
import tempfile
from pathlib import Path
from dataclasses import dataclass, field
from typing import Callable, Optional

from lxml import etree

from image_processor import (
    ImageOptions, process_image, should_process, generate_cover_image
)
from metadata_handler import (
    extract_metadata, update_metadata, strip_store_metadata, format_filename
)
from html_cleaner import (
    repair_html, remove_unused_css, collect_used_selectors,
    remove_embedded_fonts_from_css, find_font_files, normalize_whitespace,
    add_chapter_page_breaks
)
from epub_packager import (
    extract_epub, package_epub, remove_os_artifacts, has_drm, find_opf_path
)
from epub_structure import (
    build_rename_map, update_opf, update_opf_remove_fonts,
    update_xhtml_references, update_css_references,
    fix_svg_covers, fix_toc, find_content_files, add_image_to_opf
)


@dataclass
class ProcessingOptions:
    """All user-configurable processing options."""
    grayscale: bool = True
    contrast_boost: bool = True
    contrast_factor: float = 1.3
    quality: int = 70
    remove_fonts: bool = True
    remove_unused_css: bool = True
    light_novel_mode: bool = False
    light_novel_rotate_left: bool = True
    generate_missing_cover: bool = True
    clean_metadata: bool = True
    # Metadata edits (applied if non-empty)
    metadata_edits: dict = field(default_factory=dict)


@dataclass
class ProcessingReport:
    """Validation report of everything that was done."""
    success: bool = True
    error: str = ''
    original_size: int = 0
    optimized_size: int = 0
    output_filename: str = ''
    # Counts
    images_converted: int = 0
    images_total: int = 0
    image_formats: dict = field(default_factory=dict)  # e.g. {"PNG→JPEG": 5, "baseline JPEG": 3}
    fonts_removed: int = 0
    css_rules_removed: int = 0
    svg_covers_fixed: int = 0
    toc_status: str = ''
    metadata_items_stripped: int = 0
    whitespace_cleaned: int = 0
    os_artifacts_removed: int = 0
    cover_generated: bool = False
    # Details
    image_details: list = field(default_factory=list)

    def summary(self) -> str:
        """Generate a human-readable summary of all changes."""
        parts = []

        if self.images_converted > 0:
            fmt_parts = [f"{v} {k}" for k, v in self.image_formats.items()]
            parts.append(f"Converted {self.images_converted}/{self.images_total} images ({', '.join(fmt_parts)})")

        if self.fonts_removed > 0:
            parts.append(f"Removed {self.fonts_removed} embedded fonts")

        if self.css_rules_removed > 0:
            parts.append(f"Stripped {self.css_rules_removed} unused CSS rules")

        if self.svg_covers_fixed > 0:
            parts.append(f"Fixed {self.svg_covers_fixed} SVG cover wrappers")

        if self.cover_generated:
            parts.append("Generated missing cover image")

        if self.toc_status:
            parts.append(f"TOC: {self.toc_status}")

        if self.metadata_items_stripped > 0:
            parts.append(f"Stripped {self.metadata_items_stripped} store metadata entries")

        if self.whitespace_cleaned > 0:
            parts.append(f"Cleaned {self.whitespace_cleaned} empty elements")

        if self.os_artifacts_removed > 0:
            parts.append(f"Removed {self.os_artifacts_removed} OS artifacts")

        if self.original_size > 0 and self.optimized_size > 0:
            reduction = (1 - self.optimized_size / self.original_size) * 100
            parts.append(f"Size: {_fmt_size(self.original_size)} → {_fmt_size(self.optimized_size)} ({reduction:.1f}% reduction)")

        return "; ".join(parts) if parts else "No changes needed"


ProgressCallback = Callable[[int, str], None]


def process_epub(input_path: str, output_path: str,
                 options: ProcessingOptions = None,
                 progress: ProgressCallback = None) -> ProcessingReport:
    """
    Main processing pipeline. Takes an EPUB, optimizes it, writes output.
    """
    if options is None:
        options = ProcessingOptions()

    report = ProcessingReport()
    report.original_size = os.path.getsize(input_path)

    def _progress(pct: int, msg: str):
        if progress:
            progress(pct, msg)

    # Create temp working directory
    work_dir = tempfile.mkdtemp(prefix='epub_opt_')

    try:
        # Step 1: Check for DRM
        _progress(2, "Checking for DRM...")
        if has_drm(input_path):
            report.success = False
            report.error = "This EPUB is DRM-protected. Please remove DRM first (e.g. using DeDRM with Calibre)."
            return report

        # Step 2: Extract
        _progress(5, "Extracting EPUB...")
        extract_epub(input_path, work_dir)

        # Step 3: Find OPF
        _progress(8, "Parsing structure...")
        opf_rel_path = find_opf_path(work_dir)
        opf_path = os.path.join(work_dir, opf_rel_path)
        opf_tree = etree.parse(opf_path)

        # Step 4: Extract metadata
        _progress(10, "Reading metadata...")
        metadata = extract_metadata(opf_tree)

        # Step 5: Apply metadata edits
        if options.metadata_edits:
            update_metadata(opf_tree, options.metadata_edits)
            opf_tree.write(opf_path, xml_declaration=True, encoding='utf-8', pretty_print=True)
            # Re-read metadata for filename generation
            opf_tree = etree.parse(opf_path)
            metadata = extract_metadata(opf_tree)

        # Step 6: Find all content files
        content_files = find_content_files(work_dir, opf_path)

        # Step 7: Process images (20-60%)
        _progress(15, "Processing images...")
        image_options = ImageOptions(
            grayscale=options.grayscale,
            contrast_boost=options.contrast_boost,
            contrast_factor=options.contrast_factor,
            quality=options.quality,
            light_novel_mode=options.light_novel_mode,
            light_novel_rotate_left=options.light_novel_rotate_left,
        )

        image_files = content_files['images']
        report.images_total = len(image_files)
        processed_images = {}  # old_rel_path -> new_filename

        for i, img_path in enumerate(image_files):
            pct = 15 + int(45 * (i / max(len(image_files), 1)))
            _progress(pct, f"Processing image {i + 1}/{len(image_files)}...")

            if not os.path.exists(img_path):
                continue

            with open(img_path, 'rb') as f:
                img_bytes = f.read()

            if not should_process(img_path):
                continue

            results = process_image(img_bytes, Path(img_path).name, image_options)

            for j, result in enumerate(results):
                if result.was_converted:
                    report.images_converted += 1

                    # Track format changes
                    detail_key = result.details.split(',')[0].strip() if result.details else 'processed'
                    report.image_formats[detail_key] = report.image_formats.get(detail_key, 0) + 1

                    # Write new file
                    new_path = Path(img_path).parent / result.new_filename
                    with open(str(new_path), 'wb') as f:
                        f.write(result.output_bytes)

                    # Remove old file if name changed
                    if result.new_filename != Path(img_path).name:
                        if os.path.exists(img_path):
                            os.unlink(img_path)

                    # Track for reference updates
                    old_rel = os.path.relpath(img_path, Path(opf_path).parent)
                    processed_images[old_rel] = result.new_filename

                    report.image_details.append(result.details)

        # Step 8: Fix SVG covers (62%)
        _progress(62, "Fixing SVG covers...")
        report.svg_covers_fixed = fix_svg_covers(work_dir, opf_path)

        # Step 9: Generate missing cover (64%)
        if options.generate_missing_cover:
            _progress(64, "Checking cover...")
            opf_tree = etree.parse(opf_path)
            meta = extract_metadata(opf_tree)
            if not meta['cover_href']:
                title = options.metadata_edits.get('title', meta['title']) or 'Untitled'
                author = options.metadata_edits.get('author', meta['author']) or ''
                cover_bytes = generate_cover_image(title, author)
                opf_dir = str(Path(opf_path).parent)
                # Determine images directory
                images_dir = os.path.join(opf_dir, 'images')
                if not os.path.exists(images_dir):
                    images_dir = os.path.join(opf_dir, 'Images')
                    if not os.path.exists(images_dir):
                        images_dir = os.path.join(opf_dir, 'images')
                        os.makedirs(images_dir, exist_ok=True)

                cover_path = os.path.join(images_dir, 'cover_generated.jpg')
                with open(cover_path, 'wb') as f:
                    f.write(cover_bytes)

                # Add to OPF
                cover_href = os.path.relpath(cover_path, opf_dir)
                add_image_to_opf(opf_path, cover_href, 'cover-image-generated')
                report.cover_generated = True

        # Step 10: Update references (68%)
        _progress(68, "Updating references...")
        rename_map = build_rename_map(
            work_dir,
            {k: v for k, v in processed_images.items()}
        )
        if rename_map:
            update_opf(opf_path, rename_map)
            for xhtml_path in content_files['xhtml']:
                if os.path.exists(xhtml_path):
                    update_xhtml_references(xhtml_path, rename_map)
            for css_path in content_files['css']:
                if os.path.exists(css_path):
                    update_css_references(css_path, rename_map)

        # Step 11: Repair HTML (72%)
        _progress(72, "Repairing HTML...")
        for xhtml_path in content_files['xhtml']:
            if os.path.exists(xhtml_path):
                with open(xhtml_path, 'rb') as f:
                    html_bytes = f.read()
                repaired = repair_html(html_bytes)
                with open(xhtml_path, 'wb') as f:
                    f.write(repaired)

        # Step 12: Remove unused CSS (76%)
        if options.remove_unused_css:
            _progress(76, "Removing unused CSS...")
            # Collect all used selectors from XHTML files
            all_classes = set()
            all_ids = set()
            all_elements = set()
            for xhtml_path in content_files['xhtml']:
                if os.path.exists(xhtml_path):
                    with open(xhtml_path, 'rb') as f:
                        classes, ids, elements = collect_used_selectors(f.read())
                        all_classes.update(classes)
                        all_ids.update(ids)
                        all_elements.update(elements)

            for css_path in content_files['css']:
                if os.path.exists(css_path):
                    with open(css_path, 'r', encoding='utf-8', errors='ignore') as f:
                        css_text = f.read()
                    cleaned, removed = remove_unused_css(css_text, all_classes, all_ids, all_elements)
                    report.css_rules_removed += removed
                    if removed > 0:
                        with open(css_path, 'w', encoding='utf-8') as f:
                            f.write(cleaned)

        # Step 13: Remove embedded fonts (80%)
        if options.remove_fonts:
            _progress(80, "Removing embedded fonts...")
            font_files = content_files['fonts']

            if font_files:
                # Remove @font-face from CSS
                for css_path in content_files['css']:
                    if os.path.exists(css_path):
                        with open(css_path, 'r', encoding='utf-8', errors='ignore') as f:
                            css_text = f.read()
                        cleaned, removed = remove_embedded_fonts_from_css(css_text)
                        report.fonts_removed += removed
                        if removed > 0:
                            with open(css_path, 'w', encoding='utf-8') as f:
                                f.write(cleaned)

                # Remove font files
                for font_path in font_files:
                    if os.path.exists(font_path):
                        os.unlink(font_path)
                        report.fonts_removed += 1

                # Remove from OPF manifest
                update_opf_remove_fonts(opf_path, font_files)

        # Step 14: Normalize whitespace and page breaks (84%)
        _progress(84, "Normalizing content...")
        for xhtml_path in content_files['xhtml']:
            if os.path.exists(xhtml_path):
                with open(xhtml_path, 'rb') as f:
                    html_bytes = f.read()
                cleaned, removed = normalize_whitespace(html_bytes)
                report.whitespace_cleaned += removed
                cleaned = add_chapter_page_breaks(cleaned)
                with open(xhtml_path, 'wb') as f:
                    f.write(cleaned)

        # Step 15: Clean metadata (87%)
        if options.clean_metadata:
            _progress(87, "Cleaning metadata...")
            opf_tree = etree.parse(opf_path)
            report.metadata_items_stripped = strip_store_metadata(opf_tree)
            if report.metadata_items_stripped > 0:
                opf_tree.write(opf_path, xml_declaration=True, encoding='utf-8', pretty_print=True)

        # Step 16: Fix TOC (90%)
        _progress(90, "Checking TOC...")
        toc_fixed, toc_msg = fix_toc(work_dir, opf_path)
        report.toc_status = toc_msg

        # Step 17: Clean OS artifacts (93%)
        _progress(93, "Cleaning up...")
        report.os_artifacts_removed = remove_os_artifacts(work_dir)

        # Step 18: Repackage (95%)
        _progress(95, "Repackaging EPUB...")
        package_epub(work_dir, output_path)

        # Step 19: Generate output filename
        opf_tree = etree.parse(opf_path)
        final_metadata = extract_metadata(opf_tree)
        title = options.metadata_edits.get('title', final_metadata['title']) or final_metadata['title']
        author = options.metadata_edits.get('author', final_metadata['author']) or final_metadata['author']
        report.output_filename = format_filename(title, author)

        # Done
        report.optimized_size = os.path.getsize(output_path)
        report.success = True
        _progress(100, "Complete")

    except Exception as e:
        report.success = False
        report.error = str(e)
        _progress(100, f"Error: {e}")

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    return report


def extract_epub_metadata(epub_path: str) -> dict:
    """
    Quick metadata extraction without full processing.
    Used for the preview step in the web UI.
    Returns: {title, author, series, series_index, language, cover_id, cover_href, cover_data, has_drm}
    """
    result = {
        'title': '',
        'author': '',
        'series': '',
        'series_index': '',
        'language': '',
        'cover_data': None,  # Base64-encoded cover image
        'has_drm': False,
        'is_kepub': Path(epub_path).name.lower().endswith('.kepub.epub'),
    }

    if result['is_kepub']:
        return result

    result['has_drm'] = has_drm(epub_path)
    if result['has_drm']:
        return result

    work_dir = tempfile.mkdtemp(prefix='epub_meta_')
    try:
        extract_epub(epub_path, work_dir)
        opf_rel = find_opf_path(work_dir)
        opf_path = os.path.join(work_dir, opf_rel)
        opf_tree = etree.parse(opf_path)

        metadata = extract_metadata(opf_tree)
        result.update(metadata)

        # Extract cover image data for preview
        if metadata['cover_href']:
            opf_dir = str(Path(opf_path).parent)
            cover_path = os.path.join(opf_dir, metadata['cover_href'])
            if os.path.exists(cover_path):
                import base64
                with open(cover_path, 'rb') as f:
                    cover_bytes = f.read()
                result['cover_data'] = base64.b64encode(cover_bytes).decode('ascii')

    except Exception:
        pass
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    return result


def _fmt_size(size_bytes: int) -> str:
    """Format bytes to human-readable string."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"
