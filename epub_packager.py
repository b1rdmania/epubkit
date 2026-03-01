"""
EPUB packager for Xteink X4 EPUB Optimizer.
Handles: EPUB extraction, repackaging with correct mimetype-first ZIP structure, OS artifact cleanup.
"""

import os
import zipfile
from pathlib import Path

# Files/dirs to exclude from packaged EPUB
OS_ARTIFACTS = {
    '.DS_Store', 'Thumbs.db', 'desktop.ini', '._.DS_Store',
}
OS_ARTIFACT_DIRS = {
    '__MACOSX', '.git', '.svn',
}


def extract_epub(epub_path: str, dest_dir: str) -> None:
    """
    Extract an EPUB file to a directory.
    Validates ZIP structure and prevents zip-slip attacks.
    """
    dest = os.path.abspath(dest_dir)

    with zipfile.ZipFile(epub_path, 'r') as zf:
        for entry in zf.namelist():
            # Zip-slip prevention
            target = os.path.abspath(os.path.join(dest, entry))
            if not target.startswith(dest + os.sep) and target != dest:
                raise ValueError(f"Unsafe path in EPUB: {entry}")

        zf.extractall(dest)


def package_epub(source_dir: str, output_path: str) -> None:
    """
    Create a valid EPUB ZIP file from a directory.
    - mimetype is first entry, stored (uncompressed), no extra field
    - All other files are deflated
    - OS artifacts are excluded
    """
    source = Path(source_dir)
    mimetype_path = source / 'mimetype'

    with zipfile.ZipFile(output_path, 'w') as zf:
        # 1. Write mimetype first, uncompressed, no extra field
        info = zipfile.ZipInfo('mimetype')
        info.compress_type = zipfile.ZIP_STORED
        info.extra = b''
        if mimetype_path.exists():
            mimetype_content = mimetype_path.read_text().strip()
        else:
            mimetype_content = 'application/epub+zip'
        zf.writestr(info, mimetype_content)

        # 2. Write META-INF/container.xml next (convention)
        container_path = source / 'META-INF' / 'container.xml'
        if container_path.exists():
            arcname = 'META-INF/container.xml'
            zf.write(str(container_path), arcname, compress_type=zipfile.ZIP_DEFLATED)

        # 3. Write everything else
        for root, dirs, files in os.walk(source):
            # Filter out OS artifact directories
            dirs[:] = [d for d in dirs if d not in OS_ARTIFACT_DIRS]

            for filename in sorted(files):
                filepath = Path(root) / filename
                arcname = str(filepath.relative_to(source))

                # Skip mimetype (already written)
                if arcname == 'mimetype':
                    continue

                # Skip META-INF/container.xml (already written)
                if arcname == os.path.join('META-INF', 'container.xml'):
                    continue

                # Skip OS artifacts
                if filename in OS_ARTIFACTS:
                    continue

                zf.write(str(filepath), arcname, compress_type=zipfile.ZIP_DEFLATED)


def remove_os_artifacts(directory: str) -> int:
    """
    Remove OS artifacts from extracted EPUB directory.
    Returns count of removed files.
    """
    removed = 0
    dir_path = Path(directory)

    # Remove artifact files
    for artifact in OS_ARTIFACTS:
        for found in dir_path.rglob(artifact):
            found.unlink()
            removed += 1

    # Remove artifact directories
    for artifact_dir in OS_ARTIFACT_DIRS:
        for found in dir_path.rglob(artifact_dir):
            if found.is_dir():
                import shutil
                shutil.rmtree(found)
                removed += 1

    return removed


def is_valid_epub(epub_path: str) -> tuple[bool, str]:
    """
    Quick validation of an EPUB file.
    Returns (is_valid, error_message).
    """
    try:
        with zipfile.ZipFile(epub_path, 'r') as zf:
            names = zf.namelist()

            # Check mimetype is first entry
            if not names or names[0] != 'mimetype':
                return False, "mimetype is not the first entry in the ZIP"

            # Check mimetype content
            mimetype = zf.read('mimetype').decode('utf-8').strip()
            if mimetype != 'application/epub+zip':
                return False, f"Invalid mimetype: {mimetype}"

            # Check mimetype is stored (uncompressed)
            info = zf.getinfo('mimetype')
            if info.compress_type != zipfile.ZIP_STORED:
                return False, "mimetype entry is compressed (should be stored)"

            # Check container.xml exists
            if 'META-INF/container.xml' not in names:
                return False, "Missing META-INF/container.xml"

            return True, ""

    except zipfile.BadZipFile:
        return False, "Not a valid ZIP file"
    except Exception as e:
        return False, str(e)


def has_drm(epub_path: str) -> bool:
    """Check if an EPUB file contains DRM encryption."""
    try:
        with zipfile.ZipFile(epub_path, 'r') as zf:
            if 'META-INF/encryption.xml' in zf.namelist():
                # Read encryption.xml to confirm it's actual DRM
                enc_content = zf.read('META-INF/encryption.xml').decode('utf-8', errors='ignore')
                # Font obfuscation is not DRM - check for actual encryption methods
                if 'http://www.w3.org/2001/04/xmlenc' in enc_content:
                    # Check if it's only font obfuscation
                    if 'http://www.idpf.org/2008/embedding' in enc_content or \
                       'http://ns.adobe.com/pdf/enc' in enc_content:
                        # Could be font obfuscation only - check for other encryption
                        if 'http://ns.adobe.com/adept' in enc_content or \
                           'EncryptedData' in enc_content:
                            # Count encrypted items - if only fonts, likely just obfuscation
                            from lxml import etree
                            try:
                                tree = etree.fromstring(enc_content.encode('utf-8'))
                                encrypted = tree.findall('.//{http://www.w3.org/2001/04/xmlenc#}EncryptedData')
                                # If we have encrypted content files (not just fonts), it's DRM
                                for item in encrypted:
                                    cipher = item.find('.//{http://www.w3.org/2001/04/xmlenc#}CipherReference')
                                    if cipher is not None:
                                        uri = cipher.get('URI', '')
                                        ext = Path(uri).suffix.lower()
                                        if ext not in {'.ttf', '.otf', '.woff', '.woff2'}:
                                            return True
                            except Exception:
                                return True
                    else:
                        return True
            return False
    except Exception:
        return False


def find_opf_path(epub_dir: str) -> str:
    """
    Find the OPF file path by reading META-INF/container.xml.
    Returns the path relative to the EPUB root directory.
    """
    container_path = os.path.join(epub_dir, 'META-INF', 'container.xml')

    if not os.path.exists(container_path):
        # Fallback: search for .opf file
        for root, dirs, files in os.walk(epub_dir):
            for f in files:
                if f.endswith('.opf'):
                    return os.path.relpath(os.path.join(root, f), epub_dir)
        raise FileNotFoundError("No OPF file found in EPUB")

    from lxml import etree
    tree = etree.parse(container_path)
    root = tree.getroot()

    # Find rootfile element
    ns = {'container': 'urn:oasis:names:tc:opendocument:xmlns:container'}
    rootfile = root.find('.//container:rootfile', ns)
    if rootfile is None:
        # Try without namespace
        rootfile = root.find('.//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile')
    if rootfile is None:
        # Wildcard fallback
        for child in root.iter():
            tag = child.tag if isinstance(child.tag, str) else ''
            if tag.endswith('}rootfile') or tag == 'rootfile':
                rootfile = child
                break

    if rootfile is None:
        raise FileNotFoundError("No rootfile found in container.xml")

    return rootfile.get('full-path')
