"""Tests for collection / omnibus detection."""
from __future__ import annotations

from colophon.stages.collection import _classify_entry, register_for_href


def test_classify_grouping_label():
    assert _classify_entry("The Novels") == "grouping"


def test_classify_apparatus():
    assert _classify_entry("Copyright") == "apparatus"


def test_classify_work():
    assert _classify_entry("Ulysses") == "work"


def test_register_for_href_neologistic():
    works = [
        {"title": "Finnegans Wake", "hrefs": ["wake.xhtml"], "kind": "work", "register": "neologistic"},
        {"title": "Dubliners", "hrefs": ["dub.xhtml"], "kind": "work", "register": "conventional"},
    ]
    assert register_for_href(works, "OEBPS/wake.xhtml") == "neologistic"
    assert register_for_href(works, "dub.xhtml") == "conventional"