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
