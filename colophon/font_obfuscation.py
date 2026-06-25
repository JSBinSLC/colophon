"""IDPF / Adobe font obfuscation helpers.

EPUB embeds fonts XOR-mangled with a SHA-1 key derived from the publication
identifier. If the UID drifts during repair, fonts render as garbage. Re-keying
deobfuscates with the source UID and re-obfuscates with the canonical OPF UID.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

from lxml import etree

log = logging.getLogger(__name__)

IDPF_ALGORITHM = "http://www.idpf.org/2008/embedding"
ADOBE_ALGORITHM = "http://ns.adobe.com/pdf/enc#RC"
_FONT_EXTS = {".otf", ".ttf", ".woff", ".woff2"}
_OBFUSCATE_BYTES = 1040
_ENC_NS = {"enc": "urn:oasis:names:tc:opendocument:xmlns:container"}


def _sha1_key(identifier: str) -> bytes:
    return hashlib.sha1(identifier.encode("utf-8")).digest()


def xor_font(data: bytearray, identifier: str, *, nbytes: int = _OBFUSCATE_BYTES) -> None:
    """Apply or remove IDPF font obfuscation (XOR is self-inverse)."""
    key = _sha1_key(identifier)
    limit = min(nbytes, len(data))
    for i in range(limit):
        data[i] ^= key[i % len(key)]


def find_obfuscated_fonts(work_dir: Path) -> list[dict[str, str]]:
    """Return obfuscated font entries from META-INF/encryption.xml."""
    enc_path = work_dir / "META-INF" / "encryption.xml"
    if not enc_path.exists():
        return []

    try:
        root = etree.parse(str(enc_path)).getroot()
    except etree.XMLSyntaxError:
        return []

    fonts: list[dict[str, str]] = []
    for enc_data in root.findall(".//{http://www.w3.org/2001/04/xmlenc#}EncryptedData"):
        method = enc_data.find("{http://www.w3.org/2001/04/xmlenc#}EncryptionMethod")
        algo = method.get("Algorithm", "") if method is not None else ""
        if algo not in (IDPF_ALGORITHM, ADOBE_ALGORITHM):
            continue
        for ref in enc_data.findall(".//{http://www.w3.org/2001/04/xmlenc#}CipherReference"):
            uri = ref.get("URI", "")
            if Path(uri).suffix.lower() in _FONT_EXTS:
                fonts.append({"uri": uri, "algorithm": algo})
    return fonts


def rekey_obfuscated_fonts(
    work_dir: Path,
    canonical_uid: str,
    source_uid: str | None = None,
) -> int:
    """Re-key obfuscated fonts to canonical_uid. Returns count re-keyed."""
    if not canonical_uid or (source_uid and source_uid == canonical_uid):
        return 0

    old_uid = source_uid or canonical_uid
    changed = 0
    for entry in find_obfuscated_fonts(work_dir):
        font_path = work_dir / entry["uri"]
        if not font_path.exists():
            log.warning("Font obfuscation: %s listed in encryption.xml but missing", entry["uri"])
            continue
        data = bytearray(font_path.read_bytes())
        xor_font(data, old_uid)
        if source_uid and source_uid != canonical_uid:
            xor_font(data, canonical_uid)
        font_path.write_bytes(data)
        changed += 1
        log.info("Font obfuscation: re-keyed %s to UID %s", entry["uri"], canonical_uid[:16])
    return changed


def read_publication_uid(work_dir: Path) -> str | None:
    """Read the OPF unique-identifier text."""
    from colophon.stages.opf_utils import DC_NS, read_opf

    opf = read_opf(work_dir)
    if opf is None:
        return None
    return opf.uid or None