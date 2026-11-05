"""Turn one wiktextract etymology section into typed ancestry edges.

Two template systems coexist on Wiktionary:

* ``{{etymon}}`` (new): states each parent of the entry explicitly, with
  relation keywords (``:inh``, ``:bor`` ...), homograph ids (``<id:...>``),
  uncertainty (``<unc:1>`` / ``:inh<unc>``) and nested chains
  (``<ety:bor<fro:decembre>>``). Edges from it are trusted as given.
* Classic templates (``inh``, ``bor``, ``der``, ``af`` ...): each one says
  "entry <- X". The chain between the X's is only implied by the order of
  the prose ("from A, from B, from C"), so those links are emitted with
  ``via="sequence"`` and checked later against the intermediate entries.

Nothing here guesses: templates that only mention or compare words
(``cog``, ``m``, ``doublet``, surface analyses) never produce edges, and
hedged wording in the prose marks edges ``uncertain`` with the evidence.
"""
import re

INHERITED, BORROWED, DERIVED, ROOT, COMPONENT = "inherited", "borrowed", "derived", "root", "component"

# classic templates: {{name|entry_lang|source_lang|term|alt|gloss}}
CHAIN_TEMPLATES = {
    **dict.fromkeys(["inh", "inh+", "inherited", "inh-lite"], INHERITED),
    **dict.fromkeys(["bor", "bor+", "borrowed", "bor-lite", "lbor", "learned borrowing", "slbor",
                     "semi-learned borrowing", "obor", "orthographic borrowing", "ubor",
                     "unadapted borrowing"], BORROWED),
    **dict.fromkeys(["der", "der+", "derived", "der-lite", "uder", "calque", "cal", "clq",
                     "partial calque", "pcal", "pclq", "semantic loan", "sl", "psm",
                     "phono-semantic matching"], DERIVED),
}
# same-language derivations: {{name|lang|term}}
SAME_LANG_TEMPLATES = {name: DERIVED for name in
                       ["clipping", "clip", "back-formation", "back-form", "bf", "ellipsis", "ellip"]}
# morphological templates: {{name|lang|part1|part2|...}}
AFFIX_TEMPLATES = {"af", "affix", "pre", "prefix", "suf", "suffix", "con", "confix",
                   "com", "compound", "blend", "circumfix", "infix"}
ROOT_TEMPLATES = {"root"}
UNKNOWN_TEMPLATES = {"unk", "unknown", "unc", "uncertain"}
# comparisons: never ancestry, and they end a "from A, from B" chain
CHAIN_BREAKERS = {"cog", "cognate", "noncog", "noncognate", "ncog", "doublet", "dbt", "surf",
                  "surface analysis", "col-top", "col", "col2", "col3", "desc"}

# {{etymon}} and its shortcut
ETYMON_TEMPLATES = {"etymon", "ety"}
ETYMON_KEYWORDS = {
    ":inh": INHERITED,
    **dict.fromkeys([":bor", ":lbor", ":slbor", ":obor", ":ubor"], BORROWED),
    **dict.fromkeys([":der", ":uder", ":from", ":calque", ":clq", ":pclq", ":sl", ":psm", ":bf",
                     ":back", ":clip", ":clipping", ":ellipsis", ":ellip", ":deverbal", ":nom",
                     ":vrd", ":univ"], DERIVED),
    **dict.fromkeys([":af", ":affix", ":com", ":compound", ":blend", ":prefix", ":suffix",
                     ":confix"], COMPONENT),
    ":root": ROOT,
}
# etymon keywords that are explicitly not ancestry (surface analysis, influence, ...)
ETYMON_SKIP = {":afeq", ":influence", ":infl", ":surf", ":abbr", ":acronym", ":init", ":cog",
               ":doublet", ":dbt"}

HEDGE_RE = re.compile(
    r"\b(possibl[ey]|perhaps|probabl[ey]|maybe|uncertain\w*|unclear|disputed|doubtful|dubious"
    r"|conjectur\w*|speculat\w*|hypothe\w*|presumabl[ey]|apparently|supposedly|allegedly"
    r"|obscure|unknown|folk etymolog\w*|may be|might be|could be|may have|might have"
    r"|perhaps|likely|unlikely|tentative\w*|some (?:scholars|sources|authors)|according to some"
    r"|it has been (?:suggested|proposed)|has been (?:suggested|proposed|connected)"
    r"|supposed|assumed|believed|thought to|traditionally|commonly (?:derived|connected|said))\b"
    r"|\?", re.I)
ALTERNATIVES_RE = re.compile(r"\b(alternatively|another (?:theory|possibility|view|explanation)"
                             r"|others? (?:derive|connect|suggest)|competing (?:theory|theories))\b", re.I)
SENTENCE_END_RE = re.compile(r"[.;]\s|\n")
SIBLING_GAP_RE = re.compile(r"\b(and|plus)\b|\+|&|;", re.I)
OR_GAP_RE = re.compile(r"\bor\b", re.I)
NOT_ANCESTRY_GAP_RE = re.compile(r"\b(influenc\w*|compare|cf|cognate|akin|related|doublet|contaminat\w*|reinforced)\b", re.I)
INLINE_MOD_RE = re.compile(r"<[^<>]*>")
WIKILINK_RE = re.compile(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]")
LANG_PREFIX_RE = re.compile(r"^([a-z]{2,3}(?:-[a-z]{2,5})*):(?!$)(.+)$")
EMPTY_TERM_RE = re.compile(r"^([a-z]{2,3}(?:-[a-z]{2,5})*):()$")


def clean_term(term):
    """Strip inline modifiers, wikilinks and whitespace from a linked form."""
    if not term:
        return ""
    term = WIKILINK_RE.sub(r"\1", term)
    while INLINE_MOD_RE.search(term):
        term = INLINE_MOD_RE.sub("", term)
    term = term.strip()
    return "" if term in ("-", "?", "—") else term


def node_key(lang, term):
    """Graph key: reconstructions are stored by wiktextract without the asterisk."""
    return f"{lang}|{term.lstrip('*')}"


BAD_TERM_RE = re.compile(r"[\[\]{}<>|]|^\W*$|^[a-z]{2,3}(?:-[a-z]{2,5})*:")


def _edge(parent_lang, term, etype, via, src, child=None, uncertain=False, evidence=None, pid=None, gloss=None):
    term = clean_term(term)
    # "+", leftover "lang:" prefixes and unexpanded wikitext are not words
    if not term or not parent_lang or BAD_TERM_RE.search(term) or not re.search(r"\w", term):
        return None
    e = {"c": child, "p": node_key(parent_lang, term), "form": term, "t": etype, "via": via, "src": src}
    if uncertain:
        e["u"] = True
        if evidence:
            e["ev"] = evidence[:160]
    if pid:
        e["pid"] = pid
    if gloss:
        e["gl"] = gloss[:80]
    return e


# ---------------------------------------------------------------- etymon

def _split_mods(s):
    """'la:ferō<id:carry><unc:1>' -> ('la:ferō', [('id','carry'), ('unc','1')]); nesting-aware."""
    head, mods, i, n = [], [], 0, len(s)
    while i < n and s[i] != "<":
        head.append(s[i])
        i += 1
    while i < n:
        if s[i] != "<":
            i += 1
            continue
        depth, j = 0, i
        while j < n:
            if s[j] == "<":
                depth += 1
            elif s[j] == ">":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        body = s[i + 1:j]
        k, _, v = body.partition(":")
        mods.append((k.strip(), v) if _ else (body.strip(), ""))
        i = j + 1
    return "".join(head).strip(), mods


def _split_groups(s):
    """'bor<fro:x><la:y>' -> ('bor', ['fro:x', 'la:y']) honouring nesting."""
    rel, i = [], 0
    while i < len(s) and s[i] != "<":
        rel.append(s[i])
        i += 1
    groups = []
    while i < len(s):
        if s[i] != "<":
            i += 1
            continue
        depth, j = 0, i
        while j < len(s):
            depth += {"<": 1, ">": -1}.get(s[j], 0)
            if depth == 0:
                break
            j += 1
        groups.append(s[i + 1:j])
        i = j + 1
    return "".join(rel).strip(), groups


def _etymon_term(raw, ctx_lang, child, etype, kw_unc, src, out, depth=0):
    """Parse one etymon term (with nested <ety:...>) and append edges to out."""
    if depth > 20:
        return
    if raw.lstrip().startswith("["):
        return  # wikitext wiktextract could not expand
    head, mods = _split_mods(raw)
    m = LANG_PREFIX_RE.match(head) or EMPTY_TERM_RE.match(head)
    lang, term = (m.group(1), m.group(2)) if m else (ctx_lang, head)
    md = {}
    for k, v in mods:
        md.setdefault(k, v)
    if not term.strip():
        term = md.get("alt", "")  # unlinked term, shown only by its display form
    unc = kw_unc or md.get("unc") not in (None, "", "0")
    e = _edge(lang, term, etype, "etymon", src, child=child, uncertain=unc,
              evidence="marked uncertain in {{etymon}}" if unc else None,
              pid=md.get("id") or None, gloss=md.get("t"))
    if e is not None:
        out.append(e)
        child = e["p"]
    elif term.strip():
        return  # not a word: drop it and anything nested under it
    for k, v in mods:
        if k != "ety":
            continue
        rel, groups = _split_groups(v)
        sub_type = ETYMON_KEYWORDS.get(":" + rel)
        if sub_type is None:
            continue
        for g in groups:
            _etymon_term(g, lang, child, sub_type, False, src, out, depth + 1)


def etymon_edges(args, entry_lang):
    """Edges from one {{etymon}} call. Child None means the entry itself."""
    out = []
    if args.get("1") != entry_lang:
        return out, None
    etype, kw_unc = None, False
    positional = sorted((int(k), v) for k, v in args.items() if k.isdigit() and int(k) >= 2)
    for _, v in positional:
        v = v.strip()
        if v.startswith(":"):
            kw, mods = _split_mods(v)
            md = dict(mods)
            etype = None if kw in ETYMON_SKIP or "surf" in md else ETYMON_KEYWORDS.get(kw)
            kw_unc = "unc" in md
            continue
        if etype is None:
            continue
        _etymon_term(v, entry_lang, None, etype, kw_unc, "etymon", out)
    return out, args.get("id")


# ------------------------------------------------------------ classic templates

def _locate(text, needle, start):
    if not needle:
        return -1
    i = text.find(needle, start)
    return i if i >= 0 else text.find(needle)


def _hedge_before(text, pos):
    """Hedge word between the start of the sentence containing pos and pos."""
    if pos < 0:
        return None
    sent_start = 0
    for m in SENTENCE_END_RE.finditer(text, 0, pos):
        sent_start = m.end()
    m = HEDGE_RE.search(text, sent_start, pos)
    if m:
        return text[sent_start:pos + 40].strip()
    return None


def _main_paragraph_bounds(text):
    """The prose paragraph holding the main chain (skip the 'Etymology tree' block)."""
    paras, pos = [], 0
    for chunk in text.split("\n"):
        paras.append((pos, pos + len(chunk), chunk))
        pos += len(chunk) + 1
    for s, e, chunk in paras:
        c = chunk.strip()
        if not c or c == "Etymology tree" or " " not in c and len(c) < 40:
            continue
        if re.match(r"^[A-Z][\w\s'-]*? \*?\S+(?:der\.|\?)*$", c) and not re.search(r"\b(from|of)\b", c):
            continue  # a line of the rendered etymology tree, e.g. "Old English bera"
        return s, e
    return 0, len(text)


def _affix_parts(t, entry_lang):
    name, a = t["name"], t["args"]
    lang = a.get("1", "")
    parts = []
    for i in range(2, 30):
        v = a.get(str(i))
        if v is None:
            continue
        plang = a.get(f"lang{i - 1}") or lang
        m = LANG_PREFIX_RE.match(v.strip())
        if m:
            plang, v = m.group(1), m.group(2)
        _, mods = _split_mods(v)
        md = dict(mods)
        parts.append((plang, v, md.get("id") or a.get(f"id{i - 1}"), md.get("t") or a.get(f"t{i - 1}")))
    # {{prefix|en|un|do}}, {{suffix|ine-pro|*men-|tis}}: these templates supply the hyphen
    if parts and name in ("pre", "prefix", "con", "confix"):
        parts[0] = (parts[0][0], _hyphenate(parts[0][1], after=True), *parts[0][2:])
    if len(parts) > 1 and name in ("suf", "suffix", "con", "confix"):
        parts[-1] = (parts[-1][0], _hyphenate(parts[-1][1], after=False), *parts[-1][2:])
    return lang, parts


def _hyphenate(term, after):
    base, mods = _split_mods(term)
    star = "*" if base.startswith("*") else ""
    base = base.lstrip("*")
    if not base or "-" in (base[-1] if after else base[0]):
        return term
    return star + (base + "-" if after else "-" + base)


def classic_edges(templates, text, entry_lang, entry_key):
    """Edges implied by classic templates, using prose order for the chain."""
    text = text or ""
    para_s, para_e = _main_paragraph_bounds(text)
    out, chain, cursor, roots = [], [], 0, []
    prev_end, prev_edge, chain_open = None, None, True
    unknown = False

    for t in templates:
        name, a = t.get("name", ""), t.get("args", {})
        exp = t.get("expansion") or ""
        if name in UNKNOWN_TEMPLATES:
            unknown = True
            continue
        if name in CHAIN_BREAKERS:
            pos = _locate(text, exp, cursor) if exp else -1
            if pos < 0 or para_s <= pos < para_e:
                chain_open = False
            continue
        if name in ROOT_TEMPLATES:
            if a.get("1") != entry_lang:
                continue
            for i in range(3, 10):
                term = a.get(str(i))
                if not term:
                    continue
                pos = _locate(text, clean_term(term), para_s)
                ev = _hedge_before(text, pos)
                e = _edge(a.get("2", ""), term, ROOT, "root", "root", uncertain=bool(ev), evidence=ev,
                          pid=a.get(f"id{i - 2}") or a.get("id"))
                if e:
                    roots.append(e)
            continue

        is_chain = name in CHAIN_TEMPLATES or name in SAME_LANG_TEMPLATES
        is_affix = name in AFFIX_TEMPLATES
        if not (is_chain or is_affix) or a.get("1") != entry_lang and is_chain:
            continue
        if is_affix and a.get("type") == "surf":
            continue

        pos = _locate(text, exp, cursor) if exp else -1
        in_main = pos < 0 or para_s <= pos < para_e
        if pos >= 0:
            cursor = pos + len(exp)
        gap = text[prev_end:pos] if (prev_end is not None and pos >= 0 and pos >= prev_end) else ""
        ev = _hedge_before(text, pos)

        if is_chain:
            if name in SAME_LANG_TEMPLATES:
                plang, term, gloss = entry_lang, a.get("2", ""), a.get("t") or a.get("4")
            else:
                # an empty term with a display form is an unlinked term: {{der|en|ine-pro||*x}}
                plang, term, gloss = a.get("2", ""), a.get("3") or a.get("4", ""), a.get("t") or a.get("5")
            etype = CHAIN_TEMPLATES.get(name) or SAME_LANG_TEMPLATES[name]
            e = _edge(plang, term, etype, "template", name, uncertain=bool(ev) or not in_main,
                      evidence=ev or (None if in_main else "stated outside the main etymology paragraph"),
                      gloss=gloss)
            if e is None:
                continue
            lead = text[max(prev_end or 0, pos - 30):pos] if pos >= 0 else ""
            if NOT_ANCESTRY_GAP_RE.search(lead) and not re.search(r"\bfrom\s*$", lead):
                continue  # "influenced by X", "compare X": not a parent
            if chain and chain_open and in_main:
                # a sibling reading ("A + B", "A and B") is always true, since every template states
                # entry <- X; a chain reading may not be, so any branching cue wins over "from"
                if OR_GAP_RE.search(gap):
                    # "from A or B": alternatives, both uncertain, same child
                    e["c"] = prev_edge["c"]
                    for x in (e, prev_edge):
                        x["u"] = True
                        x.setdefault("ev", f"alternatives: …{gap.strip()[:120]}…")
                elif SIBLING_GAP_RE.search(gap):
                    e["c"] = prev_edge["c"]
                else:
                    e["c"] = chain[-1]["p"]
                    e["via"] = "sequence"
            if e["c"] is None:
                e["via"] = "template"
            out.append(e)
            if in_main:
                chain.append(e)
                prev_edge = e
                if pos >= 0:
                    prev_end = pos + len(exp)
            continue

        # affix / compound
        lang, parts = _affix_parts(t, entry_lang)
        if lang == entry_lang:
            child = None
        else:
            # "from Latin X, from Y + Z" written with {{af|la|...}}: attach to the last Latin link
            child = next((c["p"] for c in reversed(chain) if c["p"].startswith(lang + "|")), False)
            if child is False:
                continue
        for plang, term, pid, gloss in parts:
            e = _edge(plang, term, COMPONENT, "template" if child is None else "sequence", name,
                      child=child, uncertain=bool(ev) or not in_main, evidence=ev, pid=pid, gloss=gloss)
            if e:
                out.append(e)
    # {{root}} names the word's PIE root; the chain in the same prose says how it got here. Hang the
    # root off the end of that chain (en <- grc karkinos <- *(s)ker-) instead of off the word itself,
    # so the route is kept. Like other prose-order links, it only applies to this page's trace.
    if chain:
        end = chain[-1]["p"]
        for e in roots:
            if e["p"] != end:
                e["c"] = end
    out.extend(roots)
    return out, unknown


def section_edges(templates, text, entry_lang, entry_key):
    """All edges for one etymology section, de-duplicated. Returns (edges, etymon_ids, unknown_flag)."""
    etymon, classic, ids = [], [], set()
    for t in templates:
        if t.get("name") in ETYMON_TEMPLATES:
            es, eid = etymon_edges(t.get("args", {}), entry_lang)
            etymon.extend(es)
            if eid:
                ids.add(eid)
        else:
            classic.append(t)
    cl, unknown = classic_edges(classic, text, entry_lang, entry_key)
    if text and (m := ALTERNATIVES_RE.search(text)):
        for e in cl:  # the section itself offers competing derivations
            if not e.get("u"):
                e["u"] = True
                e["ev"] = "section gives alternatives: …" + text[max(0, m.start() - 20):m.end() + 60] + "…"
    seen, out = set(), []
    for e in etymon + cl:
        k = (e["c"], e["p"], e["t"], e["via"])
        if k in seen:
            continue
        seen.add(k)
        out.append(e)
    if text and re.search(r"\b(of )?(unknown|uncertain|obscure) (origin|etymology)\b", text, re.I):
        unknown = True
    return out, sorted(ids), unknown
