"""End-to-end pipeline test: build a real EPUB, run it through process_epub.

Covers the image path (Pillow), the XHTML path (lxml) and the upload path
(python-multipart), so a dependency bump that breaks any of them fails here
rather than in production.
"""
import os
import tempfile
import zipfile

import pytest

from PIL import Image, ImageDraw

from epub_processor import process_epub, ProcessingOptions

OPF = '''<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="id">urn:uuid:test</dc:identifier>
    <dc:title>Der Verkäufer</dc:title>
    <dc:creator>Käthe Müller</dc:creator>
    <dc:language>de</dc:language>
    <dc:date>1965-01-01</dc:date>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="cover" href="cover.png" media-type="image/png" properties="cover-image"/>
    <item id="img1" href="plate.jpg" media-type="image/jpeg"/>
    <item id="css" href="style.css" media-type="text/css"/>
  </manifest>
  <spine><itemref idref="c1"/></spine>
</package>'''

NAV = ('<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml" '
       'xmlns:epub="http://www.idpf.org/2007/ops"><body><nav epub:type="toc">'
       '<ol><li><a href="ch1.xhtml">Kapitel 1</a></li></ol></nav></body></html>')

# Deliberately malformed (unclosed <br>) so the recovery parser runs.
CH1 = ('<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Kapitel</title>'
       '<link rel="stylesheet" href="style.css"/></head><body>'
       '<h1 class="kapitelüberschrift">Kapitel 1</h1>'
       '<p>Während ihre Schwester die Lehre als Verkäuferin abgebrochen hatte, '
       'trug sie Kopfhörer.<br></p>'
       '<p>»Wie geht’s Mutter übrigens?«</p>'
       '<img src="plate.jpg" alt="Tafel"/>'
       '</body></html>')

CSS = '.kapitelüberschrift { color: #333; } .unused-rule { color: red; }'


def build_epub(path):
    tmp = tempfile.mkdtemp()
    cover = Image.new('RGB', (900, 1400), (200, 60, 60))
    ImageDraw.Draw(cover).rectangle([50, 50, 850, 400], fill=(20, 20, 120))
    cover_path = os.path.join(tmp, 'cover.png')
    cover.save(cover_path)

    plate = Image.new('RGB', (1600, 1200), (30, 160, 90))
    ImageDraw.Draw(plate).ellipse([100, 100, 1500, 1100], fill=(240, 240, 30))
    plate_path = os.path.join(tmp, 'plate.jpg')
    plate.save(plate_path, quality=95)

    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('mimetype', 'application/epub+zip')
        z.writestr('META-INF/container.xml',
                   '<?xml version="1.0"?><container version="1.0" '
                   'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<rootfiles><rootfile full-path="OEBPS/content.opf" '
                   'media-type="application/oebps-package+xml"/></rootfiles></container>')
        z.writestr('OEBPS/content.opf', OPF)
        z.writestr('OEBPS/nav.xhtml', NAV)
        z.writestr('OEBPS/ch1.xhtml', CH1)
        z.writestr('OEBPS/style.css', CSS)
        z.write(cover_path, 'OEBPS/cover.png')
        z.write(plate_path, 'OEBPS/plate.jpg')

def _process():
    work = tempfile.mkdtemp()
    src = os.path.join(work, 'in.epub')
    dst = os.path.join(work, 'out.epub')
    build_epub(src)
    report = process_epub(src, dst, ProcessingOptions())
    return src, dst, report


def test_pipeline_produces_a_smaller_epub():
    src, dst, report = _process()
    assert report.success, report.error
    assert os.path.exists(dst)
    assert os.path.getsize(dst) < os.path.getsize(src)


def test_pipeline_keeps_images():
    _, dst, _ = _process()
    with zipfile.ZipFile(dst) as z:
        images = [n for n in z.namelist()
                  if n.lower().endswith(('.jpg', '.jpeg', '.png'))]
    assert images


def test_pipeline_keeps_text_intact():
    _, dst, _ = _process()
    with zipfile.ZipFile(dst) as z:
        chapter = next(z.read(n).decode('utf-8', 'replace')
                       for n in z.namelist() if n.endswith('ch1.xhtml'))
    assert 'Verkäuferin' in chapter
    assert 'Ã' not in chapter


def test_upload_endpoint_accepts_multipart():
    pytest.importorskip('httpx', reason='TestClient needs httpx')
    from fastapi.testclient import TestClient
    import app as app_module

    work = tempfile.mkdtemp()
    src = os.path.join(work, 'in.epub')
    build_epub(src)

    client = TestClient(app_module.app)
    with open(src, 'rb') as fh:
        response = client.post(
            '/upload',
            files={'files': ('Der Verkäufer.epub', fh, 'application/epub+zip')})

    assert response.status_code == 200
    payload = response.json()
    assert payload['files'][0]['metadata']['title'] == 'Der Verkäufer'
