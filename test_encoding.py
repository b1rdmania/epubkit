"""Regression tests for the UTF-8 handling reported in issue #1."""

import pytest
from lxml import etree

from html_cleaner import (
    recovery_parser,
    repair_html,
    strip_unnecessary_attributes,
    normalize_whitespace,
    collect_used_selectors,
)
from text_cleaner import clean_text_content, TextCleanOptions, _fix_mojibake, _fix_whitespace

GERMAN = 'Während ihre Schwester die Lehre als Verkäuferin abgebrochen hatte'
QUOTED = '»Wie geht’s Mutter übrigens?«'

# Malformed on purpose: the unclosed <br> forces the recovery parser, which is
# where the declared encoding was being lost.
NO_CHARSET = ('<!DOCTYPE html><html><body><p>%s</p><p>%s<br></p></body></html>'
              % (GERMAN, QUOTED)).encode('utf-8')
LATIN1_CHARSET = ('<html><head><meta http-equiv="Content-Type" '
                  'content="text/html; charset=iso-8859-1"/></head>'
                  '<body><p>%s<br></p></body></html>' % GERMAN).encode('utf-8')

# UTF-8 bytes decoded as latin-1, written as escapes so the fixtures stay
# readable in editors that would otherwise hide the C1 control characters.
MOJI_UMLAUT = 'VerkÃ¤uferin KopfhÃ¶rer StraÃe'
MOJI_QUOTES = ('gehtâs and '
               'âquotedâ')


def _text(raw):
    return raw.decode('utf-8', 'replace')


def test_recovery_parser_keeps_utf8():
    tree = etree.fromstring(NO_CHARSET, recovery_parser(NO_CHARSET))
    assert 'Verkäuferin' in etree.tostring(tree, encoding='unicode')


def test_recovery_parser_falls_back_when_not_utf8():
    latin1 = GERMAN.encode('latin-1')
    tree = etree.fromstring(b'<html><body><p>' + latin1 + b'</p></body></html>',
                            recovery_parser(latin1))
    assert tree is not None


def test_repair_html_keeps_umlauts():
    out = _text(repair_html(NO_CHARSET))
    assert 'Verkäuferin' in out
    assert 'Ã¤' not in out


def test_attribute_stripping_keeps_umlauts():
    out, _ = strip_unnecessary_attributes(repair_html(NO_CHARSET))
    assert 'Verkäuferin' in _text(out)
    assert 'Ã' not in _text(out)


def test_whitespace_normalization_keeps_umlauts():
    out, _ = normalize_whitespace(repair_html(NO_CHARSET))
    assert 'Verkäuferin' in _text(out)


def test_text_cleaning_keeps_umlauts_and_quotes():
    out, _ = clean_text_content(repair_html(NO_CHARSET), TextCleanOptions())
    assert 'Verkäuferin' in _text(out)
    assert 'übrigens' in _text(out)
    assert 'Ã' not in _text(out)


def test_latin1_declaration_does_not_mangle_utf8_bytes():
    out, _ = strip_unnecessary_attributes(repair_html(LATIN1_CHARSET))
    assert 'Verkäuferin' in _text(out)


def test_selector_collection_survives_non_ascii():
    markup = '<html><body><p class="kapitelüberschrift">x<br></p></body></html>'
    classes, _, _ = collect_used_selectors(markup.encode('utf-8'))
    assert 'kapitelüberschrift' in classes


def test_mojibake_table_repairs_smart_quotes():
    fixed, count = _fix_mojibake(MOJI_QUOTES)
    assert fixed == 'geht’s and “quoted”'
    assert count == 3


def test_mojibake_table_repairs_umlauts_and_sharp_s():
    fixed, _ = _fix_mojibake(MOJI_UMLAUT)
    assert fixed == 'Verkäuferin Kopfhörer Straße'


def test_text_cleaning_parity_punctuation_spacing_and_counts():
    try:
        import epubkit_rs
    except ImportError:
        pytest.skip("epubkit_rs extension not available")

    raw = "Hello   world  , this  is  a test  !  Multiple   spaces\t\tand   tabs ."
    # Python pure passes
    py_res, py_ws_cnt = _fix_whitespace(raw)
    assert py_res == "Hello world, this is a test! Multiple spaces and tabs."
    assert py_ws_cnt == 12

    # Rust fast cleaner
    rs_res, rs_ds, rs_ocr, rs_q, rs_moj, rs_tot = epubkit_rs.clean_text_fast(
        raw, False, True, False, False
    )
    assert rs_res == py_res
    assert rs_ds == py_ws_cnt
    assert rs_tot == py_ws_cnt


def test_text_cleaning_parity_mojibake_and_quotes():
    try:
        import epubkit_rs
    except ImportError:
        pytest.skip("epubkit_rs extension not available")

    # In Python, mojibake runs AFTER OCR/quotes, preserving reconstructed smart quotes
    # \u00e2\u0080\u0099 is right single quote, \u00e2\u0080\u009c is left double quote, \u00e2\u0080\u009d is right double quote
    text = "It\u00e2\u0080\u0099s \u00e2\u0080\u009cfine\u00e2\u0080\u009d\u00a0\ufb01sh"
    
    # Fast Rust pass with all enabled
    rs_res, rs_ds, rs_ocr, rs_q, rs_moj, rs_tot = epubkit_rs.clean_text_fast(
        text, True, True, True, True
    )
    # The non-breaking space is normalized to ' ', \ufb01 is 'fi', mojibake quotes become ’ and “ ”
    assert rs_res == "It’s “fine” fish"
    assert rs_ocr == 1  # fi
    assert rs_q == 1    # \u00a0 -> ' '
    assert rs_moj == 3  # \u00e2\u0080\u0099, \u00e2\u0080\u009c, \u00e2\u0080\u009d


def test_text_cleaning_parity_fix_ocr_false():
    try:
        import epubkit_rs
    except ImportError:
        pytest.skip("epubkit_rs extension not available")

    # When fix_ocr is False, quote normalization is disabled even if normalize_quotes is True
    text = "‘Single’ and “Double” \ufb01"
    rs_res, rs_ds, rs_ocr, rs_q, rs_moj, rs_tot = epubkit_rs.clean_text_fast(
        text, True, False, False, False
    )
    assert rs_res == text  # Unchanged
    assert rs_ocr == 0
    assert rs_q == 0

