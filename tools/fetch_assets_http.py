#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

from urllib.request import Request, urlopen


def _download(url: str, out: Path, timeout: int = 60) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and out.stat().st_size > 0:
        return
    tmp = out.with_suffix(out.suffix + ".part")

    req = Request(url, headers={"User-Agent": "storyforge-fetch/0.1"})
    with urlopen(req, timeout=timeout) as resp:
        # urlopen raises for non-2xx in some cases; keep simple.
        with tmp.open("wb") as f:
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                f.write(chunk)

    tmp.replace(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("STORYFORGE_ASSETS_BASE") or "https://storyforge-assets.sfo3.digitaloceanspaces.com/assets/")
    ap.add_argument("--outdir", default=os.environ.get("STORYFORGE_ASSETS_OUTDIR") or ".")
    # Path relative to the assets base URL
    ap.add_argument("--index", default="credits/index.jsonl")
    ap.add_argument("--max", type=int, default=0, help="Limit number of files (0=all)")
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()

    base = args.base
    if not base.endswith("/"):
        base += "/"

    outdir = Path(args.outdir).resolve()

    # Fetch index.jsonl first
    index_rel = args.index
    index_url = urljoin(base, index_rel)
    index_path = outdir / index_rel
    index_path.parent.mkdir(parents=True, exist_ok=True)
    _download(index_url, index_path)

    # Also fetch SOURCES.md if present
    try:
        _download(urljoin(base, "credits/SOURCES.md"), outdir / "assets/credits/SOURCES.md")
    except Exception:
        pass

    paths: list[str] = []
    with index_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            lp = rec.get("local_path")
            if not lp:
                continue
            paths.append(str(lp))

    # De-dupe and optionally limit
    uniq = []
    seen = set()
    for p in paths:
        if p in seen:
            continue
        seen.add(p)
        uniq.append(p)
    if args.max and args.max > 0:
        uniq = uniq[: args.max]

    t0 = time.time()

    def task(rel: str) -> str:
        url = urljoin(base, rel)
        out = outdir / rel
        _download(url, out)
        return rel

    done = 0
    total = len(uniq)
    if total == 0:
        print("No files listed in index.")
        return

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(task, rel): rel for rel in uniq}
        for fut in concurrent.futures.as_completed(futs):
            rel = futs[fut]
            try:
                fut.result()
                done += 1
                if done % 50 == 0 or done == total:
                    dt = time.time() - t0
                    print(f"{done}/{total} downloaded ({dt:.1f}s)")
            except Exception as e:
                print(f"WARN failed {rel}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
