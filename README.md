# epubkit

A web-based EPUB optimizer for e-ink readers. Drop in any EPUB and get back a clean, optimized file ready for your device.

Originally built for the [Xteink X4](https://xteink.com/) (800x480 e-ink display, 4-level grayscale, SSD1677 controller, ESP32-C3) but works with any Xteink reader or e-ink device that supports EPUB.

## What it does

epubkit runs a multi-step processing pipeline on your EPUB files:

**Images**
- Converts all images to baseline JPEG (progressive JPEGs break many e-ink readers)
- Resizes to fit your screen (default 800x480 for Xteink X4, max 1024x1024)
- 4-level grayscale quantization with Floyd-Steinberg dithering (matches SSD1677's black/dark gray/light gray/white)
- Auto-contrast histogram stretching + contrast boost for e-ink readability
- Unwraps SVG cover wrappers (common in Gutenberg/store EPUBs)
- Generates a cover image if the book doesn't have one
- Light Novel mode: rotates and splits landscape images for vertical reading

**Text Cleanup**
- Fixes double/multiple spaces and whitespace issues
- Repairs OCR ligature artifacts (fi, fl, ffi, ffl, ff)
- Normalizes smart quotes and typographic dashes to ASCII
- Detects and fixes mojibake (UTF-8/Latin-1 misencoding)
- Cleans up punctuation (excess dots, missing spaces after sentences)
- Unicode NFC normalization

**HTML & CSS**
- Strips embedded fonts (e-ink readers use their own)
- Removes unused CSS rules
- Strips unnecessary HTML attributes (data-*, aria-*, role, tabindex, etc.) to reduce parsing overhead for the 380KB RAM device
- Removes empty whitespace elements
- Repairs malformed HTML/XHTML
- Adds chapter page breaks
- Cleans OS artifacts (`.DS_Store`, `Thumbs.db`, etc.)

**Metadata**
- Strips store-specific metadata (Calibre, iBooks, Kindle, Amazon tags)
- Editable title/author fields before processing
- Smart output filename: `Author - Title.epub`

**Structure**
- Validates and repairs Table of Contents
- Generates TOC from chapter headings if missing
- Updates all internal references when files are renamed

## Usage

1. **Drop** one or more EPUB files onto the upload zone
2. **Edit** title/author if needed (auto-detected from metadata)
3. **Pick a preset**: Quick (images + text), Full (X4-optimized), or Custom
4. **Click Optimize** and watch real-time progress
5. **Download** the optimized EPUB — ready to transfer to your reader

## Processing presets

| Preset | Images | Text | Fonts | CSS | Cover | Metadata | Best for |
|--------|--------|------|-------|-----|-------|----------|----------|
| Quick  | Yes    | Yes  | No    | No  | No    | No       | Fast image + text pass |
| Full   | Yes    | Yes  | Yes   | Yes | Yes   | Yes      | Complete X4 optimization |
| Custom | Pick   | Pick | Pick  | Pick| Pick  | Pick     | Fine-grained control |

## Tech stack

- **[FastAPI](https://fastapi.tiangolo.com/)** — async web framework
- **[Pillow](https://python-pillow.org/)** — image processing (4-level quantization, autocontrast)
- **[lxml](https://lxml.de/)** — XML/HTML parsing
- **[cssutils](https://cssutils.readthedocs.io/)** — CSS parsing and cleanup
- **Server-Sent Events** — real-time progress streaming

## DRM note

epubkit cannot process DRM-protected EPUBs. It will detect DRM and let you know. You'll need to remove DRM first using tools like [DeDRM](https://github.com/noDRM/DeDRM_tools) with Calibre.

## Acknowledgements

Inspired by and built on ideas from:

- [zgredex/baseline_jpg_converter](https://github.com/zgredex/baseline_jpg_converter) — Calibre plugin for baseline JPEG conversion
- [CrossPoint Reader PR #1224](https://github.com/nicnocquee/CrossPoint-Reader/pull/1224) — in-browser EPUB converter with Light Novel mode
- [kxrz/calibre_workflow](https://github.com/kxrz/calibre_workflow) — Calibre plugin for HTML repair and CSS cleanup
- [bigbag/papyrix-reader](https://github.com/bigbag/papyrix-reader) — Xteink device specifications and documentation

## About

Built by [@b1rdmania](https://github.com/b1rdmania). Made because existing tools required too many steps — Calibre plugins, CLI scripts, manual image conversion. epubkit does it all in one pass through a simple web interface.

## License

MIT
