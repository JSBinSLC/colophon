# Test Fixtures

Broken EPUB files used for pipeline testing. Each fixture is the minimal reproduction of one or more defect classes.

Fixtures in this directory are **not committed to the public repo** (see `.gitignore`). To reproduce locally, copy an EPUB matching the defect profile described below into this directory with the expected filename.

## How to add a fixture

1. Copy the EPUB into this directory with a short slug name
2. Run `py -3 -c "from colophon.validator import validate; from pathlib import Path; [print(i.code, i.message) for i in validate(Path('tests/fixtures/yourfile.epub')).issues]"` to see its defect profile
3. Add a test block in `tests/test_qa_fixtures.py` asserting the defect codes

## Fixtures

### `the-lost-years.epub`
*Star Trek: The Original Series #51 — The Lost Years*, J. M. Dillard  
Source: Calibre 0.8.8 export, circa 2011

| Defect | Detail |
|---|---|
| Broken TOC | `toc.ncx` has 1 `navPoint` (PROLOGUE only); 26 of 27 chapters missing from navigation |
| EPUB 2 only | No `nav.xhtml`; upgrade path to EPUB 3 needed |
| Inline `@page` styles | Baked into `<head>` of every split HTML file |
| Non-semantic classes | All elements use `calibre`, `calibre1`, `calibre2`, `calibre3` — no semantic meaning |
| Reversed manifest IDs | `html28` → `index_split_000.html`, `html1` → `index_split_027.html` |
| Empty titles | `<title>Unknown</title>` in all split files |

### QA fixtures (real-world Calibre library EPUBs)

| Filename | Defect codes | Notes |
|---|---|---|
| `jack-vance---the-men-return---jack-vance.epub` | NCX007 | navPoint src not found in ZIP |
| `the-dogtown-tourist-agency---jack-vance.epub` | NCX007, NCX008 | dual TOC problems |
| `franny-and-zooey-a-novel---j.-d.-salinge.epub` | NCX008 | incomplete TOC |
| `teachings-of-the-prophet-joseph---joseph.epub` | NCX008, OPF004 | missing metadata + incomplete TOC |
| `loser-letters---mary-eberstadt.epub` | NCX008 | pure baseline incomplete TOC |
| `allanons-quest---terry-brooks.epub` | NCX008, OPF009 | wrong media types + incomplete TOC |
| `lincolns-dreams---connie-willis.epub` | NCX008, OPF009 | same combo, larger file |
| `paradeisia-origin-of-paradise---b.c.-cha.epub` | NAV004 | EPUB 3 missing toc nav |
| `after-moses-wormwood---michael-f.-kane.epub` | OPF009 | wrong media types only |
| `emphyrio---jack-vance.epub` | OPF008 | manifest items missing from ZIP |
