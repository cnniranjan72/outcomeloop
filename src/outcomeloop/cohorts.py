"""The shared cohort object (C2) and its bootstrap from history (C3), plus cohort-level call time (C4).

A Cohort is {cohort_id, where} with the simulator's semantics. A workflow has ONE ordered CohortSet; membership
is first-match, else 'default'. Detection, experiments, the supervisor view and the config all use this set,
so a cohort id means exactly the same leads everywhere. Membership is evaluated in SQL over the feature
columns joined onto every call row, through `membership_sql`, the single implementation of the rule.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .config import Settings
from .db import DB, dumps

FEATURE_COLS = {"lang": "lang", "city_tier": "tier", "age_band": "age", "value_band": "val"}
SHORT = {"lang": "lang", "city_tier": "tier", "age_band": "age", "value_band": "value"}


@dataclass
class Cohort:
    cohort_id: str
    where: dict[str, list[str]]

    def to_config(self) -> dict:
        return {"id": self.cohort_id, "where": {k: list(v) for k, v in self.where.items()}}


def cohort_id_for(feat: str, values: list[str]) -> str:
    v = "_".join(values)
    v = v.replace("+", "p")
    return re.sub(r"[^A-Za-z0-9_]", "_", f"{SHORT[feat]}_{v}")


def membership_sql(db: DB, cohorts: list[Cohort]) -> str:
    """SQL CASE expression assigning each call row to its cohort id (first match, else 'default')."""
    if not cohorts:
        return "'default'"
    parts = []
    for c in cohorts:
        conds = []
        for feat, vals in c.where.items():
            codes = [db.code(feat, v) for v in vals]
            conds.append(f"{FEATURE_COLS[feat]} IN ({','.join(map(str, codes))})")
        parts.append(f"WHEN {' AND '.join(conds) or '1'} THEN '{c.cohort_id}'")
    return "CASE " + " ".join(parts) + " ELSE 'default' END"


def load_cohorts(db: DB, wf: int, statuses=("proposed", "live")) -> list[Cohort]:
    rows = db.q(f"SELECT cohort_id, where_json FROM cohorts WHERE wf=? AND status IN ({','.join('?' * len(statuses))})"
                " ORDER BY position", (wf, *statuses))
    import json
    return [Cohort(cid, json.loads(w)) for cid, w in rows]


def save_cohorts(db: DB, wf: int, cohorts: list[Cohort], minute: int, rationale: str, status: str = "proposed"):
    db.x("UPDATE cohorts SET status='retired' WHERE wf=? AND status IN ('proposed','live')", (wf,))
    for i, c in enumerate(cohorts):
        db.x("INSERT INTO cohorts VALUES (?,?,?,?,?,?,?) ON CONFLICT(wf, cohort_id) DO UPDATE SET position=excluded.position,"
             " where_json=excluded.where_json, status=excluded.status, rationale=excluded.rationale",
             (wf, c.cohort_id, i, dumps(c.where), status, minute, rationale))


# ---------------------------------------------------------------------------------------- bootstrap
def _g2(c: float, d: float, e: float) -> float:
    """Binomial deviance contribution of c successes in d trials vs expected e successes."""
    out = 0.0
    if c > 0 and e > 0:
        out += c * math.log(c / e)
    if d - c > 0 and d - e > 0:
        out += (d - c) * math.log((d - c) / (d - e))
    return 2 * out


def chi2_sf(x: float, df: int) -> float:
    """Upper tail of chi-square (Wilson-Hilferty normal approximation; fine for df >= 10)."""
    if df <= 0:
        return 1.0
    from .stats import phi
    z = ((x / df) ** (1 / 3) - (1 - 2 / (9 * df))) / math.sqrt(2 / (9 * df))
    return 1 - phi(z)


def hour_feature_table(db: DB, wf: int, col: str, since: int, until: int) -> dict[tuple[int, int], tuple[int, int]]:
    rows = db.q(f"SELECT {col}, ((minute % 1440 + 1440) % 1440) / 60 AS h, COUNT(*), SUM(conn) FROM calls"
                " WHERE wf=? AND minute>=? AND minute<? GROUP BY 1, 2", (wf, since, until))
    return {(v, h): (d, c) for v, h, d, c in rows}


def bootstrap_cohorts(db: DB, wf: int, s: Settings, since: int, until: int) -> tuple[list[Cohort], dict]:
    """Choose the single feature whose values have the most different hour-of-day pickup profiles
    (interaction deviance G^2 per degree of freedom, among features significant at p<0.001), merge values below the minimum share, return the CohortSet."""
    evidence = {"window": [since, until], "features": {}}
    best = None
    for feat, col in FEATURE_COLS.items():
        t = hour_feature_table(db, wf, col, since, until)
        if not t:
            continue
        N = sum(d for d, _ in t.values())
        vals = sorted({v for v, _ in t})
        hours = sorted({h for _, h in t})
        if len(vals) < 2:
            continue
        dv = {v: sum(t.get((v, h), (0, 0))[0] for h in hours) for v in vals}
        cv = {v: sum(t.get((v, h), (0, 0))[1] for h in hours) for v in vals}
        dh = {h: sum(t.get((v, h), (0, 0))[0] for v in vals) for h in hours}
        ch = {h: sum(t.get((v, h), (0, 0))[1] for v in vals) for h in hours}
        ptot = sum(cv.values()) / N
        g2 = 0.0
        for (v, h), (d, c) in t.items():
            # additive (multiplicative-odds-free) expectation: p_v * (p_h / p)
            e = d * (cv[v] / dv[v]) * ((ch[h] / dh[h]) / ptot)
            e = min(max(e, 1e-9), d - 1e-9) if d > 0 else 0
            g2 += _g2(c, d, e)
        df = (len(vals) - 1) * (len(hours) - 1)
        p = chi2_sf(g2, df)
        strength = g2 / df   # comparable across features with different numbers of values
        evidence["features"][feat] = {"g2": round(g2, 1), "df": df, "p_value": float(f"{p:.3g}"),
                                      "g2_per_df": round(strength, 2),
                                      "shares": {db.decode(feat, v): round(dv[v] / N, 3) for v in vals}}
        if p < 1e-3 and (best is None or strength > best[0]):
            best = (strength, feat, vals, dv, N)
    if best is None:
        evidence["chosen"] = None
        evidence["reason"] = "no feature explains hour-of-day pickup differences beyond noise (LR test p<0.001)"
        return [], evidence
    _, feat, vals, dv, N = best
    # group values in their natural order, merging any group below the minimum share into its neighbour
    order = sorted(vals, key=lambda v: db.decode(feat, v))
    groups: list[list[int]] = [[v] for v in order]
    share = lambda g: sum(dv[v] for v in g) / N
    while len(groups) > 1 and (min(share(g) for g in groups) < s.min_cohort_share or len(groups) > s.max_cohorts):
        i = min(range(len(groups)), key=lambda k: share(groups[k]))
        j = i - 1 if i == len(groups) - 1 else (i + 1 if i == 0 else (i - 1 if share(groups[i - 1]) < share(groups[i + 1]) else i + 1))
        lo, hi = sorted((i, j))
        groups[lo] = groups[lo] + groups[hi]
        del groups[hi]
    cohorts = []
    for g in groups:
        names = [db.decode(feat, v) for v in g]
        cohorts.append(Cohort(cohort_id_for(feat, names), {feat: names}))
    evidence["chosen"] = feat
    evidence["cohorts"] = {c.cohort_id: round(share(g), 3) for c, g in zip(cohorts, groups)}
    return cohorts, evidence


def schedule_weights(db: DB, wf: int, cohorts: list[Cohort], window: list[int], s: Settings,
                     since: int, until: int) -> tuple[dict, dict]:
    """hour_weights per cohort from smoothed pickup-by-hour; plus a historical re-weighting dry run."""
    case = membership_sql(db, cohorts)
    rows = db.q(f"SELECT {case} AS c, ((minute % 1440 + 1440) % 1440) / 60 AS h, COUNT(*), SUM(conn) FROM calls"
                " WHERE wf=? AND minute>=? AND minute<? GROUP BY 1, 2", (wf, since, until))
    lo, hi = window
    hours = list(range(lo, hi))
    tab = {(c, h): (d, k) for c, h, d, k in rows}
    names = sorted({c for c, _ in tab})
    D = sum(d for d, _ in tab.values()) or 1
    P = sum(k for _, k in tab.values()) / D
    dh = {h: sum(tab.get((c, h), (0, 0))[0] for c in names) for h in hours}
    rh = {h: ((sum(tab.get((c, h), (0, 0))[1] for c in names) / dh[h]) / P) if dh[h] else 1.0 for h in hours}
    weights, phat = {}, {}
    for c in names:
        dc = sum(tab.get((c, h), (0, 0))[0] for h in hours)
        kc = sum(tab.get((c, h), (0, 0))[1] for h in hours)
        if dc == 0:
            continue
        pc = kc / dc
        m = s.schedule_eb_strength
        w = {}
        for h in hours:
            d, k = tab.get((c, h), (0, 0))
            ph = (k + m * pc * rh[h]) / (d + m)
            phat[(c, h)] = ph
            w[str(h)] = round(min(max((ph / pc) ** s.schedule_gamma, s.schedule_w_min), s.schedule_w_max), 3)
        weights[c] = w
    # dry run: hold per-hour dial volume fixed, re-weight cohort mix by the new weights
    old_conn = new_conn = tot = 0.0
    for h in hours:
        mix = {c: tab.get((c, h), (0, 0))[0] for c in names}
        dtot = sum(mix.values())
        if not dtot:
            continue
        neww = {c: mix[c] * weights.get(c, {}).get(str(h), 1.0) for c in names}
        z = sum(neww.values()) or 1
        for c in names:
            p = phat.get((c, h), 0.0)
            old_conn += mix[c] * p
            new_conn += dtot * neww[c] / z * p
        tot += dtot
    dry = {"method": "historical re-weighting at fixed per-hour dial volume (ignores lead-pool depletion, so an"
                     " upper bound)", "window": [since, until], "dials": int(tot),
           "pickup_old": round(old_conn / tot, 4) if tot else None,
           "pickup_new": round(new_conn / tot, 4) if tot else None,
           "rel_lift": round(new_conn / old_conn - 1, 4) if old_conn else 0.0}
    return weights, dry
