import zipfile
from pathlib import Path

from click.testing import CliRunner
from colophon.cli import main, _collect_epubs


def test_version():
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def _touch_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip")


def test_collect_epubs_directory_requires_batch(tmp_path):
    import pytest
    import click

    (tmp_path / "a.epub").write_bytes(b"")
    with pytest.raises(click.UsageError):
        _collect_epubs((tmp_path,), batch=False)


def test_collect_epubs_batch_expands_directory(tmp_path):
    _touch_epub(tmp_path / "a.epub")
    _touch_epub(tmp_path / "b.epub")
    sub = tmp_path / "sub"
    sub.mkdir()
    _touch_epub(sub / "c.epub")

    found = _collect_epubs((tmp_path,), batch=True)
    names = sorted(p.name for p in found)
    assert names == ["a.epub", "b.epub", "c.epub"]


def test_collect_epubs_explicit_files(tmp_path):
    a = tmp_path / "a.epub"
    _touch_epub(a)
    found = _collect_epubs((a,), batch=False)
    assert found == [a]
