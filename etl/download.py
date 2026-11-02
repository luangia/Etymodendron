"""Download the kaikki.org raw wiktextract dump (all languages from English Wiktionary).

Resumable: re-running continues a partial download via HTTP Range.
Writes data/raw/MANIFEST.json with URL, size, Last-Modified and sha256.
"""
import argparse
import hashlib
import json
import os
import sys
import time
import urllib.request

URL = "https://kaikki.org/dictionary/raw-wiktextract-data.jsonl.gz"
CHUNK = 1 << 20


def head(url):
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req) as r:
        return int(r.headers["Content-Length"]), r.headers.get("Last-Modified")


def download(url, dest):
    total, last_modified = head(url)
    have = os.path.getsize(dest) if os.path.exists(dest) else 0
    if have < total:
        req = urllib.request.Request(url, headers={"Range": f"bytes={have}-"} if have else {})
        with urllib.request.urlopen(req) as r, open(dest, "ab" if have else "wb") as f:
            t0, done = time.time(), have
            while chunk := r.read(CHUNK):
                f.write(chunk)
                done += len(chunk)
                if done % (100 * CHUNK) < CHUNK:
                    rate = (done - have) / max(time.time() - t0, 1e-6) / 1e6
                    print(f"{done / 1e9:.2f}/{total / 1e9:.2f} GB  {rate:.1f} MB/s", flush=True)
    size = os.path.getsize(dest)
    if size != total:
        sys.exit(f"size mismatch: {size} != {total}; re-run to resume")
    h = hashlib.sha256()
    with open(dest, "rb") as f:
        while chunk := f.read(CHUNK * 8):
            h.update(chunk)
    manifest = {"url": url, "bytes": size, "last_modified": last_modified,
                "sha256": h.hexdigest(), "downloaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    with open(os.path.join(os.path.dirname(dest), "MANIFEST.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=URL)
    ap.add_argument("--dest", default="data/raw/raw-wiktextract-data.jsonl.gz")
    a = ap.parse_args()
    download(a.url, a.dest)
