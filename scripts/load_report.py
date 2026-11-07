"""Build reports/public_03.md from MEASURED values only: our own metrics table, the DB file, the grader output.

    python scripts/load_report.py --db state/public_03_load.db --grade reports/public_03_grade.md \
        --wall <controller wall seconds> --out reports/public_03.md
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import sqlite3
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--grade", required=True)
    ap.add_argument("--wall", type=float, required=True, help="controller wall-clock seconds (run.sh start→exit)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--note", default="")
    a = ap.parse_args()
    c = sqlite3.connect(a.db)
    q = lambda sql, *args: c.execute(sql, args).fetchall()

    hist = q("SELECT SUM(events), SUM(ingest_seconds), COUNT(*) FROM chunks WHERE kind='history'")[0]
    live = q("SELECT SUM(events), SUM(ingest_seconds), COUNT(*) FROM chunks WHERE kind='events'")[0]
    per_chunk = q("SELECT events, ingest_seconds FROM chunks WHERE kind='events' AND events > 0")
    peak_rate = max((e / s for e, s in per_chunk if s > 0), default=0)
    days = q("SELECT labels, value FROM metrics WHERE name='controller_seconds_per_sim_day' ORDER BY id")
    walls = {json.loads(l)["day"]: v for l, v in q("SELECT labels, value FROM metrics WHERE name="
                                                       "'wall_seconds_per_sim_day' ORDER BY id")}
    ticks = q("SELECT m1.value, m2.value FROM metrics m1 JOIN metrics m2 ON m1.minute=m2.minute AND"
              " m2.name='decide_seconds' WHERE m1.name='ingest_seconds'")
    tick_ctrl = sorted(i + d for i, d in ticks)
    p = lambda xs, f: xs[min(int(len(xs) * f), len(xs) - 1)] if xs else 0
    lag = q("SELECT MAX(value) FROM metrics WHERE name='ingest_lag_minutes'")[0][0]
    rss = q("SELECT MAX(value) FROM metrics WHERE name='rss_mb'")[0][0]
    n_calls = q("SELECT COUNT(*) FROM calls")[0][0]
    n_wf = q("SELECT COUNT(*) FROM workflows")[0][0]
    dec = q("SELECT COUNT(*) FROM decisions")[0][0]
    props = dict(q("SELECT state, COUNT(*) FROM proposals GROUP BY state"))
    size = sum(os.path.getsize(a.db + s) for s in ("", "-wal") if os.path.exists(a.db + s)) / 2 ** 20
    grade = Path(a.grade).read_text(encoding="utf-8")
    table = grade.split("## Changes applied")[0].split("## Outcomes vs baseline (no-op controller)")[-1].strip()

    L = ["# public_03_load — load test (measured)", "",
         f"Machine: {platform.platform()}, {os.cpu_count()} logical CPUs, Python {platform.python_version()}. "
         + a.note, "",
         "All numbers below are read from the controller's own `metrics`/`chunks` tables and the DB file after the"
         " run; nothing is estimated unless marked *(derived)*.", "",
         "## Throughput and latency", "",
         "| measure | value |", "|---|---|",
         f"| workflows | {n_wf} |",
         f"| history events ingested (pre-D0) | {hist[0]:,} in {hist[1]:.1f}s → {hist[0] / max(hist[1], 1e-9):,.0f} events/s |",
         f"| live events ingested (D0–end) | {live[0]:,} in {live[1]:.1f}s → {live[0] / max(live[1], 1e-9):,.0f} events/s |",
         f"| peak per-chunk ingest rate | {peak_rate:,.0f} events/s |",
         f"| call rows stored | {n_calls:,} |",
         f"| controller time per 15-min tick (ingest + decide), p50 / p95 / max | {p(tick_ctrl, .5):.2f}s / "
         f"{p(tick_ctrl, .95):.2f}s / {max(tick_ctrl, default=0):.2f}s |",
         f"| max ingest lag (sim minutes behind the simulator after a tick) | {lag} |",
         f"| peak controller memory (peak working set / max RSS) | {rss:.0f} MB |",
         f"| SQLite size at end (db + wal) | {size:,.0f} MB |",
         f"| decisions recorded | {dec:,} |",
         f"| proposals by state | {props} |",
         f"| controller wall-clock, whole run incl. waiting on the simulator | {a.wall:.0f}s |", "",
         "## Per simulated day", "",
         "| day | events | ingest s | decide s | controller s (ingest+decide) | simulator advance s | wall s |",
         "|---|---|---|---|---|---|---|"]
    for l, v in days:
        d = json.loads(l)
        L.append(f"| D{d['day']} | {d.get('events', 0):,} | {d.get('ingest_s', 0):.1f} | {d.get('decide_s', 0):.1f} | "
                 f"{v:.1f} | {d.get('advance_s', 0):.1f} | {walls.get(d['day'], 0):.1f} |")
    L += ["", "SRE target: ingest and decide on one simulated day in < 10 wall-clock minutes (600 s). The"
          " *controller s* column is our share; *simulator advance s* is the simulator generating the world, which"
          " in production is the real dialler and does not run on our box.", "",
          "## Outcomes (sim grade vs no-op baseline)", "", table, ""]
    Path(a.out).write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
