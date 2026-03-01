"""
HTML cleaner for Xteink X4 EPUB Optimizer.
Handles: HTML repair, unused CSS removal, embedded font removal, whitespace/page-break normalization.
"""

import re
from pathlib import Path
from typing import Optional

from lxml import etree
import cssutils
import logging

# Suppress cssutils noisy logging
cssutils.log.setLevel(logging.CRITICAL)

XHTML_NS = 'http://www.w3.org/1999/xhtml'
FONT_EXTENSIONS = {'.ttf', '.otf', '.woff', '.woff2', '.eot'}
FONT_MEDIA_TYPES = {
    'application/font-woff', 'application/font-woff2',
    'font/woff', 'font/woff2', 'font/ttf', 'font/otf',
    'application/vnd.ms-opentype', 'application/x-font-ttf',
    'application/x-font-otf', 'application/font-sfnt',
}


def repair_html(html_bytes: bytes) -> bytes:
    """
    Repair malformed HTML/XHTML using lxml's recovery parser.
    Returns well-formed XHTML bytes.
    """
    # Try parsing as proper XML first
    try:
        tree = etree.fromstring(html_bytes)
        # Already valid - just re-serialize cleanly
        return etree.tostring(tree, encoding='unicode', pretty_print=True).encode('utf-8')
    except etree.XMLSyntaxError:
        pass

    # Fall back to HTML parser with recovery
    parser = etree.HTMLParser(recover=True, encoding='utf-8')
    try:
        tree = etree.fromstring(html_bytes, parser)
    except Exception:
        # Completely broken - return as-is
        return html_bytes

    if tree is None:
        return html_bytes

    # Re-serialize as XHTML
    result = etree.tostring(tree, encoding='unicode', pretty_print=True, method='html')
    return result.encode('utf-8')


def remove_unused_css(css_text: str, used_classes: set, used_ids: set, used_elements: set) -> tuple[str, int]:
    """
    Remove CSS rules that don't match any elements in the EPUB content.
    Returns (cleaned CSS text, count of removed rules).
    """
    try:
        sheet = cssutils.parseString(css_text)
    except Exception:
        return css_text, 0

    removed = 0
    rules_to_remove = []

    for rule in sheet:
        if rule.type != rule.STYLE_RULE:
            continue

        # Check if any selector in this rule matches used elements
        selector_text = rule.selectorText
        if not _selector_matches_used(selector_text, used_classes, used_ids, used_elements):
            rules_to_remove.append(rule)
            removed += 1

    for rule in rules_to_remove:
        sheet.deleteRule(rule)

    return sheet.cssText.decode('utf-8') if isinstance(sheet.cssText, bytes) else sheet.cssText, removed


def _selector_matches_used(selector_text: str, used_classes: set, used_ids: set, used_elements: set) -> bool:
    """Check if a CSS selector potentially matches any used classes, IDs, or elements."""
    # Always keep universal selectors, pseudo-elements, @-rules
    if selector_text.strip() in ('*', 'html', 'body'):
        return True

    # Split compound selectors
    selectors = re.split(r'\s*,\s*', selector_text)

    for sel in selectors:
        # Extract classes
        classes = re.findall(r'\.([a-zA-Z_][\w-]*)', sel)
        if classes and any(c in used_classes for c in classes):
            return True

        # Extract IDs
        ids = re.findall(r'#([a-zA-Z_][\w-]*)', sel)
        if ids and any(i in used_ids for i in ids):
            return True

        # Extract element names
        elements = re.findall(r'(?:^|[\s>+~])([a-zA-Z][\w-]*)', sel.strip())
        if elements and any(e.lower() in used_elements for e in elements):
            return True

        # Keep pseudo-class/element rules and attribute selectors
        if '::' in sel or ':' in sel or '[' in sel:
            return True

    return False


def collect_used_selectors(xhtml_bytes: bytes) -> tuple[set, set, set]:
    """
    Parse XHTML and collect all used CSS classes, IDs, and element names.
    Returns (classes, ids, elements).
    """
    classes = set()
    ids = set()
    elements = set()

    try:
        parser = etree.HTMLParser(recover=True)
        tree = etree.fromstring(xhtml_bytes, parser)
    except Exception:
        return classes, ids, elements

    for el in tree.iter():
        # Element name (strip namespace)
        tag = el.tag
        if isinstance(tag, str):
            tag = tag.split('}')[-1] if '}' in tag else tag
            elements.add(tag.lower())

        # Classes
        class_attr = el.get('class', '')
        if class_attr:
            for cls in class_attr.split():
                classes.add(cls)

        # IDs
        id_attr = el.get('id', '')
        if id_attr:
            ids.add(id_attr)

    return classes, ids, elements


def remove_embedded_fonts_from_css(css_text: str) -> tuple[str, int]:
    """
    Remove @font-face rules from CSS.
    Returns (cleaned CSS, count of removed @font-face rules).
    """
    try:
        sheet = cssutils.parseString(css_text)
    except Exception:
        return css_text, 0

    removed = 0
    rules_to_remove = []

    for rule in sheet:
        if rule.type == rule.FONT_FACE_RULE:
            rules_to_remove.append(rule)
            removed += 1

    for rule in rules_to_remove:
        sheet.deleteRule(rule)

    # Also remove font-family declarations that reference custom fonts
    result = sheet.cssText.decode('utf-8') if isinstance(sheet.cssText, bytes) else sheet.cssText
    return result, removed


def find_font_files(file_list: list[str]) -> list[str]:
    """Find all font files in the EPUB by extension and media type."""
    fonts = []
    for filepath in file_list:
        ext = Path(filepath).suffix.lower()
        if ext in FONT_EXTENSIONS:
            fonts.append(filepath)
    return fonts


def is_font_media_type(media_type: str) -> bool:
    """Check if a media type string indicates a font file."""
    return media_type.lower() in FONT_MEDIA_TYPES


def normalize_whitespace(xhtml_bytes: bytes) -> tuple[bytes, int]:
    """
    Strip excessive blank paragraphs and empty divs from XHTML content.
    Returns (cleaned bytes, count of removed elements).
    """
    try:
        tree = etree.fromstring(xhtml_bytes)
    except etree.XMLSyntaxError:
        parser = etree.HTMLParser(recover=True)
        tree = etree.fromstring(xhtml_bytes, parser)
        if tree is None:
            return xhtml_bytes, 0

    removed = 0
    ns = XHTML_NS

    # Find consecutive empty paragraphs (more than 2 in a row)
    empty_streak = []
    for el in tree.iter():
        tag = el.tag.split('}')[-1] if '}' in str(el.tag) else str(el.tag)

        if tag in ('p', 'div'):
            text_content = (el.text or '').strip()
            has_children = len(el) > 0

            # Check if truly empty (no text, no meaningful children)
            if not text_content and not has_children:
                tail = (el.tail or '').strip()
                empty_streak.append(el)
            else:
                # Reset streak, remove excess empties (keep max 1)
                if len(empty_streak) > 1:
                    for empty_el in empty_streak[1:]:
                        parent = empty_el.getparent()
                        if parent is not None:
                            # Preserve tail text
                            if empty_el.tail:
                                prev = empty_el.getprevious()
                                if prev is not None:
                                    prev.tail = (prev.tail or '') + empty_el.tail
                                else:
                                    parent.text = (parent.text or '') + empty_el.tail
                            parent.remove(empty_el)
                            removed += 1
                empty_streak = []

    # Handle remaining streak
    if len(empty_streak) > 1:
        for empty_el in empty_streak[1:]:
            parent = empty_el.getparent()
            if parent is not None:
                if empty_el.tail:
                    prev = empty_el.getprevious()
                    if prev is not None:
                        prev.tail = (prev.tail or '') + empty_el.tail
                    else:
                        parent.text = (parent.text or '') + empty_el.tail
                parent.remove(empty_el)
                removed += 1

    result = etree.tostring(tree, encoding='unicode', pretty_print=True)
    return result.encode('utf-8'), removed


def add_chapter_page_breaks(xhtml_bytes: bytes) -> bytes:
    """
    Add CSS page-break-before to chapter headings (h1, h2) if not already present.
    This ensures proper chapter separation on e-readers.
    """
    try:
        tree = etree.fromstring(xhtml_bytes)
    except etree.XMLSyntaxError:
        return xhtml_bytes

    # Find <head> to inject CSS if needed
    head = tree.find('.//{http://www.w3.org/1999/xhtml}head')
    if head is None:
        head = tree.find('.//head')
    if head is None:
        return xhtml_bytes

    # Check if page-break CSS already exists
    existing_styles = head.findall('.//{http://www.w3.org/1999/xhtml}style')
    if not existing_styles:
        existing_styles = head.findall('.//style')

    has_page_break = False
    for style in existing_styles:
        if style.text and 'page-break-before' in style.text:
            has_page_break = True
            break

    if not has_page_break:
        # Add page-break style
        ns = tree.tag.split('}')[0] + '}' if '}' in tree.tag else ''
        style_el = etree.SubElement(head, f'{ns}style', type='text/css')
        style_el.text = '\nh1, h2 { page-break-before: always; }\n'

    return etree.tostring(tree, encoding='unicode', pretty_print=True).encode('utf-8')
