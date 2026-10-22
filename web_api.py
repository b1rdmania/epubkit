"""
Browser entry points for epubkit.
The page runs this module in Pyodide inside a Web Worker. Files stay on the
reader's device: the worker writes them to Pyodide's in-memory filesystem,
calls these functions, and hands the result back as bytes.
"""

import os
import zipfile

from epub_processor import process_epub, extract_epub_metadata, ProcessingOptions
from image_processor import DEVICE_PROFILES
from metadata_handler import FILENAME_FORMATS, format_filename

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB


def inspect_upload(path: str, filename: str, file_size: int) -> dict:
    """Check one EPUB and read its metadata for the preview card."""
    result = {"filename": filename, "file_size": file_size}

    if not filename.lower().endswith('.epub'):
        result["error"] = "Not an EPUB file"
        return result
    if filename.lower().endswith('.kepub.epub'):
        result["error"] = "Kobo EPUB files (.kepub.epub) are not supported"
        return result
    if file_size > MAX_FILE_SIZE:
        result["error"] = f"File too large (max {MAX_FILE_SIZE // (1024*1024)}MB)"
        return result

    try:
        metadata = extract_epub_metadata(path)
    except Exception as e:
        metadata = {"title": "", "author": "", "error": str(e)}

    result["metadata"] = metadata
    result["error"] = metadata.get("error")
    return result


def validate_options(params: dict) -> str:
    """Return an error message for bad options, or an empty string."""
    device = params.get("device", "x4")
    filename_format = params.get("filename_format", "author-title")
    filename_template = params.get("filename_template", "")

    if device not in DEVICE_PROFILES:
        allowed = ", ".join(f"'{d}'" for d in DEVICE_PROFILES)
        return f"Unknown device (expected {allowed})"
    if filename_format not in FILENAME_FORMATS:
        return "Unknown filename format"
    if filename_format == "custom" and not filename_template.strip():
        return "Custom filename template cannot be empty"
    if len(filename_template) > 200:
        return "Filename template is too long"
    if filename_format == "custom":
        try:
            format_filename(
                "title",
                "author",
                filename_format="custom",
                template=filename_template,
                original_filename="original.epub",
                year="2026",
            )
        except ValueError as error:
            return str(error)
    return ""


def run_process(input_path: str, output_path: str, filename: str,
                params: dict, progress_callback) -> dict:
    """Optimise one EPUB. Returns the report the results card shows."""
    error = validate_options(params)
    if error:
        return {"success": False, "error": error}

    options = ProcessingOptions(
        device=params.get("device", "x4"),
        grayscale=bool(params.get("grayscale", True)),
        contrast_boost=bool(params.get("contrast", True)),
        quality=int(params.get("quality", 70)),
        remove_fonts=bool(params.get("remove_fonts", True)),
        remove_unused_css=bool(params.get("remove_css", True)),
        light_novel_mode=bool(params.get("light_novel", False)),
        generate_missing_cover=bool(params.get("generate_cover", True)),
        clean_metadata=bool(params.get("clean_metadata", True)),
        text_cleanup=bool(params.get("text_cleanup", True)),
        filename_format=params.get("filename_format", "author-title"),
        filename_template=params.get("filename_template", ""),
        original_filename=filename,
    )

    edit_title = params.get("edit_title", "")
    edit_author = params.get("edit_author", "")
    if edit_title or edit_author:
        options.metadata_edits = {}
        if edit_title:
            options.metadata_edits['title'] = edit_title
        if edit_author:
            options.metadata_edits['author'] = edit_author

    report = process_epub(input_path, output_path, options, progress_callback)

    return {
        "success": report.success,
        "error": report.error,
        "original_size": report.original_size,
        "optimized_size": report.optimized_size,
        "output_filename": report.output_filename,
        "summary": report.summary(),
        "images_converted": report.images_converted,
        "images_total": report.images_total,
        "fonts_removed": report.fonts_removed,
        "css_rules_removed": report.css_rules_removed,
        "svg_covers_fixed": report.svg_covers_fixed,
        "toc_status": report.toc_status,
        "metadata_items_stripped": report.metadata_items_stripped,
        "cover_generated": report.cover_generated,
        "attrs_stripped": report.attrs_stripped,
        "text_fixes_total": report.text_fixes_total,
        "text_cleanup_summary": report.text_cleanup_summary,
    }


def build_zip(entries: list, zip_path: str) -> None:
    """Write [(output_path, filename), ...] into one ZIP for Download all."""
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for output_path, filename in entries:
            if os.path.exists(output_path):
                zf.write(output_path, filename)
