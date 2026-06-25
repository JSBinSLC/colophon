"""Tests for IDPF font obfuscation re-keying."""
from __future__ import annotations

from colophon.font_obfuscation import (
    _sha1_key,
    find_obfuscated_fonts,
    rekey_obfuscated_fonts,
    xor_font,
)

ADOBE_ENCRYPTION_XML = """<?xml version="1.0"?>
<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <EncryptedData xmlns="http://www.w3.org/2001/04/xmlenc#">
    <EncryptionMethod Algorithm="http://ns.adobe.com/pdf/enc#RC"/>
    <CipherData><CipherReference URI="OEBPS/font.otf"/></CipherData>
  </EncryptedData>
</encryption>"""

ENCRYPTION_XML = """<?xml version="1.0"?>
<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <EncryptedData xmlns="http://www.w3.org/2001/04/xmlenc#">
    <EncryptionMethod Algorithm="http://www.idpf.org/2008/embedding"/>
    <CipherData><CipherReference URI="OEBPS/font.otf"/></CipherData>
  </EncryptedData>
</encryption>"""


def test_xor_font_is_self_inverse():
    uid = "urn:uuid:test-book"
    original = bytearray(b"FONTDATA" + b"\x00" * 32)
    expected = original.copy()
    xor_font(original, uid)
    assert original != expected
    xor_font(original, uid)
    assert original == expected


def test_find_obfuscated_fonts(tmp_path):
    (tmp_path / "META-INF").mkdir()
    (tmp_path / "META-INF" / "encryption.xml").write_text(ENCRYPTION_XML, encoding="utf-8")
    fonts = find_obfuscated_fonts(tmp_path)
    assert len(fonts) == 1
    assert fonts[0]["uri"] == "OEBPS/font.otf"


def test_rekey_changes_font_bytes(tmp_path):
    (tmp_path / "META-INF").mkdir()
    (tmp_path / "OEBPS").mkdir(parents=True)
    (tmp_path / "META-INF" / "encryption.xml").write_text(ENCRYPTION_XML, encoding="utf-8")
    font_path = tmp_path / "OEBPS" / "font.otf"
    plain = bytearray(b"\x01\x02\x03\x04" + b"\x00" * 100)
    font_path.write_bytes(plain)

    old_uid = "old-id"
    new_uid = "new-id"
    obfuscated = bytearray(plain)
    xor_font(obfuscated, old_uid)
    font_path.write_bytes(obfuscated)

    count = rekey_obfuscated_fonts(tmp_path, canonical_uid=new_uid, source_uid=old_uid)
    assert count == 1
    result = font_path.read_bytes()
    expected = bytearray(plain)
    xor_font(expected, new_uid)
    assert result == bytes(expected)


def test_rekey_noop_without_source_uid(tmp_path):
    """No source UID -> we don't know the obfuscation key, so do nothing
    (never deobfuscate-and-leave-plaintext)."""
    (tmp_path / "META-INF").mkdir()
    (tmp_path / "OEBPS").mkdir(parents=True)
    (tmp_path / "META-INF" / "encryption.xml").write_text(ENCRYPTION_XML, encoding="utf-8")
    font_path = tmp_path / "OEBPS" / "font.otf"
    obfuscated = bytearray(b"\x01\x02\x03\x04" + b"\x00" * 100)
    font_path.write_bytes(bytes(obfuscated))

    count = rekey_obfuscated_fonts(tmp_path, canonical_uid="new-id", source_uid=None)
    assert count == 0
    assert font_path.read_bytes() == bytes(obfuscated)  # untouched


def test_rekey_skips_adobe_algorithm(tmp_path):
    """Adobe-obfuscated fonts use a different scheme; re-keying with IDPF math
    would corrupt them, so they are left as-is."""
    (tmp_path / "META-INF").mkdir()
    (tmp_path / "OEBPS").mkdir(parents=True)
    (tmp_path / "META-INF" / "encryption.xml").write_text(ADOBE_ENCRYPTION_XML, encoding="utf-8")
    font_path = tmp_path / "OEBPS" / "font.otf"
    obfuscated = bytearray(b"\x01\x02\x03\x04" + b"\x00" * 100)
    font_path.write_bytes(bytes(obfuscated))

    count = rekey_obfuscated_fonts(tmp_path, canonical_uid="new-id", source_uid="old-id")
    assert count == 0
    assert font_path.read_bytes() == bytes(obfuscated)  # untouched


def test_sha1_key_ignores_whitespace():
    """IDPF strips all whitespace from the identifier before hashing."""
    assert _sha1_key("urn:uuid:abc-123") == _sha1_key("  urn:uuid:abc-123\n ")