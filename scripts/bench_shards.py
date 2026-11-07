"""Measured sharding prototype: N processes each ingest only their workflows (sha256(workflow_id) mod N) from the
same history chunks of a running simulator, each into its own store, all at once. Reports wall time, aggregate
events/s and the speed-up over one process, and checks that the shards together stored exactly the rows one process
stores (no loss, no duplicates).

    python scripts/bench_shards.py http://127.0.0.1:8712 --chunks 8 --shards 1 2 4

This measures ingest only (the first thing that breaks at 10×). Decisions shard the same way (workflows are
independent) except the shared credit budget; the loop's single clock (`/sim/advance`) would need one coordinator.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "src")

WORKER = r"""
import sys, time
sys.path.insert(0, {src!r})
from outcomeloop.db import DB
from outcomeloop.ingest import Ingestor, shard_of
from outcomeloop.simclient import SimClient
url, path, k, n, chunks = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
sim = SimClient(url)
mine = {{w["workflow_id"] for w in sim.workflows() if shard_of(w["workflow_id"], n) == k}}
db = DB(path)
for w in sorted(mine):
    db.code("wf", w)
ing = Ingestor(db, sim, workflows=mine if n > 1 else None)
t0 = time.perf_counter()
for m in sim.list_chunks("history")[:chunks]:
    ing.ingest_chunk(m)
print(f"{{time.perf_counter() - t0:.2f}} {{len(mine)}}", flush=True)
"""


def calls_in(path):
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return c.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
    finally:
        c.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--chunks", type=int, default=8)
    ap.add_argument("--shards", type=int, nargs="+", default=[1, 2, 4])
    ap.add_argument("--dir", default="runs")
    a = ap.parse_args()
    code = WORKER.format(src=SRC)
    base_rows = base_wall = None
    total_events = None
    print("| shards | wall s | per-shard s (workflows) | events/s (aggregate) | speed-up | call rows |")
    print("|---|---|---|---|---|---|")
    for n in a.shards:
        with tempfile.TemporaryDirectory(dir=a.dir) as d:
            paths = [os.path.join(d, f"s{k}.db") for k in range(n)]
            t0 = time.perf_counter()
            ps = [subprocess.Popen([sys.executable, "-c", code, a.url, p, str(k), str(n), str(a.chunks)],
                                   stdout=subprocess.PIPE, text=True) for k, p in enumerate(paths)]
            outs = [p.communicate()[0].split() for p in ps]
            wall = time.perf_counter() - t0
            if any(p.returncode for p in ps):
                raise SystemExit(f"a shard failed: {[p.returncode for p in ps]}")
            rows = sum(calls_in(p) for p in paths)
        if total_events is None:
            import json
            import urllib.request
            metas = json.load(urllib.request.urlopen(f"{a.url}/events/chunks?kind=history"))[: a.chunks]
            total_events = sum(m["events"] for m in metas)
        if base_rows is None:
            base_rows, base_wall = rows, wall
        ok = "same" if rows == base_rows else f"MISMATCH ({rows} vs {base_rows})"
        per = ", ".join(f"{o[0]} ({o[1]})" for o in outs)
        print(f"| {n} | {wall:.1f} | {per} | {total_events / wall:,.0f} | {base_wall / wall:.2f}× | {rows:,} {ok} |",
              flush=True)


if __name__ == "__main__":
    main()
