from pathlib import Path
import zipfile
import pytest

from colophon.validator import validate, Severity

FIXTURE = Path(__file__).parent / "fixtures" / "the-lost-years.epub"


@pytest.mark.skipif(not FIXTURE.exists(), reason="fixture EPUB not present")
def test_fixture_is_valid_zip():
    assert zipfile.is_zipfile(FIXTURE)


@pytest.mark.skipif(not FIXTURE.exists(), reason="fixture EPUB not present")
def test_fixture_validates():
    result = validate(FIXTURE)
    # The fixture is a real EPUB — container should be sound even if TOC is broken
    assert result is not None
    # Report what we find (useful during development)
    for issue in result.issues:
        print(f"[{issue.severity}] {issue.code}: {issue.message} ({issue.location})")


@pytest.mark.skipif(not FIXTURE.exists(), reason="fixture EPUB not present")
def test_fixture_ncx_incomplete():
    """The Lost Years has only 1 navPoint in its NCX — we should detect this as a warning."""
    result = validate(FIXTURE)
    # The NCX exists and is well-formed, so no NCX errors expected
    ncx_errors = [i for i in result.issues if i.code.startswith("NCX") and i.severity == Severity.ERROR]
    assert not ncx_errors, f"Unexpected NCX errors: {ncx_errors}"


def test_invalid_zip(tmp_path):
    bad = tmp_path / "bad.epub"
    bad.write_bytes(b"not a zip file")
    result = validate(bad)
    assert not result.ok()
    assert any(i.code == "PKG001" for i in result.errors)


def test_missing_mimetype(tmp_path):
    epub = tmp_path / "test.epub"
    with zipfile.ZipFile(epub, "w") as zf:
        zf.writestr("META-INF/container.xml", "<container/>")
    result = validate(epub)
    assert any(i.code == "PKG002" for i in result.errors)


def test_mimetype_wrong_position(tmp_path):
    epub = tmp_path / "test.epub"
    with zipfile.ZipFile(epub, "w") as zf:
        zf.writestr("META-INF/container.xml", "<container/>")
        zf.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip")
    result = validate(epub)
    assert any(i.code == "PKG003" for i in result.errors)


def test_mimetype_compressed(tmp_path):
    epub = tmp_path / "test.epub"
    with zipfile.ZipFile(epub, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/epub+zip")
    result = validate(epub)
    assert any(i.code == "PKG004" for i in result.errors)


# ---- EPUB 3 NAV path (built in-memory; no binary fixture committed) ----

CONTAINER_XML = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""

OPF_EPUB3 = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Test</dc:title>
    <dc:identifier id="uid">urn:uuid:test</dc:identifier>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="ch1"/>
  </spine>
</package>"""

NAV_WITH_TOC = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
  <body>
    <nav epub:type="toc"><ol><li><a href="ch1.xhtml">One</a></li></ol></nav>
  </body>
</html>"""

NAV_WITHOUT_TOC = NAV_WITH_TOC.replace('epub:type="toc"', 'epub:type="landmarks"')


def _build_epub3(tmp_path, nav_content: str) -> Path:
    epub = tmp_path / "epub3.epub"
    with zipfile.ZipFile(epub, "w") as zf:
        zf.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip")
        zf.writestr("META-INF/container.xml", CONTAINER_XML)
        zf.writestr("OEBPS/content.opf", OPF_EPUB3)
        zf.writestr("OEBPS/nav.xhtml", nav_content)
        zf.writestr("OEBPS/ch1.xhtml", "<html xmlns='http://www.w3.org/1999/xhtml'><body><p>hi</p></body></html>")
    return epub


def test_epub3_valid_nav_passes(tmp_path):
    epub = _build_epub3(tmp_path, NAV_WITH_TOC)
    result = validate(epub)
    # A well-formed EPUB 3 with a toc nav should produce no errors —
    # this guards against the namespaced-predicate false positive.
    assert result.ok(), f"Unexpected errors: {result.errors}"
    assert not any(i.code == "NAV004" for i in result.issues)


def test_epub3_missing_toc_nav_detected(tmp_path):
    epub = _build_epub3(tmp_path, NAV_WITHOUT_TOC)
    result = validate(epub)
    assert any(i.code == "NAV004" for i in result.errors)


# ---- DRM gating ----

ADEPT_RIGHTS = """<?xml version="1.0"?>
<adept:rights xmlns:adept="http://ns.adobe.com/adept"><licenseToken/></adept:rights>"""

ENCRYPTION_ADEPT = """<?xml version="1.0"?>
<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <EncryptedData xmlns="http://www.w3.org/2001/04/xmlenc#">
    <KeyInfo xmlns="http://www.w3.org/2000/09/xmldsig#">
      <resource xmlns="http://ns.adobe.com/adept">urn:uuid:abc</resource>
    </KeyInfo>
    <CipherData><CipherReference URI="OEBPS/ch1.xhtml"/></CipherData>
  </EncryptedData>
</encryption>"""

# IDPF font obfuscation — legitimately uses encryption.xml, is NOT DRM.
ENCRYPTION_FONT_ONLY = """<?xml version="1.0"?>
<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <EncryptedData xmlns="http://www.w3.org/2001/04/xmlenc#">
    <EncryptionMethod Algorithm="http://www.idpf.org/2008/embedding"/>
    <CipherData><CipherReference URI="OEBPS/fonts/body.otf"/></CipherData>
  </EncryptedData>
</encryption>"""


def test_drm_adept_rights_file_detected(tmp_path):
    """An Adobe ADEPT rights.xml is a definitive DRM marker."""
    epub = _build_epub3(tmp_path, NAV_WITH_TOC)
    with zipfile.ZipFile(epub, "a") as zf:
        zf.writestr("META-INF/encryption.xml", ENCRYPTION_ADEPT)
        zf.writestr("META-INF/rights.xml", ADEPT_RIGHTS)
    result = validate(epub)
    assert any(i.code == "DRM001" for i in result.errors)


def test_drm_is_the_only_error_reported(tmp_path):
    """DRM short-circuits: no misleading downstream errors on encrypted bytes."""
    epub = _build_epub3(tmp_path, NAV_WITHOUT_TOC)  # would otherwise be NAV004
    with zipfile.ZipFile(epub, "a") as zf:
        zf.writestr("META-INF/encryption.xml", ENCRYPTION_ADEPT)
    codes = {i.code for i in validate(epub).issues}
    assert codes == {"DRM001"}, f"Expected only DRM001, got {codes}"


def test_font_obfuscation_is_not_drm(tmp_path):
    """Font obfuscation uses encryption.xml but must NOT be gated as DRM."""
    epub = _build_epub3(tmp_path, NAV_WITH_TOC)
    with zipfile.ZipFile(epub, "a") as zf:
        zf.writestr("META-INF/encryption.xml", ENCRYPTION_FONT_ONLY)
    result = validate(epub)
    assert not any(i.code == "DRM001" for i in result.issues)
    assert result.ok(), f"Font-obfuscated EPUB should still validate: {result.errors}"
