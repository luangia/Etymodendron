import json

from etl.export import collect, write_outputs
from etl.extract import process
from etl.graph import Graph
from etl.templates import section_edges, etymon_edges


def T(name, expansion="", **args):
    return {"name": name, "args": {str(k).lstrip("_"): v for k, v in args.items()}, "expansion": expansion}


def edges_of(templates, text, lang="en", word="x"):
    return section_edges(templates, text, lang, f"{lang}|{word}")[0]


# ------------------------------------------------------------------ templates

def test_classic_chain_uses_prose_order():
    text = "From Middle English comen, from Old English cuman, from Proto-Germanic *kwemaną."
    es = edges_of([
        T("inh", "Middle English comen", _1="en", _2="enm", _3="comen"),
        T("inh", "Old English cuman", _1="en", _2="ang", _3="cuman"),
        T("inh", "Proto-Germanic *kwemaną", _1="en", _2="gem-pro", _3="*kwemaną"),
    ], text)
    assert [(e["c"], e["p"], e["via"]) for e in es] == [
        (None, "enm|comen", "template"),
        ("enm|comen", "ang|cuman", "sequence"),
        ("ang|cuman", "gem-pro|kwemaną", "sequence"),
    ]
    assert not any(e.get("u") for e in es)


def test_cognates_and_mentions_are_not_edges():
    text = "From Old English beran. Cognate with German gebären, see also bear."
    es = edges_of([
        T("inh", "Old English beran", _1="en", _2="ang", _3="beran"),
        T("cog", "German gebären", _1="de", _2="gebären"),
        T("m", "bear", _1="en", _2="bear"),
    ], text)
    assert [e["p"] for e in es] == ["ang|beran"]


def test_hedged_root_is_uncertain_with_evidence():
    text = "Inherited from Old English fæder, from Proto-Indo-European *ph₂tḗr, possibly from *peh₂- + *-tḗr."
    es = edges_of([
        T("root", _1="en", _2="ine-pro", _3="*peh₂-"),
        T("inh", "Old English fæder", _1="en", _2="ang", _3="fæder"),
        T("inh", "Proto-Indo-European *ph₂tḗr", _1="en", _2="ine-pro", _3="*ph₂tḗr"),
    ], text)
    root = next(e for e in es if e["t"] == "root")
    assert root["p"] == "ine-pro|peh₂-" and root["u"] and "possibly" in root["ev"]
    assert not next(e for e in es if e["p"] == "ine-pro|ph₂tḗr").get("u")


def test_alternatives_are_both_uncertain_and_siblings():
    text = "From Old French faire or Latin facere."
    es = edges_of([
        T("der", "Old French faire", _1="en", _2="fro", _3="faire"),
        T("der", "Latin facere", _1="en", _2="la", _3="facere"),
    ], text)
    assert all(e["c"] is None and e["u"] for e in es)


def test_influence_is_not_a_parent():
    text = "From Middle English foo, influenced by Old Norse bar."
    es = edges_of([
        T("inh", "Middle English foo", _1="en", _2="enm", _3="foo"),
        T("der", "Old Norse bar", _1="en", _2="non", _3="bar"),
    ], text)
    assert [e["p"] for e in es] == ["enm|foo"]


def test_etymon_nested_chain_ids_and_uncertainty():
    es, eid = etymon_edges({"1": "en", "id": "month", "2": ":inh",
                            "3": "enm:December<ety:bor<fro:decembre<unc:1>>>", "tree": "1"}, "en")
    assert eid == "month"
    assert [(e["c"], e["p"], e["t"], bool(e.get("u"))) for e in es] == [
        (None, "enm|December", "inherited", False),
        ("enm|December", "fro|decembre", "borrowed", True),
    ]


def test_etymon_surface_analysis_skipped():
    es, _ = etymon_edges({"1": "enm", "2": ":inh", "3": "ang:ġiestrandæġ", "4": ":afeq", "5": "yester-",
                          "6": "day"}, "enm")
    assert [e["p"] for e in es] == ["ang|ġiestrandæġ"]


# ------------------------------------------------------------------ end to end

def entry(lang, word, templates=(), text="", etym=None, gloss="g", form_of=False):
    sense = {"glosses": [gloss]}
    if form_of:
        sense["form_of"] = [{"word": "x"}]
    e = {"lang_code": lang, "word": word, "pos": "verb", "senses": [sense],
         "etymology_templates": list(templates), "etymology_text": text}
    if etym:
        e["etymology_number"] = etym
    return json.dumps(e, ensure_ascii=False)


def build(tmp_path, lines):
    sections, pages = process(lines)
    work = tmp_path / "work"
    work.mkdir()
    (work / "sections.jsonl").write_text("".join(sections), encoding="utf-8")
    (work / "pages.tsv").write_text("".join(pages), encoding="utf-8")
    G = Graph()
    G.load(str(work))
    members, per_group, tops = collect(G)
    index, unrooted = write_outputs(G, str(tmp_path / "out"), members, per_group, tops)
    return G, members, tops, index, unrooted


def test_borrowing_reaches_pie_through_latin_page(tmp_path):
    lines = [
        entry("en", "prefer", [
            T("inh", "Middle English preferren", _1="en", _2="enm", _3="preferren"),
            T("der", "Latin praeferō", _1="en", _2="la", _3="praeferō")],
            "From Middle English preferren, from Latin praeferō."),
        # page title has no macron: matched diacritic-insensitively
        entry("la", "praefero", [T("af", "prae- + ferō", _1="la", _2="prae-", _3="ferō")], "From prae- + ferō."),
        entry("la", "fero", [
            T("inh", "Proto-Italic *ferō", _1="la", _2="itc-pro", _3="*ferō"),
            T("inh", "Proto-Indo-European *bʰéreti", _1="la", _2="ine-pro", _3="*bʰéreti")],
            "From Proto-Italic *ferō, from Proto-Indo-European *bʰéreti."),
        entry("ine-pro", "bʰéreti", [T("der", "*bʰer-", _1="ine-pro", _2="ine-pro", _3="*bʰer-")], "From *bʰer-."),
        entry("ine-pro", "bʰer-"),
        entry("en", "zzz", text="Of unknown origin.", templates=[T("unk", _1="en")]),
    ]
    G, members, tops, index, unrooted = build(tmp_path, lines)
    assert "ine-pro|bʰer-" in tops and "ine-pro|bʰéreti" not in tops   # lexeme has a certain parent root
    roots = [index["roots"][h[0]]["term"] for h in index["words"]["prefer"]]
    assert roots == ["*bʰer-"]
    _, path = members["ine-pro|bʰer-"][0][1:]
    assert [G.edges[e].parent for e in path] == [
        "enm|preferren", "la|praefero", "la|fero", "itc-pro|ferō", "ine-pro|bʰéreti", "ine-pro|bʰer-"]
    assert unrooted["zzz"][0][1] == "unknown_origin"


def test_ambiguous_homograph_is_not_followed(tmp_path):
    lines = [
        entry("en", "foo", [T("bor", "Latin bar", _1="en", _2="la", _3="bar")], "From Latin bar."),
        entry("la", "bar", [T("inh", "*a-", _1="la", _2="ine-pro", _3="*a-")], "From *a-.", etym=1),
        entry("la", "bar", [T("inh", "*b-", _1="la", _2="ine-pro", _3="*b-")], "From *b-.", etym=2),
    ]
    G, members, tops, index, unrooted = build(tmp_path, lines)
    assert "foo" not in index["words"]
    assert unrooted["foo"][0][1] == "ambiguous_homograph"


def test_etymon_id_picks_the_homograph(tmp_path):
    lines = [
        entry("en", "foo", [T("etymon", _1="en", _2=":bor", _3="la:bar<id:two>")], "From Latin bar."),
        entry("la", "bar", [T("etymon", _1="la", id="one", _2=":inh", _3="ine-pro:*a-")], "x", etym=1),
        entry("la", "bar", [T("etymon", _1="la", id="two", _2=":inh", _3="ine-pro:*b-")], "y", etym=2),
    ]
    G, members, tops, index, unrooted = build(tmp_path, lines)
    assert [index["roots"][h[0]]["term"] for h in index["words"]["foo"]] == ["*b-"]


def test_uncertain_parent_root_keeps_lexeme_file(tmp_path):
    lines = [
        entry("en", "father", [T("inh", "Old English fæder", _1="en", _2="ang", _3="fæder"),
                               T("inh", "Proto-Indo-European *ph₂tḗr", _1="en", _2="ine-pro", _3="*ph₂tḗr")],
              "From Old English fæder, from Proto-Indo-European *ph₂tḗr."),
        entry("ine-pro", "ph₂tḗr", [T("af", "*peh₂- + *-tḗr", _1="ine-pro", _2="*peh₂-", _3="*-tḗr")],
              "Possibly from *peh₂- + *-tḗr."),
    ]
    G, members, tops, index, unrooted = build(tmp_path, lines)
    assert "ine-pro|ph₂tḗr" in tops and "ine-pro|peh₂-" in tops and "ine-pro|-tḗr" not in tops
    hits = {index["roots"][h[0]]["term"]: h[2] for h in index["words"]["father"]}
    assert hits["*ph₂tḗr"] & 1 == 0 and hits["*peh₂-"] & 1 == 1


def test_suffix_template_supplies_hyphen():
    es = edges_of([T("suffix", "*men- + *-tis", _1="ine-pro", _2="*men-", _3="tis")], "From *men- + *-tis.",
                  lang="ine-pro", word="méntis")
    assert [e["p"] for e in es] == ["ine-pro|men-", "ine-pro|-tis"]


def test_prose_order_link_does_not_leak_to_other_pages(tmp_path):
    lines = [
        # a sloppy page implies *per- <- *gʷem- by prose order
        entry("en", "pervene", [T("der", "*per-", _1="en", _2="ine-pro", _3="*per-"),
                                T("der", "*gʷem-", _1="en", _2="ine-pro", _3="*gʷem-")],
              "From *per-, from *gʷem-."),
        entry("en", "fare", [T("inh", "*per-", _1="en", _2="ine-pro", _3="*per-")], "From *per-."),
    ]
    G, members, tops, index, unrooted = build(tmp_path, lines)
    fare = {index["roots"][h[0]]["term"] for h in index["words"]["fare"]}
    pervene = {index["roots"][h[0]]["term"] for h in index["words"]["pervene"]}
    assert fare == {"*per-"}
    assert pervene == {"*per-", "*gʷem-"}


def test_plus_between_links_means_siblings_even_with_from():
    text = ("From Sanskrit padga, from pad (ultimately from Proto-Indo-European *ped-) + ga "
            "(ultimately from Proto-Indo-European *gʷem-).")
    es = edges_of([
        T("der", "Sanskrit padga", _1="en", _2="sa", _3="padga"),
        T("der", "Proto-Indo-European *ped-", _1="en", _2="ine-pro", _3="*ped-"),
        T("der", "Proto-Indo-European *gʷem-", _1="en", _2="ine-pro", _3="*gʷem-"),
    ], text)
    assert [(e["c"], e["p"]) for e in es] == [
        (None, "sa|padga"), ("sa|padga", "ine-pro|ped-"), ("sa|padga", "ine-pro|gʷem-")]
