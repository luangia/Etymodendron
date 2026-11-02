"""Validation report: coverage numbers plus readable sample trees for spot-checking."""
import json
import os
import re
import statistics
from collections import Counter

from etl.export import UNCERTAIN_FLAG, AFFIX_FLAG, build_tree, display
from etl.graph import PIE, node_lang

SAMPLES = ["bʰer-", "ph₂tḗr", "gʷem-"]
NON_CORE_POS = {"name", "phrase", "proverb", "prefix", "suffix", "infix", "interfix", "circumfix",
                "affix", "symbol", "character", "abbrev", "contraction", "punct", "prep_phrase"}
MAX_TREE_LINES = 250


def render(node, prefix="", last=True, lines=None, top=True):
    lines = [] if lines is None else lines
    e = node.get("edge")
    label = f"{node['lang']} {node['term']}"
    if node.get("etym"):
        label += f" (etym {node['etym']})"
    if e:
        tag = e["type"]
        if e.get("uncertain"):
            tag += ", UNCERTAIN"
        if e["via"] in ("sequence",):
            tag += ", from prose order" + ("" if e.get("confirmed") else " (unconfirmed)")
        if e.get("link"):
            tag += f", link {e['link']}"
        label += f"   [{tag}]"
        if e.get("uncertain") and e.get("evidence"):
            label += f'  « {e["evidence"][:90]} »'
    if node.get("gloss") and node["lang"] == "en":
        label += f"  — {node['gloss'][:60]}"
    if node.get("via_affix"):
        label += "  {via affix}"
    lines.append(label if top else prefix + ("└─ " if last else "├─ ") + label)
    kids = node.get("children", [])
    for i, c in enumerate(kids):
        render(c, "" if top else prefix + ("   " if last else "│  "), i == len(kids) - 1, lines, False)
    return lines


def is_core(word, groups):
    return re.fullmatch(r"[a-z]+", word) and any(g["pos"] - NON_CORE_POS for g in groups)


def write_report(G, outdir, members, per_group, tops, index, unrooted):
    L = []
    lemma_words = {}
    for g, grp in G.groups.items():
        if g[0] == "en" and grp["lemma"]:
            lemma_words.setdefault(g[1], []).append(grp)
    rooted = set(index["words"])
    rooted_lemmas = rooted & lemma_words.keys()
    core = {w for w, gs in lemma_words.items() if is_core(w, gs)}
    sizes = [r["words"] for r in index["roots"]]
    kinds = Counter(r["kind"] for r in index["roots"])

    # how each rooted word got there
    only_root_tmpl, only_uncertain, only_affix = 0, 0, 0
    for w, hits in index["words"].items():
        if all(h[2] & UNCERTAIN_FLAG for h in hits):
            only_uncertain += 1
        if all(h[2] & AFFIX_FLAG for h in hits):
            only_affix += 1
    for g, res in per_group.items():
        paths = [p for r, (s, p) in res.items() if r in tops]
        if paths and all(len(p) == 1 and G.edges[p[0]].type == "root" for p in paths):
            only_root_tmpl += 1

    def pct(a, b):
        return f"{a:,} / {b:,} ({100 * a / b:.1f}%)" if b else "n/a"

    L += ["# Etymodendron — validation report", ""]
    manifest = os.path.join("data", "raw", "MANIFEST.json")
    if os.path.exists(manifest):
        m = json.load(open(manifest))
        L += [f"Source: `{m['url']}` (Last-Modified {m['last_modified']}, sha256 `{m['sha256'][:16]}…`)", ""]
    L += ["## Coverage", "",
          f"- PIE files written: **{len(index['roots']):,}** "
          f"({kinds['root']:,} roots ending in `-`, {kinds['lexeme']:,} PIE words with no certain parent root)",
          f"- English lemmas reaching a PIE file: **{pct(len(rooted_lemmas), len(lemma_words))}**",
          f"- …core vocabulary only (lowercase a–z, not names/phrases/affixes): "
          f"**{pct(len(rooted_lemmas & core), len(core))}**",
          f"- Rooted words whose every path has an uncertain step: {pct(only_uncertain, len(rooted))}",
          f"- Rooted words reached only through an affix (e.g. *trans-*): {pct(only_affix, len(rooted))}",
          f"- English sections rooted only through a `{{{{root}}}}` template (no chain through languages): "
          f"{only_root_tmpl:,}", ""]

    L += ["### Why English lemmas have no root", "",
          "Per word, the reason of its first unrooted etymology section.", "", "| reason | words | core |", "|---|---:|---:|"]
    reasons = Counter(v[0][1] for v in unrooted.values())
    core_reasons = Counter(v[0][1] for w, v in unrooted.items() if w in core)
    explain = {
        "no_etymology": "no etymology section at all",
        "no_ancestry_templates": "etymology prose without ancestry templates (compounds in plain text, 'see X', …)",
        "unknown_origin": "Wiktionary says unknown / uncertain origin",
        "non_pie_or_incomplete": "chain ends at a non-PIE source or at an entry with no further etymology",
        "proto_language_no_pie": "reaches a proto-language (e.g. Proto-Germanic) but no PIE is given",
        "chain_broken_unresolved": "chain stops at a link with no matching page",
        "ambiguous_homograph": "chain hits a page with several etymologies and no way to pick one",
        "pie_suffix_only": "reaches only a PIE suffix",
    }
    for r, n in reasons.most_common():
        L.append(f"| `{r}` — {explain.get(r, '')} | {n:,} | {core_reasons[r]:,} |")
    L.append("")

    L += ["## Words per PIE file", "",
          f"- median {statistics.median(sizes) if sizes else 0}, mean {statistics.mean(sizes) if sizes else 0:.1f}, "
          f"max {max(sizes) if sizes else 0}",
          f"- files with exactly 1 English word: {sum(1 for s in sizes if s == 1):,}", ""]
    buckets = [(1, 1), (2, 5), (6, 20), (21, 100), (101, 500), (501, 10 ** 9)]
    L += ["| English words | files |", "|---|---:|"]
    for lo, hi in buckets:
        L.append(f"| {lo}{'' if lo == hi else ('+' if hi > 10 ** 8 else f'–{hi}')} | "
                 f"{sum(1 for s in sizes if lo <= s <= hi):,} |")
    L += ["", "Top 25:", "", "| PIE | kind | English words |", "|---|---|---:|"]
    for r in index["roots"][:25]:
        L.append(f"| {r['term']} | {r['kind']} | {r['words']:,} |")
    L.append("")

    L += ["## Graph health", ""]
    edge_types, vias = Counter(), Counter()
    for grp in G.groups.values():
        for e in grp["edges"]:
            edge_types[e["t"]] += 1
            vias[e["via"]] += 1
    for es in [*G.foreign.values(), *(x for m in G.local.values() for x in m.values())]:
        for e in es:
            edge_types[e["t"]] += 1
            vias[e["via"]] += 1
    L.append("- Extracted edges by type: " + ", ".join(f"{k} {v:,}" for k, v in edge_types.most_common()))
    L.append("- …by source: " + ", ".join(f"{k} {v:,}" for k, v in vias.most_common())
             + " (`sequence` = implied by prose order; used only for words traced from the page that states it)")
    tot = sum(v for k, v in G.stats.items() if k.startswith("links_"))
    L.append(f"- Link resolution: exact {pct(G.stats['links_exact'], tot)}, diacritic-insensitive "
             f"{pct(G.stats['links_loose'], tot)}, unresolved {pct(G.stats['links_unresolved'], tot)}")
    L.append(f"- Pages where a link could not pick between homographs: {len(G.ambiguous):,} "
             f"(top: {', '.join(f'{k} ×{v}' for k, v in sorted(G.ambiguous.items(), key=lambda x: -x[1])[:8])})")
    L.append(f"- Links followed into the only section that has data on a multi-etymology page "
             f"(flagged uncertain): {sum(G.guessed.values()):,}")
    L.append(f"- Nodes on a cycle (cut, not followed twice): {len(G.cycles):,}"
             + (f" e.g. {', '.join(sorted(G.cycles)[:6])}" if G.cycles else ""))
    L.append("")

    L += ["## Sample trees", "",
          "Read top-down: PIE → … → English. Each line shows the step's type; `UNCERTAIN` steps quote "
          "the wording that triggered the flag; `from prose order` means the link was inferred from "
          "\"from A, from B\" order on an English page (`unconfirmed` = the intermediate page does not state it itself).", ""]
    for term in SAMPLES:
        key = f"{PIE}|{term}"
        mems = members.get(key, [])
        L.append(f"### *{term}")
        L.append("")
        if not mems:
            L += ["No English word reaches this node in the data.", ""]
            continue
        status = "own file" if key in tops else "no own file (has a certain parent root; shown here for checking)"
        res, _ = G.results_for(key)
        parents = [f"{display(r)}{' (uncertain)' if s[0] else ''}" for r, (s, _) in res.items() if r != key]
        L.append(f"{len({g[1] for g, _, _ in mems})} English words · {status}"
                 + (f" · parent PIE: {', '.join(parents)}" if parents else ""))
        L += ["", "```"]
        lines = render(build_tree(G, key, mems))
        L += lines[:MAX_TREE_LINES]
        if len(lines) > MAX_TREE_LINES:
            L.append(f"… {len(lines) - MAX_TREE_LINES} more lines in the JSON file")
        L += ["```", ""]
    with open(os.path.join(outdir, "validation_report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
