# Etymodendron

A Python pipeline that builds static JSON of English words grouped by Proto-Indo-European (PIE) ancestor, from the
English Wiktionary extract published by [kaikki.org](https://kaikki.org) (wiktextract).
Data is CC BY-SA (Wiktionary); keep attribution when publishing.

```bash
python3 -m etl.download   # ~3 GB → data/raw/ (resumable, writes MANIFEST.json with sha256)
python3 -m etl.extract    # streams the .gz → data/work/ (~6 min on 10 cores)
python3 -m etl.run        # graph → data/out/ + validation_report.md
python3 -m pytest tests
```
`python3 -m etl.extract --limit 300000 --out data/work_sample` gives a fast partial run.

## Web app (`web/`)

Vite + TypeScript + D3. A static site that reads the JSON above.

```bash
cd web
npm install
npm run dev       # copies ../data/out into public/data, then serves on :5173
npm run build     # → web/dist (static; deploy anywhere, works from a sub-path)
```

- **Search**: prefix autocomplete over every English word in `index.json` (press `/` to focus).
- **Root view**: radial tree with the PIE node at the centre, intermediate forms on rings by depth,
  English words on the outer ring. Edge colour = the branch the path took after leaving PIE
  (Germanic / Latin & Romance / Greek / other); grey = Wiktionary links the word straight to the
  root without stating a route. Dashed = uncertain step.
- **Click a word** for its ancestry chain, gloss, link types, and Wiktionary links; **click an
  intermediate node** to re-centre on it (breadcrumbs lead back).
- **Surprising cognates**: the panel picks words from the same ancestor that came in through
  different branches (father / pater / patriot) and can highlight their routes on the tree.
- English words built on another English word (*fatherhood*) are listed under that word rather
  than drawn; affix-only paths are hidden unless the checkbox is on.
- State lives in the URL hash (`#r=<root>&c=<node>&w=<word>`), so views can be shared.

### Deploying (Cloudflare Pages)

The site is built locally (the data is not in git) and the finished `web/dist` is uploaded:

```bash
cd web
npx wrangler login     # once: opens the browser to authorise your Cloudflare account
npm run deploy         # build → check Pages limits → upload to the "etymodendron" project
```

The first deploy creates the project and prints its `*.pages.dev` URL; add a custom domain in the
Cloudflare dashboard if you want one. `npm run check-dist` fails early if the build ever exceeds
Pages' limits (20,000 files, 25 MB per file). `web/public/_headers` sets caching: hashed app
bundles are immutable, `data/` refreshes within an hour of a redeploy.

## Warehouse: history across dumps (`warehouse/`)

kaikki.org republishes the extract regularly. Each dump is loaded into a warehouse and dbt tracks
how etymologies, and the roots the site shows, change from one dump to the next.

```text
etl.download → etl.extract → etl.run → etl.warehouse load → dbt build
                                        raw_* tables          staging → snapshots (SCD2) → marts → data tests
```

- **`etl/warehouse.py`** flattens `data/work` and `data/out` into four raw tables, partitioned by
  `dump_id` (the dump's Last-Modified date): `raw_dumps`, `raw_sections` (3.47M rows, one per
  lang/word/pos/etymology, with a hash of the parsed edges), `raw_word_roots` (668K) and
  `raw_unrooted` (519K). Reloading a dump replaces its partition; only the newest 3 dumps stay in
  the raw tables (`--keep`), since the snapshots hold the history. About 1 GB per dump.
- **Snapshots** (dbt `check` strategy, SCD Type 2): `snap_sections` versions a section only when
  its `edges_hash` changes (prose edits that change no ancestry are not changes);
  `snap_word_status` versions a word's set of roots. A section that disappears is closed
  (`hard_deletes: invalidate`).
- **Marts** (incremental, one partition per dump):
  - `fct_dump_summary`: coverage per dump, with deltas (matches `validation_report.md`).
  - `fct_section_changes`: added / removed / edited / renumbered. Sections are matched by content
    first, so an etymology inserted at the top of a page is one *added* and some *renumbered*,
    not every section *edited*.
  - `fct_word_root_changes`: gained_root / lost_root / roots_changed / added_word / removed_word.
- **Data tests**: keys unique and not null, accepted values, at most one open snapshot version
  per key, and two guards that fail the run on a parsing regression: the section count moves more
  than 5% between dumps, or coverage drops more than 1 point (`vars` in `dbt_project.yml`).

Locally, free, with duckdb:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-warehouse.txt
.venv/bin/python -m etl.warehouse load --backend duckdb     # → data/warehouse.duckdb
cd warehouse && ../.venv/bin/dbt build --profiles-dir .
```

On BigQuery: `DBT_TARGET=prod GCP_PROJECT=<project>`, and `--backend bigquery` for the loader
(auth is Application Default Credentials, e.g. `gcloud auth application-default login`).
Enable billing on the project: the BigQuery sandbox expires tables after 60 days, which would
delete the snapshots. Usage stays inside the free tier (about 5 GB stored, a few GB scanned a week).

**CI** (`.github/workflows/ci.yml`): pytest on every PR, including two synthetic dumps through the
loader and a full `dbt build` on duckdb, so snapshots, change types and data tests are checked
with no cloud account. **Weekly** (`.github/workflows/weekly.yml`): Mondays, if the published dump
is new, run the pipeline, load BigQuery, `dbt build` and deploy the site; a failing data test
fails the run before the deploy. Step-by-step setup: [`docs/SETUP.md`](docs/SETUP.md). It
needs the repo variable `GCP_PROJECT` and the secrets `GCP_WORKLOAD_IDENTITY_PROVIDER` and
`GCP_SERVICE_ACCOUNT` (Workload Identity Federation; the service account needs BigQuery Data
Editor and Job User), plus `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` for the deploy. A full run peaks at 5.3 GB of memory.

## Licenses

The generated data is derived from Wiktionary and is CC BY-SA 4.0 — see `DATA_LICENSE.md`.

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
  step on the path, 2 = path goes through an affix (*trans-*, *-ment*), 4 = linked straight to the
  root by `{{root}}` (no route stated); `roots[i]` gives slug and term.
- `languages.json` — language code → name.
- `unrooted.json` — English lemmas with no PIE ancestor and the reason.
- `validation_report.md` — coverage, words per root, graph health, sample trees.
