"""reports/scaling.md from two runs' own stores (1x and kx). Measured values only; the projection is labelled.

    python scripts/scale_report.py runs/scaling/load_x1_d2.db runs/scaling/load_x3_d2.db --out reports/scaling.md
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess


def stats(path):
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    q = lambda s, a=(): c.execute(s, a).fetchall()
    wfs = q("SELECT COUNT(*) FROM workflows")[0][0]
    per = {}
    for name in ("ingest_seconds", "decide_seconds", "advance_seconds", "ingest_events"):
        for m, v in q("SELECT minute, value FROM metrics WHERE name=? AND minute>=0", (name,)):
            d = per.setdefault((m - 1) // 1440, {})
            d[name] = d.get(name, 0) + v
    days = [per[d] for d in sorted(per) if d >= 0 and per[d].get("ingest_events", 0) > 0]
    hist = q("SELECT SUM(events), SUM(ingest_seconds) FROM chunks WHERE kind='history'")[0]
    live = q("SELECT SUM(events), SUM(ingest_seconds) FROM chunks WHERE kind='events'")[0]
    ticks = sorted(v for (v,) in q("SELECT a.value + b.value FROM metrics a JOIN metrics b ON a.minute=b.minute AND"
                                   " b.name='decide_seconds' WHERE a.name='ingest_seconds' AND a.minute>=0"))
    rss = q("SELECT MAX(value) FROM metrics WHERE name='rss_mb'")[0][0]
    errs = q("SELECT COUNT(*) FROM decisions WHERE kind='error'")[0][0]
    size = os.path.getsize(path) / 2**20
    return {"wfs": wfs, "days": days, "hist": hist[0] / hist[1], "live": live[0] / live[1], "rss": rss, "errs": errs,
            "p95": ticks[int(0.95 * (len(ticks) - 1))], "max": ticks[-1], "size": size}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("big")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    s1, sk = stats(a.base), stats(a.big)
    k = sk["wfs"] / s1["wfs"]
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "src"], capture_output=True, text=True).stdout.strip()

    def col(s, key):
        return " / ".join(f"{d.get(key, 0):,.1f}" if key != "ingest_events" else f"{d.get(key, 0):,.0f}" for d in s["days"])

    def ctl(s):
        return [d.get("ingest_seconds", 0) + d.get("decide_seconds", 0) for d in s["days"]]

    def mean(x):
        return sum(x) / len(x)
    c1, ck = mean(ctl(s1)), mean(ctl(sk))
    ratio = ck / c1
    proj10 = c1 * 10 * (ratio / k)   # scale the measured per-unit cost, not the raw ratio
    lines = [f"# Measured scaling: 1× vs {k:.0f}× public_03", "",
             "Generated with `scripts/scaling.sh`: `scripts/make_scale_scenario.py` makes K copies of every public_03",
             "workflow under new ids (2 simulated days, shortened history); each run is a Linux container at the",
             "grader's spec (`--cpus 4 --memory 8g`, `scripts/docker_scenario.sh`), one after the other, same code",
             f"(commit `{head}`{' + uncommitted src changes' if dirty else ''}). Every number is read from that run's",
             "own `metrics` / `chunks` tables by `scripts/scale_report.py`. Other containers ran on the host, so",
             "absolute times are conservative; the ratio is the point.", "",
             f"| | 1× ({s1['wfs']} workflows) | {k:.0f}× ({sk['wfs']} workflows) | ratio |", "|---|---|---|---|",
             f"| events per simulated day | {col(s1, 'ingest_events')} | {col(sk, 'ingest_events')} | "
             f"{mean([d['ingest_events'] for d in sk['days']]) / mean([d['ingest_events'] for d in s1['days']]):.1f}× |",
             f"| ingest seconds per simulated day | {col(s1, 'ingest_seconds')} | {col(sk, 'ingest_seconds')} | "
             f"{mean([d['ingest_seconds'] for d in sk['days']]) / mean([d['ingest_seconds'] for d in s1['days']]):.1f}× |",
             f"| decide seconds per simulated day | {col(s1, 'decide_seconds')} | {col(sk, 'decide_seconds')} | "
             f"{mean([d['decide_seconds'] for d in sk['days']]) / mean([d['decide_seconds'] for d in s1['days']]):.1f}× |",
             f"| **controller seconds per simulated day** | **{' / '.join(f'{x:.1f}' for x in ctl(s1))}** | "
             f"**{' / '.join(f'{x:.1f}' for x in ctl(sk))}** | **{ratio:.1f}×** |",
             f"| simulator seconds per simulated day (not ours) | {col(s1, 'advance_seconds')} | "
             f"{col(sk, 'advance_seconds')} | |",
             f"| history ingest throughput | {s1['hist']:,.0f} events/s | {sk['hist']:,.0f} events/s | |",
             f"| live ingest throughput | {s1['live']:,.0f} events/s | {sk['live']:,.0f} events/s | |",
             f"| per-tick controller time p95 / max | {s1['p95']:.2f} s / {s1['max']:.1f} s | "
             f"{sk['p95']:.2f} s / {sk['max']:.1f} s | |",
             f"| peak memory (ru_maxrss) | {s1['rss']:,.0f} MB | {sk['rss']:,.0f} MB | {sk['rss'] / s1['rss']:.2f}× |",
             f"| SQLite file at end | {s1['size']:,.0f} MB | {sk['size']:,.0f} MB | {sk['size'] / s1['size']:.1f}× |",
             f"| decision errors | {s1['errs']} | {sk['errs']} | |", "",
             "Reading it:", "",
             f"* Controller cost grew {ratio:.1f}× for {k:.0f}× the events and workflows.",
             f"* *Projection, not a measurement:* scaling the measured per-unit cost linearly to 10× public_03",
             f"  (≈ 8.4 M events/day, 120 workflows) gives ≈ **{proj10:.0f} s of controller time per simulated day** on",
             "  4 vCPU, against the 600 s target. Where the time goes and what changes first: see below.", ""]
    keep = ""
    if os.path.exists(a.out):
        old = open(a.out, encoding="utf-8").read()
        mark = "## Where the time goes"
        if mark in old:
            keep = old[old.index(mark):]
    open(a.out, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n" + keep)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
