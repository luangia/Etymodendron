"""Two synthetic dumps through the loader and dbt: snapshots, change types and data tests.

Needs dbt-duckdb (requirements-warehouse.txt); skipped otherwise. Runs in about 30 s.
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

duckdb = pytest.importorskip("duckdb")
DBT = shutil.which("dbt", path=os.path.dirname(sys.executable)) or shutil.which("dbt")
pytestmark = pytest.mark.skipif(DBT is None, reason="dbt is not installed")

from etl import warehouse  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
X = [{"c": None, "p": "la|x", "t": "borrowed"}]
Y = [{"c": None, "p": "ang|y", "t": "inherited"}]
Z = [{"c": None, "p": "fr|z", "t": "borrowed"}]
HUMUS = [{"c": None, "p": "la|humus", "t": "borrowed", "via": "etymon"}]
ROOTS = [
    {"slug": "ghemi-ef8bd5", "term": "*ǵʰémi", "kind": "lexeme"},
    {"slug": "meh2ter-169474", "term": "*méh₂tēr", "kind": "lexeme"},
    {"slug": "kat-aaaaaa", "term": "*kat-", "kind": "root"},
    {"slug": "kat-bbbbbb", "term": "*kat-", "kind": "root"},
]

DUMP_A = {
    "last_modified": "Thu, 01 Jan 2026 12:00:00 GMT",
    "sections": [
        ("humus", 0, []), ("mother", 0, Y), ("bank", 1, X), ("bank", 2, Y),
        ("free", 0, Y), ("cat", 0, X), ("dog", 0, Y),
    ],
    "words": {"mother": [[1, "0", 0]], "free": [[1, "0", 1]], "cat": [[2, "0", 0]], "dog": [[1, "0", 0]]},
    "unrooted": {"humus": [[0, "no_ancestry_templates", None]], "bank": [[1, "chain_broken_unresolved", "la|x"]]},
}
DUMP_B = {
    "last_modified": "Thu, 08 Jan 2026 12:00:00 GMT",
    "sections": [
        ("humus", 0, HUMUS), ("mother", 0, Y),
        ("bank", 1, Z), ("bank", 2, X), ("bank", 3, Y),    # a new etymology inserted at the top
        ("glorp", 0, []), ("cat", 0, Z), ("dog", 0, X),    # free is gone, glorp is new
    ],
    "words": {"humus": [[0, "0", 1]], "mother": [[1, "0", 0]], "cat": [[3, "0", 0]]},
    "unrooted": {"bank": [[1, "chain_broken_unresolved", "fr|z"]], "glorp": [[0, "no_etymology", None]],
                 "dog": [[0, "non_pie_or_incomplete", "la|x"]]},
}


def write_dump(base, dump):
    work, out, raw = (os.path.join(base, d) for d in ("work", "out", "raw"))
    for d in (work, out, raw):
        os.makedirs(d, exist_ok=True)
    with open(os.path.join(work, "sections.jsonl"), "w") as f:
        for word, e, edges in dump["sections"]:
            f.write(json.dumps({"l": "en", "w": word, "e": e, "pos": "noun", "edges": edges,
                                "lemma": True, "has_ety": bool(edges), "gl": word}) + "\n")
    with open(os.path.join(out, "index.json"), "w") as f:
        json.dump({"roots": ROOTS, "words": dump["words"]}, f)
    with open(os.path.join(out, "unrooted.json"), "w") as f:
        json.dump(dump["unrooted"], f)
    with open(os.path.join(raw, "MANIFEST.json"), "w") as f:
        json.dump({"url": "test://dump", "bytes": 1, "sha256": "0", "last_modified": dump["last_modified"]}, f)
    return work, out, raw


# a 7-section fixture swings far more than a real dump, so the guard thresholds are opened up
LOOSE = '{"max_section_change_pct": 100, "max_coverage_drop_pts": 100}'


def dbt(tmp_path, db, *args):
    env = {**os.environ, "DUCKDB_PATH": db, "DBT_TARGET": "local"}
    return subprocess.run([DBT, *args, "--profiles-dir", ".", "--target-path", str(tmp_path / "target"),
                           "--log-path", str(tmp_path / "logs")],
                          cwd=os.path.join(ROOT, "warehouse"), env=env, capture_output=True, text=True)


def load_and_build(tmp_path, name, dump, db):
    work, out, raw = write_dump(str(tmp_path / name), dump)
    assert warehouse.main(["load", "--backend", "duckdb", "--duckdb", db, "--work", work, "--out", out,
                           "--raw", raw, "--stage", str(tmp_path / "load")]) == 0
    r = dbt(tmp_path, db, "build", "--vars", LOOSE)
    assert r.returncode == 0, r.stdout[-4000:]


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("wh")
    path = str(tmp / "wh.duckdb")
    load_and_build(tmp, "a", DUMP_A, path)
    load_and_build(tmp, "b", DUMP_B, path)
    return tmp, path


@pytest.fixture(scope="module")
def db(built):
    return built[1]


def rows(db, sql):
    with duckdb.connect(db, read_only=True) as con:   # closed again, so a later dbt run can write
        return sorted(con.execute(sql).fetchall(), key=lambda r: tuple(str(x) for x in r))


def test_section_changes_match_by_content(db):
    assert rows(db, "select change_type, section_key, prev_section_key from main.fct_section_changes") == sorted([
        ("added", "en|bank|noun|1", None),            # the inserted etymology
        ("renumbered", "en|bank|noun|2", "en|bank|noun|1"),
        ("renumbered", "en|bank|noun|3", "en|bank|noun|2"),
        ("edited", "en|cat|noun|0", "en|cat|noun|0"),
        ("edited", "en|dog|noun|0", "en|dog|noun|0"),
        ("added", "en|glorp|noun|0", None),
        ("removed", None, "en|free|noun|0"),
        ("edited", "en|humus|noun|0", "en|humus|noun|0"),
    ], key=lambda r: tuple(str(x) for x in r))


def test_word_root_changes(db):
    assert rows(db, "select word, change_type, prev_root_slugs, root_slugs from main.fct_word_root_changes") == [
        ("cat", "roots_changed", "kat-aaaaaa", "kat-bbbbbb"),
        ("dog", "lost_root", "meh2ter-169474", None),
        ("free", "removed_word", "meh2ter-169474", None),
        ("glorp", "added_word", None, None),
        ("humus", "gained_root", None, "ghemi-ef8bd5"),
    ]


def test_snapshots_keep_history(db):
    # humus: the empty first version is closed, the new one is open
    assert rows(db, "select edges_hash is not null, dbt_valid_to is null from main.snap_sections "
                    "where section_key = 'en|humus|noun|0'") == [(True, False), (True, True)]
    # free disappeared: its only version is closed
    assert rows(db, "select dbt_valid_to is null from main.snap_sections where section_key = 'en|free|noun|0'") \
        == [(False,)]
    # mother never changed: one version, still open, first seen in the first dump
    assert rows(db, "select cast(dump_id as varchar), dbt_valid_to is null from main.snap_sections "
                    "where section_key = 'en|mother|noun|0'") == [("2026-01-01", True)]
    assert rows(db, "select root_slugs, dbt_valid_to is null from main.snap_word_status where word = 'humus'") \
        == [(None, False), ("ghemi-ef8bd5", True)]


def test_dump_summary(db):
    assert rows(db, "select cast(dump_id as varchar), cast(prev_dump_id as varchar), english_lemmas, rooted_lemmas, "
                    "sections_delta from main.fct_dump_summary") == [
        ("2026-01-01", None, 6, 4, None),
        ("2026-01-08", "2026-01-01", 6, 3, 1),
    ]


def test_guard_tests_fail_on_a_big_swing(built):
    # the fixture's second dump drops coverage from 66.7% to 50%: the default 1-point guard must catch it
    r = dbt(*built, "test", "--select", "assert_coverage_not_dropping", "assert_section_count_stable")
    assert r.returncode != 0
    assert "ERROR=2" in r.stdout


def test_dump_id_is_the_last_modified_date():
    assert warehouse.dump_id_of("Fri, 30 Oct 2026 20:48:24 GMT") == "2026-10-30"


def test_duplicate_section_keys_are_merged(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text("".join(json.dumps({"l": "en", "w": "wares", "e": 0, "pos": "noun", "edges": e, "lemma": True})
                         + "\n" for e in (X, Y)))
    (row,) = warehouse.section_rows(str(p), "2026-01-01")
    assert (row["section_key"], row["entries"], row["n_edges"]) == ("en|wares|noun|0", 2, 2)
