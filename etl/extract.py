"""Stream the gzipped wiktextract dump and keep only what the graph needs.

Outputs (in --out):
  sections.jsonl  one line per (lang, word, etymology_number, pos) entry that has
                  ancestry edges, plus every English entry (for coverage stats)
  pages.tsv       lang \t word \t etymology_number \t has_etymology_text, for every entry
"""
import argparse
import gzip
import json
import os
import sys
import time
from multiprocessing import Pool

from etl.templates import section_edges

BATCH = 2000


def is_lemma(e):
    senses = e.get("senses") or []
    if not senses:
        return False
    for s in senses:
        tags = s.get("tags") or []
        if not (s.get("form_of") or s.get("alt_of") or "form-of" in tags or "alt-of" in tags):
            return True
    return False


def first_gloss(e):
    for s in e.get("senses") or []:
        for g in s.get("glosses") or []:
            return g[:100]
    return None


def process(lines):
    sections, pages = [], []
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        lang, word = e.get("lang_code"), e.get("word")
        if not lang or not word:
            continue
        etym_no = e.get("etymology_number") or 0
        text = e.get("etymology_text") or ""
        templates = e.get("etymology_templates") or []
        pages.append(f"{lang}\t{word}\t{etym_no}\t{int(bool(text or templates))}\n")
        edges, ids, unknown = section_edges(templates, text, lang, f"{lang}|{word}") if templates else ([], [], False)
        if not edges and lang != "en":
            continue
        rec = {"l": lang, "w": word, "e": etym_no, "pos": e.get("pos"), "edges": edges}
        if ids:
            rec["ids"] = ids
        if unknown:
            rec["unk"] = True
        if lang == "en":
            rec["lemma"] = is_lemma(e)
            rec["has_ety"] = bool(text or templates)
            rec["gl"] = first_gloss(e)
        elif lang.endswith("-pro"):
            rec["gl"] = first_gloss(e)
        sections.append(json.dumps(rec, ensure_ascii=False) + "\n")
    return sections, pages


def batches(path, limit):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        buf, n = [], 0
        for line in f:
            buf.append(line)
            n += 1
            if len(buf) >= BATCH:
                yield buf
                buf = []
            if limit and n >= limit:
                break
        if buf:
            yield buf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", default="data/raw/raw-wiktextract-data.jsonl.gz")
    ap.add_argument("--out", default="data/work")
    ap.add_argument("--limit", type=int, default=0, help="only read the first N lines (for test runs)")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    t0, n_entries, n_sections = time.time(), 0, 0
    with open(os.path.join(a.out, "sections.jsonl"), "w", encoding="utf-8") as fs, \
            open(os.path.join(a.out, "pages.tsv"), "w", encoding="utf-8") as fp, Pool(a.workers) as pool:
        for sections, pages in pool.imap(process, batches(a.dump, a.limit), chunksize=4):
            fs.writelines(sections)
            fp.writelines(pages)
            n_entries += len(pages)
            n_sections += len(sections)
            if n_entries % 500_000 < BATCH:
                print(f"{n_entries:>10,} entries  {n_sections:>9,} kept  {time.time() - t0:6.0f}s", file=sys.stderr, flush=True)
    print(f"done: {n_entries:,} entries, {n_sections:,} kept, {time.time() - t0:.0f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
