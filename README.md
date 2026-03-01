# epubkit

A web-based EPUB optimizer for e-ink readers. Drop in any EPUB and get back a clean, optimized file ready for your device.

Originally built for the [Xteink X4](https://xteink.com/) (800x480 e-ink display, 4-level grayscale, SSD1677 controller, ESP32-C3) but works with any Xteink reader or e-ink device that supports EPUB.

## Processing pipeline

epubkit runs a 20-step pipeline on every EPUB:

| Step | What it does |
|------|-------------|
| 1 | **DRM check** — detects DRM-protected files and stops early with a clear message |
| 2 | **Extract** — unpacks the EPUB ZIP structure into a working directory |
| 3 | **Parse structure** — locates the OPF package file and parses the manifest |
| 4 | **Read metadata** — extracts title, author, series, language, cover reference |
| 5 | **Apply metadata edits** — overwrites title/author if the user edited them in the UI |
| 6 | **Find content files** — catalogs all XHTML, CSS, image, and font files in the EPUB |
| 7 | **Process images** — converts all images to baseline JPEG, resizes to 800x480 (max 1024x1024), applies 4-level grayscale quantization with Floyd-Steinberg dithering, autocontrast histogram stretching, and contrast boost. Light Novel mode rotates/splits landscape images |
| 8 | **Fix SVG covers** — unwraps SVG-wrapped cover images (common in Gutenberg/store EPUBs) |
| 9 | **Generate cover** — creates a title/author cover image if the book doesn't have one |
| 10 | **Update references** — rewrites all internal hrefs and srcs to match renamed image files |
| 11 | **Repair HTML + strip attributes** — fixes malformed XHTML with lxml recovery parser, strips unnecessary attributes (data-\*, aria-\*, role, tabindex, etc.) to reduce parsing overhead for the 380KB RAM device |
| 12 | **Remove unused CSS** — collects all used classes/IDs/elements across XHTML files, then strips CSS rules that don't match anything |
| 13 | **Remove embedded fonts** — deletes @font-face rules from CSS, removes font files (.ttf, .otf, .woff, .woff2), and cleans them from the OPF manifest |
| 14 | **Normalize whitespace** — strips excessive empty paragraphs/divs, adds CSS page-break-before to chapter headings (h1, h2) |
| 15 | **Text cleanup** — scans all text nodes (skipping script/style/pre/code) and fixes: double spaces, OCR ligature artifacts (fi/fl/ffi/ffl/ff), smart quotes → straight quotes, mojibake encoding errors, punctuation issues, Unicode NFC normalization |
| 16 | **Clean metadata** — strips store-specific tags (Calibre, iBooks, Kindle, Amazon, Google Play, Kobo) |
| 17 | **Fix TOC** — validates the Table of Contents, generates one from chapter headings if missing |
| 18 | **Clean OS artifacts** — removes .DS_Store, Thumbs.db, __MACOSX, desktop.ini, etc. |
| 19 | **Repackage** — rebuilds the EPUB ZIP with correct mimetype entry and deflate compression |
| 20 | **Output filename** — generates a clean `Author - Title.epub` filename from metadata |

## Usage

1. **Drop** one or more EPUB files onto the upload zone
2. **Edit** title/author if needed (auto-detected from metadata)
3. **Pick a preset**: Quick (images + text), Full (X4-optimized), or Custom
4. **Click Optimize** and watch real-time progress via SSE streaming
5. **Download** the optimized EPUB — ready to transfer to your reader

## Processing presets

| Preset | Images | Text | Fonts | CSS | Cover | Metadata | Best for |
|--------|--------|------|-------|-----|-------|----------|----------|
| Quick  | Yes    | Yes  | No    | No  | No    | No       | Fast image + text pass |
| Full   | Yes    | Yes  | Yes   | Yes | Yes   | Yes      | Complete X4 optimization |
| Custom | Pick   | Pick | Pick  | Pick| Pick  | Pick     | Fine-grained control |

## Xteink X4 specs

The optimizer is tuned for these hardware constraints:

| Spec | Value |
|------|-------|
| Display | 800x480 e-ink panel |
| Grayscale | 4 levels (SSD1677 controller): black, dark gray, light gray, white |
| Processor | ESP32-C3, 160MHz |
| RAM | 380KB usable |
| Max image | 1024x1024 pixels |
| Formats | EPUB, XTC, XTCH, Markdown, TXT |
| Storage | 32GB + microSD |

## Image processing details

- **Format**: All images converted to baseline JPEG (progressive breaks many e-ink readers)
- **Resize**: Fit within 800x480 screen, hard clamp at 1024x1024
- **Grayscale**: 4-level quantization matching SSD1677 palette (0, 85, 170, 255) with Floyd-Steinberg dithering
- **Contrast**: Auto-histogram stretching (`ImageOps.autocontrast`) followed by 1.5x contrast boost
- **Subsampling**: 4:2:0 for grayscale (all RGB channels identical, saves ~15-20%), 4:4:4 for color
- **Transparency**: Alpha composited onto white background
- **Light Novel mode**: Landscape images rotated 90°; double-page spreads (aspect > 1.8) split into two portrait pages

## Text cleanup details

Scans all XHTML text nodes (skipping `<script>`, `<style>`, `<pre>`, `<code>`):

- **Whitespace**: Multiple spaces/tabs → single space, removes spaces before punctuation
- **OCR ligatures**: fi (U+FB01), fl (U+FB02), ffi (U+FB03), ffl (U+FB04), ff (U+FB00) → plain ASCII
- **Smart quotes**: Typographic quotes/dashes → straight equivalents (configurable)
- **Mojibake**: Detects and repairs common UTF-8/Latin-1 double-encoding patterns
- **Punctuation**: 4+ dots → ellipsis, missing space after sentence-ending punctuation, duplicate commas
- **Unicode**: NFC normalization

## Tech stack

- **[FastAPI](https://fastapi.tiangolo.com/)** — async web framework
- **[Pillow](https://python-pillow.org/)** — image processing (4-level quantization, autocontrast)
- **[lxml](https://lxml.de/)** — XML/HTML parsing and repair
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
