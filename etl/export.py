"""Write per-root JSON trees, the search index and the unrooted list."""
import hashlib
import json
import os
import re
import unicodedata
from collections import defaultdict

from etl.graph import PIE, is_bound, node_lang, node_term, pie_kind

ASCII_MAP = str.maketrans({"ʰ": "h", "ʷ": "w", "₁": "1", "₂": "2", "₃": "3", "ₓ": "x", "ǵ": "g", "ḱ": "k",
                           "ʲ": "j", "ə": "e", "þ": "th", "ð": "dh", "æ": "ae", "ŋ": "ng"})
UNCERTAIN_FLAG, AFFIX_FLAG = 1, 2


def slug(term):
    t = unicodedata.normalize("NFKD", term.translate(ASCII_MAP))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-") or "x"
    return f"{t}-{hashlib.sha1(term.encode()).hexdigest()[:6]}"


def display(key, form=None):
    lang, term = node_lang(key), form or node_term(key)
    if lang.endswith("-pro") and not term.startswith("*"):
        term = "*" + term
    return term


def collect(G):
    """Trace every English section; return members per PIE node and per-section results."""
    members = defaultdict(list)          # pie node -> [(gkey, score, path)]
    per_group = {}
    for g in G.groups:
        if g[0] != "en":
            continue
        res = G.compute(f"en|{g[1]}", g)
        per_group[g] = res
        for pie, (score, path) in res.items():
            members[pie].append((g, score, path))
    tops = {p for p in members if G.is_top(p)}
    return members, per_group, tops


def _path_flags(G, score, path):
    flags = UNCERTAIN_FLAG if score[0] else 0
    if any(is_bound(G.edges[e].parent) and node_lang(G.edges[e].parent) != PIE for e in path[:-1]):
        flags |= AFFIX_FLAG
    return flags


def build_tree(G, pie, mems):
    root = {"lang": PIE, "term": display(pie), "children": {}}
    for g, score, path in mems:
        nodes = [f"en|{g[1]}"] + [G.edges[e].parent for e in path]
        cur = root
        for i in range(len(path) - 1, -1, -1):
            ed = G.edges[path[i]]
            child = nodes[i]
            # edges are made per (node, section), so the edge id also tells homograph sections apart and
            # an English word that is both a leaf and an intermediate (refer -> reference) merges into one node
            k = (child, ed.id)
            nxt = cur["children"].get(k)
            if nxt is None:
                form = g[1] if i == 0 else G.edges[path[i - 1]].form
                nxt = {"lang": node_lang(child), "term": display(child, form), "edge": ed.as_json(), "children": {}}
                cur["children"][k] = nxt
            if i == 0:
                grp = G.groups[g]
                nxt.update({"etym": g[2] or None, "gloss": grp["gl"], "pos": sorted(grp["pos"])})
                flags = _path_flags(G, score, path)
                if flags & UNCERTAIN_FLAG:
                    nxt["path_uncertain"] = True
                if flags & AFFIX_FLAG:
                    nxt["via_affix"] = True
            cur = nxt

    def finalize(n):
        kids = [finalize(c) for c in n.pop("children").values()]
        if kids:
            kids.sort(key=lambda c: (c["lang"] == "en", c["lang"], c["term"]))
            n["children"] = kids
        return n
    return finalize(root)


def root_doc(G, pie, mems):
    grps = [G.groups[g] for g in G.groups_of.get(pie, [])]
    res, _ = G.results_for(pie)
    parents = []
    for r, (score, path) in sorted(res.items()):
        if r == pie or not path:
            continue
        parents.append({"term": display(r), "kind": pie_kind(node_term(r)), "uncertain": bool(score[0]),
                        "path": [display(G.edges[e].parent, G.edges[e].form) for e in path],
                        "edges": [G.edges[e].as_json() for e in path]})
    ids = sorted({i for g in grps for i in g["ids"]})
    words = {(g[1], g[2]) for g, _, _ in mems}
    return {
        "root": {"lang": PIE, "term": display(pie), "kind": pie_kind(node_term(pie)),
                 "gloss": next((g["gl"] for g in grps if g["gl"]), None),
                 "page_exists": pie in G.titles.exact,
                 "homograph_ids": ids if len(ids) > 1 else None},
        "parents": parents,
        "stats": {"english_sections": len(words),
                  "english_words": len({w for w, _ in words}),
                  "uncertain_paths": sum(1 for _, s, _ in mems if s[0]),
                  "via_affix": sum(1 for _, s, p in mems if _path_flags(G, s, p) & AFFIX_FLAG)},
        "tree": build_tree(G, pie, mems),
    }


def write_outputs(G, outdir, members, per_group, tops):
    os.makedirs(os.path.join(outdir, "roots"), exist_ok=True)
    def direct_words(p):
        return len({g[1] for g, sc, path in members[p] if not _path_flags(G, sc, path) & AFFIX_FLAG})
    sizes = {p: direct_words(p) for p in tops}
    order = sorted(tops, key=lambda p: (-sizes[p], p))
    root_idx = {p: i for i, p in enumerate(order)}
    roots_meta = []
    for p in order:
        s = slug(display(p))
        doc = root_doc(G, p, members[p])
        with open(os.path.join(outdir, "roots", s + ".json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
        roots_meta.append({"slug": s, "term": display(p), "kind": doc["root"]["kind"],
                           "words": sizes[p], "words_incl_affix": doc["stats"]["english_words"]})

    words, glosses, unrooted = defaultdict(list), defaultdict(dict), defaultdict(list)
    for g, res in per_group.items():
        hits = [(root_idx[p], g[2], _path_flags(G, s, path)) for p, (s, path) in res.items() if p in root_idx]
        if hits:
            words[g[1]].extend(sorted(hits, key=lambda h: (h[2], h[0])))
        elif G.groups[g]["lemma"]:
            unrooted[g[1]].append([g[2], G.walk_reason(g)])
    for w in words:
        etyms = {h[1] for h in words[w]}
        if len(etyms) > 1:
            for e in etyms:
                glosses[w][str(e)] = G.groups[("en", w, e)]["gl"]
    index = {"format": "word -> [[root index, etymology number (0 = only one), flags]]; "
                        "flags: 1 = path has an uncertain step, 2 = path goes through an affix",
             "roots": roots_meta, "words": dict(sorted(words.items())), "glosses": glosses}
    with open(os.path.join(outdir, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(outdir, "unrooted.json"), "w", encoding="utf-8") as f:
        json.dump(dict(sorted(unrooted.items())), f, ensure_ascii=False, separators=(",", ":"))
    return index, unrooted
