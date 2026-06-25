# Test Fixtures

Broken EPUB files used for pipeline testing. Each fixture is the minimal reproduction of one or more defect classes.

Copyrighted EPUBs placed **directly** in this directory are **not committed** (see `.gitignore`); to reproduce those locally, copy an EPUB matching the profile below in with the expected filename. Public-domain fixtures live in [`public-domain/`](public-domain/) and **are** committed (or fetched on demand) — see that section below — so the fixture tests run on a fresh clone and in CI.

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

#### Original set

| Filename | Defect codes | Notes |
|---|---|---|
| `jack-vance---the-men-return---jack-vance.epub` | NCX007 | navPoint src not found in ZIP |
| `the-dogtown-tourist-agency---jack-vance.epub` | NCX007, NCX008 | dual TOC problems |
| `franny-and-zooey-a-novel---j.-d.-salinge.epub` | NCX005, NCX008 | empty navMap + incomplete TOC |
| `teachings-of-the-prophet-joseph---joseph.epub` | NCX008, OPF004 | missing metadata + incomplete TOC |
| `loser-letters---mary-eberstadt.epub` | NCX008 | pure baseline incomplete TOC |
| `allanons-quest---terry-brooks.epub` | NCX008, OPF009 | wrong media types + incomplete TOC |
| `lincolns-dreams---connie-willis.epub` | NCX008, OPF009 | same combo, larger file |
| `paradeisia-origin-of-paradise---b.c.-cha.epub` | NAV004 | EPUB 3 missing toc nav |
| `after-moses-wormwood---michael-f.-kane.epub` | OPF009 | wrong media types only |
| `emphyrio---jack-vance.epub` | OPF008 | manifest items missing from ZIP |

#### Expanded set — new defect codes

| Filename | Defect codes | Notes |
|---|---|---|
| `brave-new-world.epub` | NCX005, NCX008 | empty navMap; classic dystopia |
| `i-robot.epub` | NCX005, NCX008 | empty navMap; anthology stress test |
| `the-republic.epub` | NCX005, NCX008 | empty navMap; spine=15; ancient philosophy |
| `federalist-papers.epub` | NCX005, NCX008 | empty navMap; non-fiction |
| `age-of-wonder.epub` | NCX001, OPF009 | spine missing `toc` attr; science history |
| `so-long-thanks.epub` | NCX001, OPF009 | spine missing `toc` attr; comedy sci-fi; spine=51 |
| `hidden-truth.epub` | NAV003 | EPUB 3 nav not well-formed XML (unescaped entities) |
| `sudden-rescue.epub` | NAV003 | EPUB 3 nav not well-formed XML; self-published |
| `plot-against-president.epub` | DRM001 | **Adobe ADEPT (library-loan) DRM.** Gating fixture — must be detected as unrepairable and skipped, NOT "repaired". Its encrypted bytes previously misread as NAV003. |
| `les-miserables-fr.epub` | NCX008, OPF009 | **422 spine items** — large-book stress test; French |
| `le-vicomte-bragelonne.epub` | NCX008 | **271 spine items** — large-spine stress test |
| `elon-musk.epub` | OPF009 | EPUB 3; spine=198; large modern non-fiction |

#### Variant-clustering stress fixtures (Russian novels)

These exist to battle-test Stage 1 variant clustering against Slavic naming
(full name + patronymic + surname + diminutives that share no substring).
They also carry NCX008, so they double as TOC-rebuild fixtures. See SPEC.md
→ "Hard case: Slavic naming". Ground truth (grouped aliases) will live in
`ground_truth/<slug>.json` and must be hand-verified independently of any
in-book cast list.

| Filename | Defect codes | Notes |
|---|---|---|
| `crime-and-punishment.epub` | NCX008 | Raskolnikov = Rodion Romanovich = Rodya = Rodka = Rodenka |
| `brothers-karamazov.epub` | NCX008 | three brothers, each with full name + patronymic + diminutives |
| `war-and-peace.epub` | NCX008 | huge cast, French/Russian code-switching, nicknames |

#### Defect code coverage

| Code | Meaning | Covered by |
|---|---|---|
| NCX001 | EPUB 2 `<spine>` missing `toc` attribute | age-of-wonder, so-long-thanks |
| NCX005 | `<navMap>` present but contains zero `<navPoint>` elements | brave-new-world, i-robot, the-republic, federalist-papers |
| NCX007 | navPoint `src` not found in ZIP | jack-vance men-return, dogtown-tourist |
| NCX008 | navPoint count < spine item count (incomplete TOC) | many |
| OPF004 | Required metadata field missing | teachings-of-the-prophet-joseph |
| OPF008 | Manifest item `href` missing from ZIP | emphyrio |
| OPF009 | Wrong `media-type` for manifest item | allanons-quest, lincolns-dreams, age-of-wonder, etc. |
| NAV003 | EPUB 3 nav document is not well-formed XML | hidden-truth, sudden-rescue |
| NAV004 | EPUB 3 nav document has no `epub:type="toc"` nav element | paradeisia |
| DRM001 | DRM-protected (encrypted content) — gated, unrepairable | plot-against-president |

#### Text-coherence & structural fixtures

For the Stage 3 local-coherence pass and collection/omnibus structure. See SPEC.md
→ "Local Coherence Repair" and "Collections & Editorial Apparatus".

| Fixture | Purpose |
|---|---|
| `coherence-cases.jsonl` | Validation corpus for the coherence pass. Each line: a span, its tier (A auto / B apply+flag / C world-knowledge flag / D unrecoverable / `none` already-valid / `intentional` leave-alone), expected output (or `null`), and the justifying evidence. Anchored by the real `Kelterrified`→`Kel—terrified` defect (*The Lost Years*) and the *Finnegans Wake* adversarial negatives (the `quark` coinage and the 100-letter thunderword) that must pass through **unchanged**. Committed (text, not an EPUB). |
| `complete-works-of-james-joyce.epub` | **Omnibus / "complete works" stress fixture** (Delphi). 567 spine items; Collection → Work → Chapter hierarchy; mixed genres; editorial apparatus (copyright, poem indexes, the Delphi catalogue). Critically, *Finnegans Wake* and *Dubliners* coexist in one file, forcing **per-work** register assessment. Source: Calibre library, not committed. |

### Public-domain fixtures (`public-domain/`)

So the fixture tests run out of the box (CI, fresh clones), this folder holds
open-licensed fixtures in two forms:

**Committed seeds** — tiny, hand-built EPUBs whose text is unambiguously public
domain (Charles Dickens, d. 1870). Generated by `make_seeds.py`; checked into the
repo (a few KB each).

| Seed | Profile |
|---|---|
| `pd-clean-epub3.epub` | Valid EPUB 3 with a proper nav — clean baseline / "do not break valid files" |
| `pd-broken-toc-epub2.epub` | EPUB 2 whose `toc.ncx` covers 1 of 3 chapters — NCX008 |

**Fetched corpus** — larger real-world public-domain books, downloaded on demand
into `public-domain/_fetched/` (gitignored, so no binaries bloat git):

```
python tests/fixtures/public-domain/fetch.py            # fetch all
python tests/fixtures/public-domain/fetch.py dubliners  # only matching slugs
```

`corpus.json` is the manifest (slug, source, URL, license, what each tests).
Sources and their licensing:
- **Standard Ebooks** — productions dedicated to the public domain (CC0); pristine EPUB3, ideal clean baselines.
- **Project Gutenberg** — public-domain texts; files carry the PG trademark/license boilerplate (permissive redistribution, strip the boilerplate for unencumbered use).

Add a book by appending an entry to `corpus.json`. To regenerate the seeds:
`python tests/fixtures/public-domain/make_seeds.py`.
