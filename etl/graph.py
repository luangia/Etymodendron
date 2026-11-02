"""Build the ancestry graph and trace every English section to PIE.

Nodes are pages ("lang|title"); a page can hold several etymology sections
(homographs), so a node's own claims are stored per section ("group").
Claims about a node made on *other* pages (a "from A, from B" sequence, or a
nested {{etymon}}) are stored per node and apply to every section.

Following a link into a page with several sections needs to know which one
is meant. We use, in order: an {{etymon}} id, the page having a single
section, or all sections agreeing on the result. Otherwise the link is not
followed and the node is recorded as an ambiguous homograph.
"""
import json
import os
import sys
from collections import defaultdict, deque

from etl.normalize import TitleIndex, canonical_lang

MAX_DEPTH = 40
PIE = "ine-pro"


def node_lang(key):
    return key.partition("|")[0]


def node_term(key):
    return key.partition("|")[2]


def pie_kind(term):
    if term.startswith("-"):
        return "suffix"
    if term.endswith("-"):
        return "root"
    return "lexeme"


def is_bound(key):
    t = node_term(key)
    return t.startswith("-") or t.endswith("-")


class Edge:
    __slots__ = ("id", "child", "parent", "type", "via", "uncertain", "evidence", "confirmed", "sources",
                 "form", "resolved", "pid")

    def as_json(self):
        d = {"type": self.type, "via": self.via}
        if self.uncertain:
            d["uncertain"] = True
            if self.evidence:
                d["evidence"] = self.evidence
        if self.confirmed:
            d["confirmed"] = True
        if self.resolved != "exact":
            d["link"] = self.resolved or "unresolved"
        d["sources"] = sorted(self.sources)[:3]
        return d


class Graph:
    def __init__(self):
        self.groups = {}                         # gkey -> dict(edges, ids, unk, lemma, has_ety, gl, pos)
        self.groups_of = defaultdict(list)       # node -> [gkey] (sections with data)
        self.etym_count = defaultdict(set)       # node -> {etymology_number} from pages.tsv
        self.foreign = defaultdict(list)         # node -> explicit {{etymon}} claims made on other pages
        self.local = defaultdict(dict)           # gkey -> {node: [prose-order claims made on that page]}
        self.local_edge = {}                     # (gkey, child, parent) -> Edge
        self.titles = TitleIndex()
        self.edges = []
        self.memo = {}
        self.stack = set()
        self.cycles = set()
        self.ambiguous = defaultdict(int)        # node -> times a link into it could not be disambiguated
        self.guessed = defaultdict(int)          # node -> times only one section had data
        self.stats = defaultdict(int)

    # ------------------------------------------------------------- loading
    def load(self, workdir):
        langs = set()
        with open(os.path.join(workdir, "pages.tsv"), encoding="utf-8") as f:
            for line in f:
                langs.add(line.split("\t", 1)[0])
        self.langs = langs

        with open(os.path.join(workdir, "sections.jsonl"), encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                g = (r["l"], r["w"], r["e"])
                grp = self.groups.get(g)
                if grp is None:
                    grp = self.groups[g] = {"edges": {}, "ids": set(), "unk": False, "lemma": False,
                                            "has_ety": False, "gl": None, "pos": set()}
                    self.groups_of[f"{r['l']}|{r['w']}"].append(g)
                for e in r["edges"]:
                    grp["edges"].setdefault((e["c"], e["p"], e["t"], e["via"]), e)
                grp["ids"].update(r.get("ids", ()))
                grp["unk"] |= r.get("unk", False)
                grp["lemma"] |= r.get("lemma", False)
                grp["has_ety"] |= r.get("has_ety", bool(r["edges"]))
                grp["gl"] = grp["gl"] or r.get("gl")
                if r.get("pos"):
                    grp["pos"].add(r["pos"])

        # languages that are ever linked to: only those need a title index
        wanted = set()
        for grp in self.groups.values():
            for e in grp["edges"].values():
                wanted.add(canonical_lang(node_lang(e["p"]), langs))
        wanted.add("en")
        with open(os.path.join(workdir, "pages.tsv"), encoding="utf-8") as f:
            for line in f:
                lang, word, etym, _ = line.rstrip("\n").split("\t")
                if lang in wanted:
                    self.titles.add(lang, word)
                    self.etym_count[f"{lang}|{word}"].add(etym)
        self.titles.langs |= langs

        # resolve link targets. Claims about other nodes: nested {{etymon}} links are explicit and
        # apply everywhere; prose-order ("from A, from B") links stay local to the page stating them
        for g, grp in self.groups.items():
            src = f"{g[0]}:{g[1]}" + (f"#{g[2]}" if g[2] else "")
            own = []
            for e in grp["edges"].values():
                e["p"], e["res"] = self.titles.resolve(e["p"])
                e["src"] = src
                self.stats[f"links_{e['res'] or 'unresolved'}"] += 1
                if e["c"] is None:
                    own.append(e)
                    continue
                e["c"], _ = self.titles.resolve(e["c"])
                if e["via"] == "etymon":
                    self.foreign[e["c"]].append(e)
                else:
                    self.local[g].setdefault(e["c"], []).append(e)
            grp["edges"] = own
        print(f"loaded {len(self.groups):,} sections, {len(self.titles.exact):,} titles", file=sys.stderr)

    # ------------------------------------------------------------ traversal
    def _make_edge(self, child, parent, claims, confirmed):
        pick = next((c for c in claims if c["via"] == "etymon"), claims[0])
        ed = Edge()
        ed.id = len(self.edges)
        ed.child, ed.parent, ed.form, ed.type = child, parent, pick["form"], pick["t"]
        ed.via = {"template": "page"}.get(pick["via"], pick["via"])
        # an explicit {{etymon}} statement decides; otherwise uncertain only if every claim is hedged
        ety = [c for c in claims if c["via"] == "etymon"]
        ed.uncertain = any(c.get("u") for c in ety) if ety else all(c.get("u") for c in claims)
        unc = next((c for c in claims if c.get("u")), None)
        ed.evidence = unc.get("ev") if (ed.uncertain and unc) else None
        ed.confirmed = confirmed
        ed.sources = {c["src"] for c in claims}
        ed.resolved = pick["res"]
        ed.pid = next((c.get("pid") for c in claims if c.get("pid")), None)
        self.edges.append(ed)
        return ed

    def _merged_edges(self, node, g):
        """Claims about node that hold everywhere: section g's own, plus explicit {{etymon}} links."""
        by_parent = defaultdict(list)
        if g is not None:
            for e in self.groups[g]["edges"]:
                by_parent[e["p"]].append(e)
        for e in self.foreign.get(node, ()):
            by_parent[e["p"]].append(e)
        return [self._make_edge(node, p, cl, False) for p, cl in by_parent.items() if p != node]

    def _states_link(self, child, parent):
        """Does child's own page (or an explicit etymon) state child -> parent?"""
        if any(e["p"] == parent for e in self.foreign.get(child, ())):
            return True
        return any(e["p"] == parent for g in self.groups_of.get(child, ()) for e in self.groups[g]["edges"])

    def _local_edges(self, g, node):
        out = []
        by_parent = defaultdict(list)
        for e in self.local.get(g, {}).get(node, ()):
            by_parent[e["p"]].append(e)
        for p, cl in by_parent.items():
            k = (g, node, p)
            if k not in self.local_edge:
                self.local_edge[k] = self._make_edge(node, p, cl, self._states_link(node, p))
            if p != node:
                out.append(self.local_edge[k])
        return out

    @staticmethod
    def _extend(best, ed, res, flag):
        for root, (score, path) in res.items():
            unc = score[0] + (1 if ed.uncertain or flag == "homograph_guess" else 0)
            unconf = score[2] + (1 if ed.via == "sequence" and not ed.confirmed else 0)
            cand = ((unc, score[1] - 1, unconf), (ed.id,) + path)
            if root not in best or cand[0] < best[root][0]:
                best[root] = cand

    def _with_local(self, node, pid, g, depth, seen):
        """Results at node: what holds globally, plus the prose chain of page g continuing from node."""
        res, flag = self.results_for(node, pid, depth)
        local = self._local_edges(g, node) if g is not None else []
        if not local or node in seen:
            return res, flag
        best = dict(res)
        for ed in local:
            sub, sflag = self._with_local(ed.parent, ed.pid, g, depth + 1, seen | {node})
            self._extend(best, ed, sub, sflag)
        return best, flag

    def results_for(self, node, pid=None, depth=0):
        """{pie_node: (score, path)} for the best path from node to every PIE node it reaches."""
        groups = self.groups_of.get(node, [])
        n_sections = max(len(self.etym_count.get(node, ())), len(groups))
        if not groups:
            return self.compute(node, None, depth), None
        if pid:
            hit = [g for g in groups if pid in self.groups[g]["ids"]]
            if len(hit) == 1:
                return self.compute(node, hit[0], depth), None
        if len(groups) == 1:
            res = self.compute(node, groups[0], depth)
            if n_sections <= 1 or not res:
                return res, None
            # the page's other sections carry no ancestry data: follow, but flag it
            self.guessed[node] += 1
            return res, "homograph_guess"
        results = [self.compute(node, g, depth) for g in groups]
        nonempty = [r for r in results if r]
        if not nonempty:
            return {}, None
        if len(nonempty) == len(groups) and all(r.keys() == nonempty[0].keys() for r in nonempty):
            best = min(nonempty, key=lambda r: sorted(s for s, _ in r.values()))
            if n_sections == len(groups):
                return best, None
            self.guessed[node] += 1
            return best, "homograph_guess"
        self.ambiguous[node] += 1
        return self.compute(node, None, depth), "ambiguous"

    def compute(self, node, g, depth=0):
        key = (node, g)
        if key in self.memo:
            return self.memo[key]
        if key in self.stack or depth > MAX_DEPTH:
            self.cycles.add(node)
            return {}
        self.stack.add(key)
        best = {}
        if node_lang(node) == PIE:
            best[node] = ((0, 0, 0), ())
        for ed in self._merged_edges(node, g):
            res, flag = self._with_local(ed.parent, ed.pid, g, depth + 1, frozenset([node]))
            self._extend(best, ed, res, flag)
        self.stack.discard(key)
        self.memo[key] = best
        return best

    # --------------------------------------------------------------- roots
    def is_top(self, pie_node):
        """A PIE node gets its own file if it is a root, or a word with no certain PIE parent."""
        kind = pie_kind(node_term(pie_node))
        if kind == "suffix":
            return False
        if kind == "root":
            return True
        res, _ = self.results_for(pie_node)
        return not any(r != pie_node and pie_kind(node_term(r)) != "suffix" and s[0] == 0
                       for r, (s, _) in res.items())

    def walk_reason(self, g):
        """Why an English section reaches no PIE node, and the node where its history stops.

        Returns (reason, node key or None). Best effort, for the report and the site's search.
        """
        grp = self.groups[g]
        if not grp["has_ety"]:
            return "no_etymology", None
        if not grp["edges"]:
            return ("unknown_origin" if grp["unk"] else "no_ancestry_templates"), None
        start = f"{g[0]}|{g[1]}"
        seen, todo, found = set(), deque([(start, g, 0)]), {}
        deepest = (0, None)
        while todo and len(seen) < 5000:
            node, grp_key, depth = todo.popleft()  # breadth-first: nodes are first met at their nearest
            if (node, grp_key) in seen:
                continue
            seen.add((node, grp_key))
            lang = node_lang(node)
            if depth > deepest[0]:
                deepest = (depth, node)
            if lang == PIE and pie_kind(node_term(node)) == "suffix":
                found.setdefault("pie_suffix_only", node)
            elif lang.endswith("-pro") and depth < found.get("_proto_depth", 1 << 30):
                # the nearest proto-language is the one on the main chain; deeper ones tend to come
                # from side remarks (cat: Proto-West Germanic, not a Proto-Uralic comparison)
                found["proto_language_no_pie"], found["_proto_depth"] = node, depth
            edges = (self.groups[grp_key]["edges"] if grp_key else []) + self.foreign.get(node, []) \
                + self.local.get(g, {}).get(node, [])
            if not edges and grp_key is None and node not in self.titles.exact:
                found.setdefault("chain_broken_unresolved", node)
            for e in edges:
                p = e["p"]
                gs = self.groups_of.get(p, [])
                hit = [x for x in gs if e.get("pid") and e["pid"] in self.groups[x]["ids"]]
                if len(gs) == 1 or len(hit) == 1:
                    todo.append((p, (hit or gs)[0], depth + 1))
                elif gs and self.ambiguous.get(p):
                    found.setdefault("ambiguous_homograph", p)
                    todo.append((p, None, depth + 1))
                elif gs:
                    todo.extend((p, x, depth + 1) for x in gs)
                else:
                    todo.append((p, None, depth + 1))
        for r in ("pie_suffix_only", "ambiguous_homograph", "proto_language_no_pie", "chain_broken_unresolved"):
            if r in found:
                return r, found[r]
        return "non_pie_or_incomplete", deepest[1]
