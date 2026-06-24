from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from lxml import etree

NS = {
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
    "ncx": "http://www.daisy.org/z3986/2005/ncx/",
    "xhtml": "http://www.w3.org/1999/xhtml",
    "epub": "http://www.idpf.org/2007/ops",
    "cnt": "urn:oasis:names:tc:opendocument:xmlns:container",
}

MEDIA_TYPES: dict[str, str] = {
    ".xhtml": "application/xhtml+xml",
    ".html":  "application/xhtml+xml",
    ".htm":   "application/xhtml+xml",
    ".css":   "text/css",
    ".ncx":   "application/x-dtbncx+xml",
    ".jpg":   "image/jpeg",
    ".jpeg":  "image/jpeg",
    ".png":   "image/png",
    ".gif":   "image/gif",
    ".svg":   "image/svg+xml",
    ".ttf":   "font/ttf",
    ".otf":   "font/otf",
    ".woff":  "font/woff",
    ".woff2": "font/woff2",
    ".mp3":   "audio/mpeg",
    ".mp4":   "video/mp4",
    ".js":    "application/javascript",
    ".smil":  "application/smil+xml",
}


class Severity(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"


@dataclass
class ValidationIssue:
    severity: Severity
    code: str
    message: str
    location: str | None = None


@dataclass
class ValidationResult:
    issues: list[ValidationIssue] = field(default_factory=list)

    def error(self, code: str, message: str, location: str | None = None) -> None:
        self.issues.append(ValidationIssue(Severity.ERROR, code, message, location))

    def warn(self, code: str, message: str, location: str | None = None) -> None:
        self.issues.append(ValidationIssue(Severity.WARNING, code, message, location))

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == Severity.WARNING]

    def ok(self) -> bool:
        return len(self.errors) == 0


def validate(epub_path: Path) -> ValidationResult:
    result = ValidationResult()

    if not zipfile.is_zipfile(epub_path):
        result.error("PKG001", "File is not a valid ZIP archive")
        return result

    with zipfile.ZipFile(epub_path) as zf:
        names = zf.namelist()
        name_set = set(names)

        _check_container(zf, names, name_set, result)
        opf_path = _find_opf_path(zf, result)
        if opf_path:
            _check_opf(zf, opf_path, name_set, result)

    return result


def _check_container(
    zf: zipfile.ZipFile,
    names: list[str],
    name_set: set[str],
    result: ValidationResult,
) -> None:
    # mimetype must exist
    if "mimetype" not in name_set:
        result.error("PKG002", "Missing 'mimetype' file")
    else:
        # must be first entry in ZIP
        if names[0] != "mimetype":
            result.error("PKG003", f"'mimetype' must be the first file in the ZIP (found at position {names.index('mimetype')})")

        # must be uncompressed
        info = zf.getinfo("mimetype")
        if info.compress_type != zipfile.ZIP_STORED:
            result.error("PKG004", "'mimetype' must be stored uncompressed (ZIP_STORED)")

        # must contain exactly the right value
        content = zf.read("mimetype").decode("ascii", errors="replace").strip()
        if content != "application/epub+zip":
            result.error("PKG005", f"'mimetype' must contain 'application/epub+zip', found: '{content}'")

    if "META-INF/container.xml" not in name_set:
        result.error("PKG006", "Missing 'META-INF/container.xml'")
    else:
        try:
            etree.fromstring(zf.read("META-INF/container.xml"))
        except etree.XMLSyntaxError as e:
            result.error("PKG007", f"'META-INF/container.xml' is not well-formed XML: {e}")


def _find_opf_path(zf: zipfile.ZipFile, result: ValidationResult) -> str | None:
    if "META-INF/container.xml" not in set(zf.namelist()):
        return None
    try:
        root = etree.fromstring(zf.read("META-INF/container.xml"))
    except etree.XMLSyntaxError:
        return None

    rootfiles = root.findall(".//cnt:rootfile", NS)
    if not rootfiles:
        result.error("PKG008", "No <rootfile> element found in container.xml")
        return None

    opf_path = rootfiles[0].get("full-path")
    if not opf_path:
        result.error("PKG009", "<rootfile> missing 'full-path' attribute")
        return None

    if opf_path not in set(zf.namelist()):
        result.error("PKG010", f"OPF file '{opf_path}' listed in container.xml does not exist in ZIP")
        return None

    return opf_path


def _check_opf(
    zf: zipfile.ZipFile,
    opf_path: str,
    name_set: set[str],
    result: ValidationResult,
) -> None:
    try:
        root = etree.fromstring(zf.read(opf_path))
    except etree.XMLSyntaxError as e:
        result.error("OPF001", f"OPF file is not well-formed XML: {e}", opf_path)
        return

    version = root.get("version", "")
    if not version.startswith(("2.", "3.")):
        result.warn("OPF002", f"Unrecognised EPUB version '{version}'", opf_path)

    # Required metadata
    opf_base = opf_path.rsplit("/", 1)[0] + "/" if "/" in opf_path else ""
    metadata = root.find("opf:metadata", NS)
    if metadata is None:
        result.error("OPF003", "OPF missing <metadata> element", opf_path)
    else:
        for tag in ("dc:title", "dc:identifier", "dc:language"):
            el = metadata.find(tag, NS)
            if el is None or not (el.text or "").strip():
                result.warn("OPF004", f"Missing or empty required metadata element <{tag}>", opf_path)

    # Manifest — collect items
    manifest = root.find("opf:manifest", NS)
    manifest_ids: dict[str, str] = {}  # id -> href

    if manifest is None:
        result.error("OPF005", "OPF missing <manifest> element", opf_path)
    else:
        for item in manifest.findall("opf:item", NS):
            item_id = item.get("id", "")
            href = item.get("href", "")
            media_type = item.get("media-type", "")

            if not item_id:
                result.error("OPF006", f"Manifest item missing 'id' attribute (href={href!r})", opf_path)
            if not href:
                result.error("OPF007", f"Manifest item missing 'href' attribute (id={item_id!r})", opf_path)
                continue

            manifest_ids[item_id] = href
            full_path = opf_base + href

            if full_path not in name_set and href not in name_set:
                result.error("OPF008", f"Manifest item '{href}' (id={item_id!r}) not found in ZIP", opf_path)

            ext = Path(href).suffix.lower()
            expected = MEDIA_TYPES.get(ext)
            if expected and media_type and media_type != expected:
                result.warn(
                    "OPF009",
                    f"'{href}' has media-type '{media_type}' but expected '{expected}'",
                    opf_path,
                )

    # Spine
    spine = root.find("opf:spine", NS)
    if spine is None:
        result.error("OPF010", "OPF missing <spine> element", opf_path)
    else:
        itemrefs = spine.findall("opf:itemref", NS)
        if not itemrefs:
            result.error("OPF011", "OPF <spine> has no <itemref> elements", opf_path)
        for ref in itemrefs:
            idref = ref.get("idref", "")
            if idref not in manifest_ids:
                result.error(
                    "OPF012",
                    f"Spine <itemref idref='{idref}'> not found in manifest",
                    opf_path,
                )

        # NCX check for EPUB 2
        if version.startswith("2."):
            toc_id = spine.get("toc")
            if not toc_id:
                result.warn("NCX001", "EPUB 2 <spine> missing 'toc' attribute pointing to NCX", opf_path)
            elif toc_id in manifest_ids:
                ncx_path = opf_base + manifest_ids[toc_id]
                _check_ncx(zf, ncx_path, result)
                _check_toc_completeness(zf, ncx_path, len(itemrefs), result)

        # NAV check for EPUB 3
        if version.startswith("3.") and manifest is not None:
            nav_items = [
                item for item in manifest.findall("opf:item", NS)
                if "nav" in item.get("properties", "").split()
            ]
            if not nav_items:
                result.error("NAV001", "EPUB 3 manifest has no item with properties='nav'", opf_path)
            else:
                nav_href = opf_base + nav_items[0].get("href", "")
                _check_nav(zf, nav_href, name_set, result)


def _check_ncx(zf: zipfile.ZipFile, ncx_path: str, result: ValidationResult) -> None:
    if ncx_path not in set(zf.namelist()):
        result.error("NCX002", f"NCX file '{ncx_path}' not found in ZIP")
        return
    try:
        root = etree.fromstring(zf.read(ncx_path))
    except etree.XMLSyntaxError as e:
        result.error("NCX003", f"NCX is not well-formed XML: {e}", ncx_path)
        return

    nav_map = root.find("ncx:navMap", NS)
    if nav_map is None:
        result.error("NCX004", "NCX missing <navMap> element", ncx_path)
        return

    nav_points = nav_map.findall(".//ncx:navPoint", NS)
    if not nav_points:
        result.error("NCX005", "NCX <navMap> has no <navPoint> elements", ncx_path)
        return
    else:
        ncx_base = ncx_path.rsplit("/", 1)[0] + "/" if "/" in ncx_path else ""
        name_set = set(zf.namelist())
        for point in nav_points:
            content = point.find("ncx:content", NS)
            if content is None:
                result.warn("NCX006", f"navPoint id={point.get('id')!r} has no <content> element", ncx_path)
                continue
            src = content.get("src", "").split("#")[0]  # strip fragment
            if src and (ncx_base + src) not in name_set and src not in name_set:
                result.warn("NCX007", f"NCX navPoint src '{src}' not found in ZIP", ncx_path)


def _check_toc_completeness(
    zf: zipfile.ZipFile,
    ncx_path: str,
    spine_count: int,
    result: ValidationResult,
) -> None:
    if ncx_path not in set(zf.namelist()):
        return
    try:
        root = etree.fromstring(zf.read(ncx_path))
    except etree.XMLSyntaxError:
        return
    nav_map = root.find("ncx:navMap", NS)
    if nav_map is None:
        return
    nav_count = len(nav_map.findall(".//ncx:navPoint", NS))
    if nav_count < spine_count:
        result.warn(
            "NCX008",
            f"TOC has {nav_count} navPoint(s) but spine has {spine_count} items — TOC appears incomplete",
            ncx_path,
        )


def _check_nav(
    zf: zipfile.ZipFile,
    nav_path: str,
    name_set: set[str],
    result: ValidationResult,
) -> None:
    if nav_path not in name_set:
        result.error("NAV002", f"NAV file '{nav_path}' not found in ZIP")
        return
    try:
        root = etree.fromstring(zf.read(nav_path))
    except etree.XMLSyntaxError as e:
        result.error("NAV003", f"NAV file is not well-formed XML: {e}", nav_path)
        return

    toc_navs = root.findall(
        ".//xhtml:nav[@epub:type='toc']",
        {**NS, "epub": "http://www.idpf.org/2007/ops"},
    )
    if not toc_navs:
        result.error("NAV004", "NAV file has no <nav epub:type='toc'> element", nav_path)
