"""Build graph -> export JSON -> validation report, from data/work (see extract.py)."""
import argparse
import sys
import threading
import time

from etl.export import collect, write_outputs
from etl.graph import Graph
from etl.report import write_report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="data/work")
    ap.add_argument("--out", default="data/out")
    a = ap.parse_args()
    t0 = time.time()
    G = Graph()
    G.load(a.work)
    members, per_group, tops = collect(G)
    print(f"traced {len(per_group):,} English sections, {len(tops):,} PIE files  {time.time() - t0:.0f}s", file=sys.stderr)
    index, unrooted = write_outputs(G, a.out, members, per_group, tops)
    write_report(G, a.out, members, per_group, tops, index, unrooted)
    print(f"done in {time.time() - t0:.0f}s -> {a.out}", file=sys.stderr)


if __name__ == "__main__":
    sys.setrecursionlimit(20000)
    threading.stack_size(512 * 1024 * 1024)
    t = threading.Thread(target=main)
    t.start()
    t.join()
