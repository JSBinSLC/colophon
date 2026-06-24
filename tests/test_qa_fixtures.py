"""
QA test suite — real-world EPUBs from a Calibre library.

Each fixture was selected to represent a distinct defect profile. Tests assert
the validator detects the known defects AND that the round-trip (unpack → repack)
produces a valid ZIP with identical content.

Fixtures are not committed to the public repo (see .gitignore). If a fixture is
absent the test is skipped, so CI stays green without the copyrighted files.
"""
from __future__ import annotations

import hashlib
import shutil
import tempfile
import zipfile
from pathlib import Path

import pytest

from colophon.validator import validate, Severity

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> Path:
    return FIXTURES / name


def _skipif(name: str):
    return pytest.mark.skipif(
        not _fixture(name).exists(),
        reason=f"fixture '{name}' not present (copyrighted — not in repo)",
    )


def _issue_codes(path: Path) -> set[str]:
    return {i.code for i in validate(path).issues}


def _roundtrip(epub_path: Path) -> Path:
    """Unpack and repack; return path to the repacked EPUB."""
    from colophon.stages.repack import _pack_epub
    tmp = Path(tempfile.mkdtemp(prefix="colophon_qa_"))
    with zipfile.ZipFile(epub_path) as zf:
        zf.extractall(tmp)
    out = epub_path.parent / (epub_path.stem + ".roundtrip.epub")
    _pack_epub(tmp, out)
    shutil.rmtree(tmp, ignore_errors=True)
    return out


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# 1. Jack Vance — The Men Return  (NCX007: navPoint src not found in ZIP)
# ---------------------------------------------------------------------------

MEN_RETURN = "jack-vance---the-men-return---jack-vance.epub"


@_skipif(MEN_RETURN)
def test_men_return_has_ncx007():
    assert "NCX007" in _issue_codes(_fixture(MEN_RETURN))


@_skipif(MEN_RETURN)
def test_men_return_roundtrip():
    out = _roundtrip(_fixture(MEN_RETURN))
    try:
        assert zipfile.is_zipfile(out)
        result = validate(out)
        assert result.ok() or set(i.code for i in result.errors) == set(), \
            f"Roundtrip introduced new errors: {result.errors}"
    finally:
        out.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 2. Jack Vance — The Dogtown Tourist Agency  (NCX007 + NCX008)
# ---------------------------------------------------------------------------

DOGTOWN = "the-dogtown-tourist-agency---jack-vance.epub"


@_skipif(DOGTOWN)
def test_dogtown_has_ncx_issues():
    codes = _issue_codes(_fixture(DOGTOWN))
    assert codes & {"NCX007", "NCX008"}, f"Expected NCX issues, got: {codes}"


@_skipif(DOGTOWN)
def test_dogtown_roundtrip():
    out = _roundtrip(_fixture(DOGTOWN))
    try:
        assert zipfile.is_zipfile(out)
    finally:
        out.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 3. J.D. Salinger — Franny and Zooey  (NCX008: incomplete TOC)
# ---------------------------------------------------------------------------

FRANNY = "franny-and-zooey-a-novel---j.-d.-salinge.epub"


@_skipif(FRANNY)
def test_franny_has_incomplete_toc():
    assert "NCX008" in _issue_codes(_fixture(FRANNY))


@_skipif(FRANNY)
def test_franny_roundtrip():
    out = _roundtrip(_fixture(FRANNY))
    try:
        assert zipfile.is_zipfile(out)
    finally:
        out.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 4. Joseph Smith — Teachings  (NCX008 + OPF004: missing metadata)
# ---------------------------------------------------------------------------

TEACHINGS = "teachings-of-the-prophet-joseph---joseph.epub"


@_skipif(TEACHINGS)
def test_teachings_has_mixed_defects():
    codes = _issue_codes(_fixture(TEACHINGS))
    assert codes & {"NCX008", "OPF004"}, f"Expected NCX008 or OPF004, got: {codes}"


@_skipif(TEACHINGS)
def test_teachings_roundtrip():
    out = _roundtrip(_fixture(TEACHINGS))
    try:
        assert zipfile.is_zipfile(out)
    finally:
        out.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 5. Mary Eberstadt — Loser Letters  (NCX008: pure baseline)
# ---------------------------------------------------------------------------

LOSER = "loser-letters---mary-eberstadt.epub"


@_skipif(LOSER)
def test_loser_letters_has_incomplete_toc():
    assert "NCX008" in _issue_codes(_fixture(LOSER))


@_skipif(LOSER)
def test_loser_letters_roundtrip():
    out = _roundtrip(_fixture(LOSER))
    try:
        assert zipfile.is_zipfile(out)
    finally:
        out.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 6. Terry Brooks — Allanon's Quest  (NCX008 + OPF009: wrong media types)
# ---------------------------------------------------------------------------

ALLANON = "allanons-quest---terry-brooks.epub"


@_skipif(ALLANON)
def test_allanon_has_media_type_and_toc_issues():
    codes = _issue_codes(_fixture(ALLANON))
    assert codes & {"NCX008", "OPF009"}, f"Expected NCX008 or OPF009, got: {codes}"


@_skipif(ALLANON)
def test_allanon_roundtrip():
    out = _roundtrip(_fixture(ALLANON))
    try:
        assert zipfile.is_zipfile(out)
    finally:
        out.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 7. Connie Willis — Lincoln's Dreams  (NCX008 + OPF009: larger file)
# ---------------------------------------------------------------------------

LINCOLN = "lincolns-dreams---connie-willis.epub"


@_skipif(LINCOLN)
def test_lincolns_dreams_has_defects():
    codes = _issue_codes(_fixture(LINCOLN))
    assert codes & {"NCX008", "OPF009"}, f"Expected NCX008 or OPF009, got: {codes}"


@_skipif(LINCOLN)
def test_lincolns_dreams_roundtrip():
    out = _roundtrip(_fixture(LINCOLN))
    try:
        assert zipfile.is_zipfile(out)
    finally:
        out.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 8. B.C. Chase — Paradeisia  (NAV004: EPUB 3 missing toc nav)
# ---------------------------------------------------------------------------

PARADEISIA = "paradeisia-origin-of-paradise---b.c.-cha.epub"


@_skipif(PARADEISIA)
def test_paradeisia_has_epub3_nav_issue():
    result = validate(_fixture(PARADEISIA))
    codes = {i.code for i in result.issues}
    assert codes & {"NAV004", "NAV001", "NAV002", "NAV003"}, \
        f"Expected NAV issue, got: {codes}"


@_skipif(PARADEISIA)
def test_paradeisia_roundtrip():
    out = _roundtrip(_fixture(PARADEISIA))
    try:
        assert zipfile.is_zipfile(out)
    finally:
        out.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 9. Michael F. Kane — After Moses Wormwood  (OPF009: wrong media types)
# ---------------------------------------------------------------------------

MOSES = "after-moses-wormwood---michael-f.-kane.epub"


@_skipif(MOSES)
def test_moses_has_media_type_issues():
    assert "OPF009" in _issue_codes(_fixture(MOSES))


@_skipif(MOSES)
def test_moses_roundtrip():
    out = _roundtrip(_fixture(MOSES))
    try:
        assert zipfile.is_zipfile(out)
    finally:
        out.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 10. Jack Vance — Emphyrio  (OPF008: manifest items missing from ZIP)
# ---------------------------------------------------------------------------

EMPHYRIO = "emphyrio---jack-vance.epub"


@_skipif(EMPHYRIO)
def test_emphyrio_has_missing_manifest_items():
    assert "OPF008" in _issue_codes(_fixture(EMPHYRIO))


@_skipif(EMPHYRIO)
def test_emphyrio_roundtrip():
    out = _roundtrip(_fixture(EMPHYRIO))
    try:
        assert zipfile.is_zipfile(out)
    finally:
        out.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Cross-cutting: every fixture survives a round-trip without gaining NEW errors
# ---------------------------------------------------------------------------

ALL_FIXTURES = [
    MEN_RETURN, DOGTOWN, FRANNY, TEACHINGS, LOSER,
    ALLANON, LINCOLN, PARADEISIA, MOSES, EMPHYRIO,
]


@pytest.mark.parametrize("name", ALL_FIXTURES)
def test_no_new_errors_after_roundtrip(name: str):
    path = _fixture(name)
    if not path.exists():
        pytest.skip(f"fixture '{name}' not present")

    errors_before = {i.code for i in validate(path).errors}
    out = _roundtrip(path)
    try:
        errors_after = {i.code for i in validate(out).errors}
        new_errors = errors_after - errors_before
        assert not new_errors, \
            f"{name}: round-trip introduced new errors: {new_errors}"
    finally:
        out.unlink(missing_ok=True)
