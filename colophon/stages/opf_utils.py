"""Shared OPF / spine helpers for stages 2–5."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lxml import etree

OPF_NS = "http://www.idpf.org/2007/opf"
DC_NS = "http://purl.org/dc/elements/1.1/"


@dataclass
class SpineItem:
    item_id: str
    href: str
    abs_path: Path
    media_type: str = "application/xhtml+xml"


@dataclass
class OPFInfo:
    path: Path
    opf_dir: Path
    root: Any
    uid: str
    title: str
    version: str
    spine_items: list[SpineItem] = field(default_factory=list)
    manifest: dict[str, dict[str, str]] = field(default_factory=dict)
    ncx_id: str | None = None
    ncx_href: str | None = None
    nav_id: str | None = None
    nav_href: str | None = None


def read_opf(work_dir: Path) -> OPFInfo | None:
    """Parse the OPF and return a structured summary, or None on failure."""
    container = work_dir / "META-INF" / "container.xml"
    if not container.exists():
        return None
    try:
        c_root = etree.parse(str(container)).getroot()
    except etree.XMLSyntaxError:
        return None

    cnt_ns = {"cnt": "urn:oasis:names:tc:opendocument:xmlns:container"}
    rootfiles = c_root.findall(".//cnt:rootfile", cnt_ns)
    if not rootfiles:
        return None

    opf_path = work_dir / rootfiles[0].get("full-path", "")
    if not opf_path.exists():
        return None

    try:
        opf_root = etree.parse(str(opf_path)).getroot()
    except etree.XMLSyntaxError:
        return None

    opf_dir = opf_path.parent
    version = "3" if opf_root.get("version", "2").startswith("3") else "2"

    uid_attr = opf_root.get("unique-identifier", "uid")
    uid_elem = opf_root.find(f".//{{{DC_NS}}}identifier[@id='{uid_attr}']")
    if uid_elem is None:
        uid_elem = opf_root.find(f".//{{{DC_NS}}}identifier")
    uid = (uid_elem.text or "").strip() if uid_elem is not None else "unknown"

    title_elem = opf_root.find(f".//{{{DC_NS}}}title")
    title = (title_elem.text or "").strip() if title_elem is not None else "Unknown"

    manifest: dict[str, dict[str, str]] = {}
    for item in opf_root.findall(f".//{{{OPF_NS}}}item"):
        item_id = item.get("id", "")
        href = item.get("href", "")
        if item_id and href:
            manifest[item_id] = {
                "href": href,
                "media_type": item.get("media-type", ""),
                "properties": item.get("properties", ""),
            }

    spine_items: list[SpineItem] = []
    for itemref in opf_root.findall(f".//{{{OPF_NS}}}itemref"):
        idref = itemref.get("idref", "")
        info = manifest.get(idref)
        if info and info["media_type"] in ("application/xhtml+xml", "text/html"):
            abs_path = opf_dir / info["href"]
            if abs_path.exists():
                spine_items.append(SpineItem(
                    item_id=idref,
                    href=info["href"],
                    abs_path=abs_path,
                    media_type=info["media_type"],
                ))

    ncx_id = ncx_href = nav_id = nav_href = None
    for item_id, info in manifest.items():
        if info["media_type"] == "application/x-dtbncx+xml" and ncx_id is None:
            ncx_id, ncx_href = item_id, info["href"]
        if "nav" in info.get("properties", "") and nav_id is None:
            nav_id, nav_href = item_id, info["href"]

    return OPFInfo(
        path=opf_path,
        opf_dir=opf_dir,
        root=opf_root,
        uid=uid,
        title=title,
        version=version,
        spine_items=spine_items,
        manifest=manifest,
        ncx_id=ncx_id,
        ncx_href=ncx_href,
        nav_id=nav_id,
        nav_href=nav_href,
    )


def write_opf(opf: OPFInfo) -> None:
    content = etree.tostring(
        opf.root, pretty_print=True, xml_declaration=True, encoding="utf-8",
    )
    opf.path.write_bytes(content)


def content_spine_items(opf: OPFInfo) -> list[SpineItem]:
    """Spine HTML items excluding the nav document."""
    skip = {opf.nav_id} if opf.nav_id else set()
    return [item for item in opf.spine_items if item.item_id not in skip]


def next_manifest_id(opf: OPFInfo, prefix: str = "ch") -> str:
    """Return an unused manifest id like ch001."""
    existing = set(opf.manifest)
    n = 1
    while True:
        candidate = f"{prefix}{n:03d}"
        if candidate not in existing:
            return candidate
        n += 1