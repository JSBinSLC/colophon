# Test Fixtures

Broken EPUB files used for pipeline testing. Each fixture is the minimal reproduction of one or more defect classes.

Fixtures in this directory are **not committed to the public repo** (see `.gitignore`). To reproduce locally, copy an EPUB matching the defect profile described below into this directory with the expected filename.

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
