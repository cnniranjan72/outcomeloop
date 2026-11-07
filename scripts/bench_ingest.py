"""Repeatable ingest benchmark: ingest the first N history chunks of a running simulator into a fresh store, time it.

    python scripts/bench_ingest.py http://127.0.0.1:8712 --chunks 8 --repeat 2

Chunks are immutable, so the same simulator serves identical bytes to every repetition. Prints events/s per run and
the best; the network read from the local simulator is included (as in production)."""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from outcomeloop.db import DB                      # noqa: E402
from outcomeloop.ingest import Ingestor            # noqa: E402
from outcomeloop.simclient import SimClient        # noqa: E402


class _TimedConn:
    """Wraps the sqlite connection to attribute time to bulk inserts and commits (test tooling only)."""

    def __init__(self, conn, ph):
        self._c, self._ph = conn, ph

    def executemany(self, *a):
        t = time.perf_counter()
        try:
            return self._c.executemany(*a)
        finally:
            self._ph["inserts"] += time.perf_counter() - t

    def execute(self, sql, *a):
        t = time.perf_counter()
        try:
            return self._c.execute(sql, *a)
        finally:
            if sql.strip().upper().startswith(("COMMIT", "END")):
                self._ph["commit"] += time.perf_counter() - t

    def __getattr__(self, k):
        return getattr(self._c, k)


def _instrument(db, ph):
    import outcomeloop.ingest as ingmod
    db.conn = _TimedConn(db.conn, ph)
    orig = ingmod.apply_rollups

    def timed(*a, **k):
        t = time.perf_counter()
        try:
            return orig(*a, **k)
        finally:
            ph["rollups"] += time.perf_counter() - t
    ingmod.apply_rollups = timed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--chunks", type=int, default=8)
    ap.add_argument("--repeat", type=int, default=2)
    ap.add_argument("--dir", default="runs", help="where the scratch store goes (avoid AV-scanned temp dirs)")
    ap.add_argument("--phases", action="store_true", help="also time inserts, rollups and commits separately")
    a = ap.parse_args()
    sim = SimClient(a.url)
    metas = sim.list_chunks("history")[: a.chunks]
    rates = []
    for r in range(a.repeat):
        with tempfile.TemporaryDirectory(dir=a.dir) as d:
            db = DB(os.path.join(d, "bench.db"))
            for w in sim.workflows():   # workflow codes as the controller registers them
                db.code("wf", w["workflow_id"])
            ing = Ingestor(db, sim)
            ph = {"inserts": 0.0, "rollups": 0.0, "commit": 0.0}
            if a.phases:
                _instrument(db, ph)
            t0 = time.perf_counter()
            n = sum(ing.ingest_chunk(m) for m in metas)
            dt = time.perf_counter() - t0
            db.conn.close()
        rates.append(n / dt)
        extra = ""
        if a.phases:
            rest = dt - sum(ph.values())
            extra = " | " + ", ".join(f"{k} {v:.1f}s ({v / dt:.0%})" for k, v in ph.items()) +                 f", fetch+parse+python {rest:.1f}s ({rest / dt:.0%})"
        print(f"run {r + 1}: {n:,} events in {dt:.1f}s -> {n / dt:,.0f} events/s{extra}")
    print(f"best: {max(rates):,.0f} events/s")


if __name__ == "__main__":
    main()
