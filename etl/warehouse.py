"""Load one dump's pipeline results into the warehouse, for history tracking with dbt.

Reads what extract.py and run.py already wrote (data/work, data/out) plus data/raw/MANIFEST.json,
flattens it into four raw tables, and loads them as the partition for this dump:

  raw_dumps        one row per dump (source URL, Last-Modified, sha256, row counts)
  raw_sections     one row per etymology section, with a hash of its parsed ancestry edges
  raw_word_roots   one row per (English word, etymology, PIE root) the site shows
  raw_unrooted     one row per English word etymology with no root, and why

`dump_id` is the dump's Last-Modified date. Loading the same dump again replaces its partition.
Only the newest `--keep` dumps stay in the raw tables (dbt snapshots keep the history);
raw_dumps keeps every row.

  python -m etl.warehouse check --backend bigquery    # exit 0 if the published dump is not loaded yet
  python -m etl.warehouse load  --backend duckdb      # local, free: data/warehouse.duckdb
  python -m etl.warehouse load  --backend bigquery    # needs GCP_PROJECT (and google-cloud-bigquery)
"""
import argparse
import email.utils
import gzip
import hashlib
import json
import os
import sys
import time
from collections import Counter, defaultdict

from etl.download import URL, head

# column name -> type, in load order. Types are BigQuery's; duckdb gets the equivalents below.
SCHEMAS = {
    "raw_dumps": {
        "dump_id": "DATE", "url": "STRING", "last_modified": "STRING", "sha256": "STRING", "bytes": "INT64",
        "sections": "INT64", "word_roots": "INT64", "unrooted": "INT64", "loaded_at": "TIMESTAMP",
    },
    "raw_sections": {
        "dump_id": "DATE", "section_key": "STRING", "lang": "STRING", "word": "STRING", "pos": "STRING",
        "etym": "STRING", "entries": "INT64", "lemma": "BOOL", "has_ety": "BOOL", "n_edges": "INT64",
        "edges_hash": "STRING", "edges": "STRING", "gloss": "STRING",
    },
    "raw_word_roots": {
        "dump_id": "DATE", "word": "STRING", "etym": "STRING", "root_slug": "STRING", "root_term": "STRING",
        "root_kind": "STRING", "uncertain": "BOOL", "via_affix": "BOOL", "shortcut": "BOOL",
    },
    "raw_unrooted": {
        "dump_id": "DATE", "word": "STRING", "etym": "STRING", "reason": "STRING", "stuck_at": "STRING",
    },
}
DUCK_TYPES = {"DATE": "DATE", "STRING": "VARCHAR", "INT64": "BIGINT", "BOOL": "BOOLEAN", "TIMESTAMP": "TIMESTAMP"}
UNCERTAIN_FLAG, AFFIX_FLAG, SHORTCUT_FLAG = 1, 2, 4   # same as etl/export.py


def dump_id_of(last_modified):
    """'Fri, 30 Oct 2026 20:48:24 GMT' -> '2026-10-30'."""
    return email.utils.parsedate_to_datetime(last_modified).date().isoformat()


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(s):
    return hashlib.sha1(s.encode()).hexdigest()[:16]


# ------------------------------------------------------------------ rows

def section_rows(path, dump_id):
    """One row per (lang, word, pos, etymology number).

    About 0.5% of keys appear more than once (two entries for the same part of speech in one
    etymology). They are merged, with a hash over every entry's edges, so the key stays unique.
    Only the parsed edges are hashed: an edit that changes prose but no ancestry is not a change.
    """
    def key(d):
        return (d["l"], d["w"], d.get("pos") or "", str(d["e"]))

    seen = Counter()
    with open(path, encoding="utf-8") as f:
        for line in f:
            seen[key(json.loads(line))] += 1
    dupes = defaultdict(list)

    def row(k, entries):
        edges = [e for d in entries for e in d["edges"]]
        hashes = sorted(digest(canonical(d["edges"])) for d in entries)
        return {
            "dump_id": dump_id, "section_key": "|".join(map(str, k)), "lang": k[0], "word": k[1], "pos": k[2],
            "etym": k[3], "entries": len(entries), "lemma": any(d.get("lemma") for d in entries),
            "has_ety": any(d.get("has_ety") for d in entries), "n_edges": len(edges),
            "edges_hash": hashes[0] if len(hashes) == 1 else digest("+".join(hashes)),
            "edges": canonical(edges), "gloss": entries[0].get("gl"),
        }

    with open(path, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            k = key(d)
            if seen[k] == 1:
                yield row(k, [d])
            else:
                dupes[k].append(d)
                if len(dupes[k]) == seen[k]:
                    yield row(k, dupes.pop(k))


def word_root_rows(index, dump_id):
    roots = index["roots"]
    for word, hits in index["words"].items():
        for root_idx, etym, flags in hits:
            r = roots[root_idx]
            yield {
                "dump_id": dump_id, "word": word, "etym": str(etym), "root_slug": r["slug"], "root_term": r["term"],
                "root_kind": r["kind"], "uncertain": bool(flags & UNCERTAIN_FLAG),
                "via_affix": bool(flags & AFFIX_FLAG), "shortcut": bool(flags & SHORTCUT_FLAG),
            }


def unrooted_rows(unrooted, dump_id):
    for word, items in unrooted.items():
        for etym, reason, stuck in items:
            yield {"dump_id": dump_id, "word": word, "etym": str(etym), "reason": reason, "stuck_at": stuck}


def write_ndjson(rows, path):
    n = 0
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
    return n


def build_files(work, out, raw, stage):
    """Write one gzipped NDJSON file per raw table. Returns (dump_id, {table: path})."""
    with open(os.path.join(raw, "MANIFEST.json")) as f:
        manifest = json.load(f)
    dump_id = dump_id_of(manifest["last_modified"])
    d = os.path.join(stage, dump_id)
    os.makedirs(d, exist_ok=True)
    files = {t: os.path.join(d, f"{t}.ndjson.gz") for t in SCHEMAS}
    with open(os.path.join(out, "index.json"), encoding="utf-8") as f:
        index = json.load(f)
    with open(os.path.join(out, "unrooted.json"), encoding="utf-8") as f:
        unrooted = json.load(f)
    counts = {
        "sections": write_ndjson(section_rows(os.path.join(work, "sections.jsonl"), dump_id), files["raw_sections"]),
        "word_roots": write_ndjson(word_root_rows(index, dump_id), files["raw_word_roots"]),
        "unrooted": write_ndjson(unrooted_rows(unrooted, dump_id), files["raw_unrooted"]),
    }
    write_ndjson([{
        "dump_id": dump_id, "url": manifest["url"], "last_modified": manifest["last_modified"],
        "sha256": manifest["sha256"], "bytes": manifest["bytes"], **counts,
        "loaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }], files["raw_dumps"])
    print(f"{dump_id}: " + ", ".join(f"{v:,} {k}" for k, v in counts.items()), file=sys.stderr)
    return dump_id, files


# ------------------------------------------------------------------ backends

class DuckDB:
    def __init__(self, path, schema):
        import duckdb
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.con, self.schema = duckdb.connect(path), schema
        self.con.execute(f"create schema if not exists {schema}")
        for t, cols in SCHEMAS.items():
            ddl = ", ".join(f"{c} {DUCK_TYPES[ty]}" for c, ty in cols.items())
            self.con.execute(f"create table if not exists {schema}.{t} ({ddl})")

    def loaded(self):
        return {str(r[0]) for r in self.con.execute(f"select dump_id from {self.schema}.raw_dumps").fetchall()}

    def load(self, dump_id, files):
        cols = lambda t: "{" + ", ".join(f"'{c}': '{DUCK_TYPES[ty]}'" for c, ty in SCHEMAS[t].items()) + "}"
        self.con.execute("begin")
        for t, path in files.items():
            self.con.execute(f"delete from {self.schema}.{t} where dump_id = ?", [dump_id])
            self.con.execute(f"insert into {self.schema}.{t} by name select * from read_json(?, columns = {cols(t)}, "
                             f"format = 'newline_delimited')", [path])
        self.con.execute("commit")

    def prune(self, keep):
        kept = sorted(self.loaded())[-keep:]
        if kept:
            for t in SCHEMAS:
                if t != "raw_dumps":
                    self.con.execute(f"delete from {self.schema}.{t} where dump_id < ?", [kept[0]])


class BigQuery:
    def __init__(self, project, dataset, location):
        from google.cloud import bigquery
        self.bq, self.client = bigquery, bigquery.Client(project=project, location=location)
        self.dataset = f"{project}.{dataset}"
        self.client.create_dataset(self.dataset, exists_ok=True)

    def _schema(self, t):
        return [self.bq.SchemaField(c, ty) for c, ty in SCHEMAS[t].items()]

    def loaded(self):
        try:
            rows = self.client.query(f"select dump_id from `{self.dataset}.raw_dumps`").result()
        except Exception as e:   # first run: the table does not exist yet
            if "Not found" in str(e):
                return set()
            raise
        return {r.dump_id.isoformat() for r in rows}

    def load(self, dump_id, files):
        part = dump_id.replace("-", "")
        for t, path in files.items():
            cfg = self.bq.LoadJobConfig(
                schema=self._schema(t), source_format=self.bq.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=self.bq.WriteDisposition.WRITE_TRUNCATE,   # replaces just this partition
                time_partitioning=self.bq.TimePartitioning(field="dump_id"),
            )
            with open(path, "rb") as f:
                self.client.load_table_from_file(f, f"{self.dataset}.{t}${part}", job_config=cfg).result()

    def prune(self, keep):
        kept = sorted(self.loaded())[-keep:]
        if kept:
            for t in SCHEMAS:
                if t != "raw_dumps":
                    self.client.query(f"delete from `{self.dataset}.{t}` where dump_id < '{kept[0]}'").result()


def backend(a):
    if a.backend == "duckdb":
        return DuckDB(a.duckdb, a.schema)
    project = a.project or os.environ.get("GCP_PROJECT")
    if not project:
        sys.exit("set --project or GCP_PROJECT")
    return BigQuery(project, a.dataset, a.location)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["check", "load"])
    ap.add_argument("--backend", choices=["duckdb", "bigquery"], default="duckdb")
    ap.add_argument("--duckdb", default=os.environ.get("DUCKDB_PATH", "data/warehouse.duckdb"))
    ap.add_argument("--schema", default="raw", help="duckdb schema for the raw tables")
    ap.add_argument("--project", default=None)
    ap.add_argument("--dataset", default=os.environ.get("BQ_RAW_DATASET", "etymodendron_raw"))
    ap.add_argument("--location", default=os.environ.get("BQ_LOCATION", "US"))
    ap.add_argument("--work", default="data/work")
    ap.add_argument("--out", default="data/out")
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--stage", default="data/load")
    ap.add_argument("--keep", type=int, default=3, help="raw dumps to keep (history lives in the snapshots)")
    ap.add_argument("--url", default=URL)
    a = ap.parse_args(argv)
    wh = backend(a)

    if a.command == "check":
        dump_id = dump_id_of(head(a.url)[1])
        new = dump_id not in wh.loaded()
        print(f"published dump {dump_id}: {'new' if new else 'already loaded'}")
        if out := os.environ.get("GITHUB_OUTPUT"):
            with open(out, "a") as f:
                f.write(f"dump_id={dump_id}\nnew={'true' if new else 'false'}\n")
        return 0

    dump_id, files = build_files(a.work, a.out, a.raw, a.stage)
    wh.load(dump_id, files)
    wh.prune(a.keep)
    print(f"loaded {dump_id} ({a.backend})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
