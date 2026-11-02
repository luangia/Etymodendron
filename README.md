# Etymodendron — data pipeline

Builds static JSON of English words grouped by Proto-Indo-European (PIE) ancestor, from the
English Wiktionary extract published by [kaikki.org](https://kaikki.org) (wiktextract).
Data is CC BY-SA (Wiktionary); keep attribution when publishing.

```bash
python3 -m etl.download   # ~3 GB → data/raw/ (resumable, writes MANIFEST.json with sha256)
python3 -m etl.extract    # streams the .gz → data/work/ (~6 min on 10 cores)
python3 -m etl.run        # graph → data/out/ + validation_report.md
python3 -m pytest tests
```
`python3 -m etl.extract --limit 300000 --out data/work_sample` gives a fast partial run.

## How ancestry is read

| Source | Edges | Trust |
|---|---|---|
| `{{etymon}}` | explicit child → parent, with ids and `<unc>` | used everywhere |
| `inh` / `bor` / `der` / `af` … on a page | that page's word → each source | used everywhere |
| order of those templates in the prose ("from A, from B") | A → B (`via: "sequence"`) | used **only** when tracing from the page that states it; `confirmed` if B's own page agrees |
| `{{root}}` | word → PIE root (`type: "root"`) | used everywhere |
| `cog`, `m`, `doublet`, surface analyses, "influenced by" | none | never ancestry |

Edges are `uncertain` when the template says so or the sentence before it hedges ("possibly",
"perhaps", "?", "A or B", …); `evidence` quotes the text. Links into a page with several
etymologies are followed only if an `{{etymon}}` id, a single section, or agreement between all
sections decides it; otherwise the word is listed as unrooted (`ambiguous_homograph`).

## Output (`data/out/`)

- `roots/<slug>.json` — one per PIE node that is a root (`*bʰer-`) or a PIE word with no
  certain parent root (`*ph₂tḗr`). `tree` runs PIE → … → English; each node's `edge` describes
  its link to the node above (`type`, `via`, `uncertain`, `evidence`, `confirmed`, `link`,
  `sources`). English leaves carry `etym`, `gloss`, `pos`, `path_uncertain`, `via_affix`.
  `parents` lists PIE nodes above this one (e.g. `*ph₂tḗr` → `*peh₂-`, uncertain).
- `index.json` — `words[word] = [[root index, etymology number, flags]]`, flags 1 = uncertain
  step on the path, 2 = path goes through an affix (*trans-*, *-ment*); `roots[i]` gives slug and term.
- `unrooted.json` — English lemmas with no PIE ancestor and the reason.
- `validation_report.md` — coverage, words per root, graph health, sample trees.
