"""Paired A/B comparison of two robustness reports (same scenarios and seeds, different code).

    python scripts/robustness_compare.py runs/work/robustness_baseline.md reports/robustness.md

Per scenario: conclusion-rate lift, harmful changes, incident MTTRs, winners/experiments; then paired totals.
Only reads the two Markdown reports (which come from the grader output and our own audit stores)."""
from __future__ import annotations

import re
import statistics
import sys


def parse(path):
    rows, notes = {}, {}
    for line in open(path, encoding="utf-8"):
        if line.startswith("| ") and not line.startswith(("| scenario", "|---")):
            c = [x.strip() for x in line.strip().strip("|").split("|")]
            lift = float(re.match(r"([+-][\d.]+)%", c[2]).group(1))
            harm = int(re.search(r"/(\d+)-\)", c[5]).group(1))
            w, e = c[-2].split("/")
            rows[c[0]] = {"exit": c[1], "lift": lift, "harm": harm, "winners": int(w), "exps": int(e),
                          "errors": int(c[-1])}
        m = re.match(r"- \*\*(\S+)\*\* — (.*)", line)
        if m:
            notes[m.group(1)] = [int(x) for x in re.findall(r"MTTR (\d+) min", m.group(2))]
    for k in rows:
        rows[k]["mttr"] = notes.get(k, [])
    return rows


def main(a_path, b_path):
    a, b = parse(a_path), parse(b_path)
    keys = sorted(set(a) & set(b))
    print(f"| scenario | lift A | lift B | Δ | harmful A→B | MTTR A | MTTR B | winners A→B |")
    print("|---|---|---|---|---|---|---|---|")
    dl, dh = [], []
    for k in keys:
        x, y = a[k], b[k]
        dl.append(y["lift"] - x["lift"])
        dh.append(y["harm"] - x["harm"])
        print(f"| {k} | {x['lift']:+.1f}% | {y['lift']:+.1f}% | {y['lift'] - x['lift']:+.1f} | {x['harm']}→{y['harm']} |"
              f" {x['mttr'] or '-'} | {y['mttr'] or '-'} | {x['winners']}/{x['exps']}→{y['winners']}/{y['exps']} |")
    n = len(keys)
    sd = statistics.stdev(dl) if n > 1 else 0.0
    print()
    print(f"paired over {n} runs: lift Δ mean {statistics.mean(dl):+.2f} pp (SE {sd / n ** 0.5:.2f}), "
          f"harmful Δ total {sum(dh):+d}; MTTR sum A {sum(sum(a[k]['mttr']) for k in keys)} min vs "
          f"B {sum(sum(b[k]['mttr']) for k in keys)} min; exit≠0 in B: {[k for k in keys if b[k]['exit'] != '0']}; "
          f"decision errors in B: {sum(b[k]['errors'] for k in keys)}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
