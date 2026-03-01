"""
Text cleaner for Xteink X4 EPUB Optimizer.
Handles: whitespace normalization, OCR artifact repair, encoding fixes,
Unicode normalization, punctuation cleanup.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from lxml import etree


@dataclass
class TextCleanReport:
    double_spaces_fixed: int = 0
    ocr_ligatures_fixed: int = 0
    smart_quotes_normalized: int = 0
    encoding_issues_fixed: int = 0
    unicode_normalized: int = 0
    punctuation_fixed: int = 0
    total_fixes: int = 0

    def summary(self) -> str:
        parts = []
        if self.double_spaces_fixed:
            parts.append(f"{self.double_spaces_fixed} extra spaces")
        if self.ocr_ligatures_fixed:
            parts.append(f"{self.ocr_ligatures_fixed} OCR artifacts")
        if self.smart_quotes_normalized:
            parts.append(f"{self.smart_quotes_normalized} quotes normalized")
        if self.encoding_issues_fixed:
            parts.append(f"{self.encoding_issues_fixed} encoding fixes")
        if self.punctuation_fixed:
            parts.append(f"{self.punctuation_fixed} punctuation fixes")
        if self.unicode_normalized:
            parts.append(f"{self.unicode_normalized} unicode fixes")
        return ", ".join(parts) if parts else "no text issues found"

    def merge(self, other: 'TextCleanReport'):
        """Merge counts from another report into this one."""
        self.double_spaces_fixed += other.double_spaces_fixed
        self.ocr_ligatures_fixed += other.ocr_ligatures_fixed
        self.smart_quotes_normalized += other.smart_quotes_normalized
        self.encoding_issues_fixed += other.encoding_issues_fixed
        self.unicode_normalized += other.unicode_normalized
        self.punctuation_fixed += other.punctuation_fixed
        self.total_fixes += other.total_fixes


@dataclass
class TextCleanOptions:
    fix_whitespace: bool = True
    fix_ocr: bool = True
    normalize_quotes: bool = True
    fix_encoding: bool = True
    fix_punctuation: bool = True
    normalize_unicode: bool = True


# Common OCR ligature/artifact mappings
OCR_LIGATURES = {
    '\ufb01': 'fi',
    '\ufb02': 'fl',
    '\ufb03': 'ffi',
    '\ufb04': 'ffl',
    '\ufb00': 'ff',
}

SMART_QUOTE_MAP = {
    '\u2018': "'",   # left single quote
    '\u2019': "'",   # right single quote
    '\u201c': '"',   # left double quote
    '\u201d': '"',   # right double quote
    '\u2014': '--',  # em dash
    '\u2013': '-',   # en dash
    '\u2026': '...', # ellipsis character
    '\u00a0': ' ',   # non-breaking space
    '\u201a': ',',   # low-9 quote (often misread comma)
}

# Common mojibake patterns (UTF-8 bytes misinterpreted as Latin-1)
MOJIBAKE_PATTERNS = {
    '\u00c3\u00a9': '\u00e9',  # e-acute
    '\u00c3\u00a8': '\u00e8',  # e-grave
    '\u00c3\u00ab': '\u00eb',  # e-umlaut
    '\u00c3\u00a0': '\u00e0',  # a-grave
    '\u00c3\u00bc': '\u00fc',  # u-umlaut
    '\u00c3\u00b1': '\u00f1',  # n-tilde
    '\u00c3\u00a7': '\u00e7',  # c-cedilla
    '\u00c3\u00b6': '\u00f6',  # o-umlaut
    '\u00c3\u00a4': '\u00e4',  # a-umlaut
    '\u00c3\u00bc': '\u00fc',  # u-umlaut
    '\u00c2\u00a3': '\u00a3',  # pound sign
    '\u00c2\u00bb': '\u00bb',  # right guillemet
    '\u00c2\u00ab': '\u00ab',  # left guillemet
    '\u00c2\u00b0': '\u00b0',  # degree sign
}

# Tags whose text content should not be modified
SKIP_TAGS = frozenset({'script', 'style', 'pre', 'code', 'kbd', 'samp'})


def _fix_whitespace(text: str) -> tuple[str, int]:
    """Fix multiple consecutive spaces, tabs within text."""
    count = 0
    # Multiple spaces/tabs to single space
    result, n = re.subn(r'[ \t]{2,}', ' ', text)
    count += n
    # Space before punctuation (but not ellipsis)
    result, n = re.subn(r'\s+([.,;:!?])', r'\1', result)
    count += n
    return result, count


def _fix_ocr_artifacts(text: str, normalize_quotes: bool = True) -> tuple[str, int, int]:
    """Fix OCR ligature artifacts and optionally normalize smart quotes."""
    lig_count = 0
    quote_count = 0

    # Fix ligatures
    for old, new in OCR_LIGATURES.items():
        if old in text:
            n = text.count(old)
            text = text.replace(old, new)
            lig_count += n

    # Normalize smart quotes/dashes
    if normalize_quotes:
        for old, new in SMART_QUOTE_MAP.items():
            if old in text:
                n = text.count(old)
                text = text.replace(old, new)
                quote_count += n

    return text, lig_count, quote_count


def _fix_mojibake(text: str) -> tuple[str, int]:
    """Detect and repair common mojibake patterns."""
    count = 0
    for broken, fixed in MOJIBAKE_PATTERNS.items():
        if broken in text:
            n = text.count(broken)
            text = text.replace(broken, fixed)
            count += n
    return text, count


def _fix_punctuation(text: str) -> tuple[str, int]:
    """Fix common punctuation issues."""
    count = 0
    # 4+ dots → ellipsis
    result, n = re.subn(r'\.{4,}', '...', text)
    count += n
    # Missing space after sentence-ending punctuation before uppercase letter
    result, n = re.subn(r'([.!?])([A-Z])', r'\1 \2', result)
    count += n
    # Multiple consecutive commas
    result, n = re.subn(r',{2,}', ',', result)
    count += n
    # Multiple consecutive exclamation/question marks (more than 3)
    result, n = re.subn(r'([!?]){4,}', r'\1\1\1', result)
    count += n
    return result, count


def _get_local_tag(tag: str) -> str:
    """Get local tag name, stripping namespace."""
    if '}' in tag:
        return tag.split('}')[-1]
    return tag


def clean_text_content(xhtml_bytes: bytes, options: TextCleanOptions = None) -> tuple[bytes, TextCleanReport]:
    """
    Clean text content within XHTML, preserving markup structure.
    Processes el.text and el.tail for all elements except script/style/pre/code.

    Returns (cleaned_bytes, report).
    """
    if options is None:
        options = TextCleanOptions()

    report = TextCleanReport()

    try:
        tree = etree.fromstring(xhtml_bytes)
    except etree.XMLSyntaxError:
        parser = etree.HTMLParser(recover=True)
        tree = etree.fromstring(xhtml_bytes, parser)
        if tree is None:
            return xhtml_bytes, report

    def _process_text(text: str) -> str:
        """Apply all enabled text fixes to a string."""
        nonlocal report
        original = text

        if options.fix_whitespace:
            text, n = _fix_whitespace(text)
            report.double_spaces_fixed += n

        if options.fix_ocr:
            text, lig_n, quote_n = _fix_ocr_artifacts(text, options.normalize_quotes)
            report.ocr_ligatures_fixed += lig_n
            report.smart_quotes_normalized += quote_n

        if options.fix_encoding:
            text, n = _fix_mojibake(text)
            report.encoding_issues_fixed += n

        if options.fix_punctuation:
            text, n = _fix_punctuation(text)
            report.punctuation_fixed += n

        if options.normalize_unicode:
            normalized = unicodedata.normalize('NFC', text)
            if normalized != text:
                report.unicode_normalized += 1
            text = normalized

        return text

    # Walk all elements
    for el in tree.iter():
        if not isinstance(el.tag, str):
            continue

        local_tag = _get_local_tag(el.tag)
        if local_tag in SKIP_TAGS:
            continue

        # Process el.text
        if el.text:
            el.text = _process_text(el.text)

        # Process el.tail
        if el.tail:
            el.tail = _process_text(el.tail)

    report.total_fixes = (
        report.double_spaces_fixed +
        report.ocr_ligatures_fixed +
        report.smart_quotes_normalized +
        report.encoding_issues_fixed +
        report.punctuation_fixed +
        report.unicode_normalized
    )

    result = etree.tostring(tree, encoding='unicode', pretty_print=True)
    return result.encode('utf-8'), report
