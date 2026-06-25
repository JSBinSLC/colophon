"""Generate the small committed public-domain seed fixtures.

These are tiny, hand-built EPUBs whose text is unambiguously public domain
(Charles Dickens, d. 1870). They are committed to the repo so the fixture-based
tests run out of the box on a fresh clone / in CI — unlike the copyrighted
Calibre EPUBs, which are gitignored and only present locally.

Run from the repo root:  python tests/fixtures/public-domain/make_seeds.py

Seeds produced (in this directory):
  pd-clean-epub3.epub      valid EPUB 3 with a proper nav — clean baseline / "do not break valid files"
  pd-broken-toc-epub2.epub EPUB 2 whose toc.ncx covers only 1 of 3 chapters — NCX008 defect
"""
from __future__ import annotations

import zipfile
from pathlib import Path

HERE = Path(__file__).parent

# Public-domain text — Charles Dickens (d. 1870). Short excerpts.
CHAPTERS = [
    ("I", "A Tale of Two Cities",
     "It was the best of times, it was the worst of times, it was the age of "
     "wisdom, it was the age of foolishness."),
    ("II", "David Copperfield",
     "Whether I shall turn out to be the hero of my own life, or whether that "
     "station will be held by anybody else, these pages must show."),
    ("III", "Great Expectations",
     "My father's family name being Pirrip, and my Christian name Philip, my "
     "infant tongue could make of both names nothing longer or more explicit "
     "than Pip."),
]


def _xhtml(title: str, body: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">\n'
        f"<head><title>{title}</title></head>\n"
        f'<body><section epub:type="chapter"><h1>{title}</h1><p>{body}</p></section></body>\n'
        "</html>\n"
    )


def _write_epub(path: Path, files: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        # mimetype first, stored (uncompressed), per OCF spec.
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        for name, content in files.items():
            z.writestr(name, content)


_CONTAINER = (
    '<?xml version="1.0"?>\n'
    '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
    '  <rootfiles><rootfile full-path="OEBPS/content.opf" '
    'media-type="application/oebps-package+xml"/></rootfiles>\n'
    "</container>\n"
)


def build_clean_epub3() -> Path:
    manifest, spine, navlis = [], [], []
    files: dict[str, str] = {}
    for i, (num, title, body) in enumerate(CHAPTERS):
        fn = f"chap{i}.xhtml"
        files[f"OEBPS/{fn}"] = _xhtml(f"Chapter {num}: {title}", body)
        manifest.append(f'<item id="c{i}" href="{fn}" media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="c{i}"/>')
        navlis.append(f'<li><a href="{fn}">Chapter {num}: {title}</a></li>')

    files["OEBPS/nav.xhtml"] = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">\n'
        "<head><title>Contents</title></head><body>\n"
        '<nav epub:type="toc"><ol>\n' + "\n".join(navlis) + "\n</ol></nav>\n"
        "</body></html>\n"
    )
    manifest.append('<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>')
    files["OEBPS/content.opf"] = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        "    <dc:title>Dickens Sampler (clean EPUB 3 seed)</dc:title>\n"
        "    <dc:creator>Charles Dickens</dc:creator>\n"
        "    <dc:language>en</dc:language>\n"
        '    <dc:identifier id="uid">colophon-seed-clean-epub3</dc:identifier>\n'
        "  </metadata>\n"
        "  <manifest>\n    " + "\n    ".join(manifest) + "\n  </manifest>\n"
        "  <spine>\n    " + "\n    ".join(spine) + "\n  </spine>\n"
        "</package>\n"
    )
    files["META-INF/container.xml"] = _CONTAINER
    out = HERE / "pd-clean-epub3.epub"
    _write_epub(out, files)
    return out


def build_broken_toc_epub2() -> Path:
    manifest, spine = [], []
    files: dict[str, str] = {}
    for i, (num, title, body) in enumerate(CHAPTERS):
        fn = f"chap{i}.xhtml"
        files[f"OEBPS/{fn}"] = _xhtml(f"Chapter {num}: {title}", body)
        manifest.append(f'<item id="c{i}" href="{fn}" media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="c{i}"/>')

    # toc.ncx deliberately lists only the FIRST chapter (3 spine, 1 navPoint) -> NCX008.
    files["OEBPS/toc.ncx"] = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
        '  <head><meta name="dtb:uid" content="colophon-seed-broken-toc"/></head>\n'
        "  <docTitle><text>Dickens Sampler (broken TOC seed)</text></docTitle>\n"
        '  <navMap><navPoint id="np0" playOrder="1"><navLabel><text>Chapter I</text></navLabel>\n'
        '    <content src="chap0.xhtml"/></navPoint></navMap>\n'
        "</ncx>\n"
    )
    manifest.append('<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>')
    files["OEBPS/content.opf"] = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="uid">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        "    <dc:title>Dickens Sampler (broken TOC seed)</dc:title>\n"
        "    <dc:creator>Charles Dickens</dc:creator>\n"
        "    <dc:language>en</dc:language>\n"
        '    <dc:identifier id="uid">colophon-seed-broken-toc</dc:identifier>\n'
        "  </metadata>\n"
        "  <manifest>\n    " + "\n    ".join(manifest) + "\n  </manifest>\n"
        '  <spine toc="ncx">\n    ' + "\n    ".join(spine) + "\n  </spine>\n"
        "</package>\n"
    )
    files["META-INF/container.xml"] = _CONTAINER
    out = HERE / "pd-broken-toc-epub2.epub"
    _write_epub(out, files)
    return out


if __name__ == "__main__":
    for builder in (build_clean_epub3, build_broken_toc_epub2):
        p = builder()
        print(f"wrote {p.relative_to(HERE.parents[2])} ({p.stat().st_size} bytes)")
