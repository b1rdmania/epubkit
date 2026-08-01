"""
Metadata handler for Xteink X4 EPUB Optimizer.
Handles: metadata extraction, cleanup, cover detection, filename formatting.
"""

import re
import string
import unicodedata
from pathlib import Path
from typing import Optional

from lxml import etree

NAMESPACES = {
    'opf': 'http://www.idpf.org/2007/opf',
    'dc': 'http://purl.org/dc/elements/1.1/',
    'dcterms': 'http://purl.org/dc/terms/',
}

# Tags considered store/DRM metadata to strip
STORE_META_NAMES = {
    'calibre:timestamp', 'calibre:title_sort', 'calibre:author_link_map',
    'calibre:series', 'calibre:series_index', 'calibre:rating',
    'calibre:user_categories', 'calibre:user_metadata',
    'ibooks:version', 'ibooks:specified-fonts',
    'Sigil version', 'dtb:uid',
}

# Prefixes for metadata we want to strip
STORE_META_PREFIXES = ('calibre:', 'ibooks:', 'amazon:', 'kindle:')

FILENAME_FORMATS = {
    'original',
    'title-author',
    'author-title',
    'title',
    'custom',
}
FILENAME_TEMPLATE_FIELDS = {'title', 'author', 'year', 'original'}


def _find_dc(root, local_name, nsmap):
    """Find a Dublin Core element, trying multiple namespace strategies."""
    ns_dc = 'http://purl.org/dc/elements/1.1/'
    # Try with nsmap
    el = root.find(f'.//dc:{local_name}', nsmap)
    if el is not None:
        return el
    # Try direct namespace
    el = root.find(f'.//{{{ns_dc}}}{local_name}')
    if el is not None:
        return el
    # Wildcard: iterate and match local name
    for child in root.iter():
        tag = child.tag if isinstance(child.tag, str) else ''
        if tag.endswith('}' + local_name) or tag == local_name:
            return child
    return None


def _find_manifest(root):
    """Find manifest element regardless of namespace."""
    ns = 'http://www.idpf.org/2007/opf'
    el = root.find(f'.//{{{ns}}}manifest')
    if el is not None:
        return el
    el = root.find('.//manifest')
    if el is not None:
        return el
    for child in root.iter():
        tag = child.tag if isinstance(child.tag, str) else ''
        if tag.endswith('}manifest') or tag == 'manifest':
            return child
    return None


def extract_metadata(opf_tree: etree._ElementTree) -> dict:
    """
    Extract metadata from OPF document.
    Returns dict with: title, author, series, series_index, language, cover_id, cover_href
    """
    root = opf_tree.getroot()
    nsmap = _build_nsmap(root)

    metadata = {
        'title': '',
        'author': '',
        'year': '',
        'series': '',
        'series_index': '',
        'language': '',
        'cover_id': '',
        'cover_href': '',
    }

    # Title
    title_el = _find_dc(root, 'title', nsmap)
    if title_el is not None and title_el.text:
        metadata['title'] = title_el.text.strip()

    # Author
    creator_el = _find_dc(root, 'creator', nsmap)
    if creator_el is not None and creator_el.text:
        metadata['author'] = creator_el.text.strip()

    # Publication year
    date_el = _find_dc(root, 'date', nsmap)
    if date_el is not None and date_el.text:
        year_match = re.search(r'\b(\d{4})\b', date_el.text)
        if year_match:
            metadata['year'] = year_match.group(1)

    # Language
    lang_el = _find_dc(root, 'language', nsmap)
    if lang_el is not None and lang_el.text:
        metadata['language'] = lang_el.text.strip()

    # Series - check calibre metadata and EPUB 3 meta
    for meta in _iter_meta(root):
        name = meta.get('name', '')
        content = meta.get('content', '')
        prop = meta.get('property', '')

        if name == 'calibre:series' and content:
            metadata['series'] = content
        elif name == 'calibre:series_index' and content:
            metadata['series_index'] = content
        elif prop == 'belongs-to-collection' and meta.text:
            metadata['series'] = meta.text.strip()
        elif prop == 'group-position' and meta.text:
            metadata['series_index'] = meta.text.strip()

    # Cover image - try multiple detection methods
    cover_id = _find_cover_id(root, nsmap)
    if cover_id:
        metadata['cover_id'] = cover_id
        # Resolve cover href from manifest
        manifest = _find_manifest(root)
        if manifest is not None:
            for item in manifest:
                if item.get('id') == cover_id:
                    metadata['cover_href'] = item.get('href', '')
                    break

    return metadata


def _find_metadata(root):
    """Find metadata element regardless of namespace."""
    ns = 'http://www.idpf.org/2007/opf'
    el = root.find(f'.//{{{ns}}}metadata')
    if el is not None:
        return el
    el = root.find('.//metadata')
    if el is not None:
        return el
    for child in root.iter():
        tag = child.tag if isinstance(child.tag, str) else ''
        if tag.endswith('}metadata') or tag == 'metadata':
            return child
    return None


def _iter_meta(root):
    """Iterate over all <meta> elements regardless of namespace."""
    ns = 'http://www.idpf.org/2007/opf'
    found = list(root.iter(f'{{{ns}}}meta'))
    if found:
        yield from found
        return
    # Fallback: iterate all and match local name
    for child in root.iter():
        tag = child.tag if isinstance(child.tag, str) else ''
        if tag.endswith('}meta') or tag == 'meta':
            yield child


def _find_cover_id(root: etree._Element, nsmap: dict) -> str:
    """Find cover image ID using multiple detection strategies."""
    # Strategy 1: EPUB 3 properties="cover-image"
    manifest = _find_manifest(root)
    if manifest is not None:
        for item in manifest:
            if not isinstance(item.tag, str):
                continue  # Skip comments/PIs
            props = item.get('properties') or ''
            if 'cover-image' in props:
                return item.get('id', '')

    # Strategy 2: EPUB 2 <meta name="cover" content="id">
    for meta in _iter_meta(root):
        if meta.get('name') == 'cover':
            return meta.get('content', '')

    # Strategy 3: Look for item with id containing "cover" and image media type
    if manifest is not None:
        for item in manifest:
            if not isinstance(item.tag, str):
                continue  # Skip comments/PIs
            item_id = (item.get('id') or '').lower()
            media_type = (item.get('media-type') or '').lower()
            if 'cover' in item_id and media_type.startswith('image/'):
                return item.get('id', '')

    return ''


def _build_nsmap(root: etree._Element) -> dict:
    """Build namespace map from root element, filling in defaults."""
    nsmap = {}
    for prefix, uri in NAMESPACES.items():
        nsmap[prefix] = uri
    # Also pick up any declared in the document
    for prefix, uri in (root.nsmap or {}).items():
        if prefix and uri:
            nsmap[prefix] = uri
    return nsmap


def update_metadata(opf_tree: etree._ElementTree, edits: dict) -> None:
    """
    Apply user-edited metadata to OPF.
    edits can contain: title, author, series, series_index, language
    """
    root = opf_tree.getroot()
    ns_dc = 'http://purl.org/dc/elements/1.1/'

    metadata_el = _find_metadata(root)
    if metadata_el is None:
        return

    nsmap = _build_nsmap(root)

    if 'title' in edits and edits['title']:
        title_el = _find_dc(root, 'title', nsmap)
        if title_el is not None:
            title_el.text = edits['title']
        else:
            el = etree.SubElement(metadata_el, f'{{{ns_dc}}}title')
            el.text = edits['title']

    if 'author' in edits and edits['author']:
        creator_el = _find_dc(root, 'creator', nsmap)
        if creator_el is not None:
            creator_el.text = edits['author']
        else:
            el = etree.SubElement(metadata_el, f'{{{ns_dc}}}creator')
            el.text = edits['author']

    if 'language' in edits and edits['language']:
        lang_el = _find_dc(root, 'language', nsmap)
        if lang_el is not None:
            lang_el.text = edits['language']
        else:
            el = etree.SubElement(metadata_el, f'{{{ns_dc}}}language')
            el.text = edits['language']


def strip_store_metadata(opf_tree: etree._ElementTree) -> int:
    """
    Remove store-specific, DRM-adjacent, and calibre-specific metadata.
    Returns count of removed elements.
    """
    root = opf_tree.getroot()
    removed = 0

    metadata_el = _find_metadata(root)
    if metadata_el is None:
        return 0

    to_remove = []
    for meta in _iter_meta(metadata_el):
        name = meta.get('name', '')
        prop = meta.get('property', '')

        # Check exact matches
        if name in STORE_META_NAMES:
            to_remove.append(meta)
            continue

        # Check prefixes
        for prefix in STORE_META_PREFIXES:
            if name.startswith(prefix) or prop.startswith(prefix):
                to_remove.append(meta)
                break

    for el in to_remove:
        el.getparent().remove(el)
        removed += 1

    return removed


def format_filename(
    title: str,
    author: str,
    filename_format: str = 'author-title',
    template: str = '',
    original_filename: str = '',
    year: str = '',
) -> str:
    """
    Create a sanitized EPUB filename using a preset or custom template.
    """
    title = (title or '').strip()
    author = (author or '').strip()
    year = (year or '').strip()
    original = Path(original_filename or '').name
    if original.lower().endswith('.epub'):
        original = original[:-5]

    if filename_format not in FILENAME_FORMATS:
        raise ValueError(f"Unknown filename format: {filename_format}")

    if filename_format == 'original':
        name = original
    elif filename_format == 'title-author':
        name = _join_filename_parts(title, author)
    elif filename_format == 'author-title':
        name = _join_filename_parts(author, title)
    elif filename_format == 'title':
        name = title
    else:
        if not template.strip():
            raise ValueError("Custom filename template cannot be empty")
        parsed_template = list(string.Formatter().parse(template))
        if any(format_spec or conversion for _, _, format_spec, conversion in parsed_template):
            raise ValueError("Filename template fields do not support formatting options")
        fields = {field_name for _, field_name, _, _ in parsed_template if field_name}
        unsupported = fields - FILENAME_TEMPLATE_FIELDS
        if unsupported:
            names = ', '.join(sorted(unsupported))
            raise ValueError(f"Unknown filename template field: {names}")
        name = template.format(
            title=title,
            author=author,
            year=year,
            original=original,
        )

    if name.lower().endswith('.epub'):
        name = name[:-5]

    name = _sanitize_filename(name)
    if not name or name in {'.', '..'}:
        name = "optimized"

    if len(name) > 200:
        name = name[:200].rstrip(' .-')

    return f"{name}.epub"


def _join_filename_parts(first: str, second: str) -> str:
    """Join available metadata fields without leaving an empty separator."""
    return ' - '.join(part for part in (first, second) if part)


def _sanitize_filename(name: str) -> str:
    """Remove characters that are problematic in filenames."""
    # Replace common problematic chars
    replacements = {
        '/': '-', '\\': '-', ':': ' -', '*': '', '?': '',
        '"': "'", '<': '', '>': '', '|': '-',
    }
    for old, new in replacements.items():
        name = name.replace(old, new)

    # Normalize unicode
    name = unicodedata.normalize('NFC', name)

    # Remove control characters
    name = re.sub(r'[\x00-\x1f\x7f]', '', name)

    # Collapse multiple spaces/dashes
    name = re.sub(r'\s+', ' ', name)
    name = re.sub(r'-{2,}', '-', name)

    return name.strip(' .-')
