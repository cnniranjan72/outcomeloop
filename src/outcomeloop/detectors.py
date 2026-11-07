"""Population-level detectors (never single calls). Each returns evidence dicts that go into the audit log."""
from __future__ import annotations

from .config import Settings
from .db import DB
from .stats import Prop, binom_excess, compare


def did_health(db: DB, wf: int, options: list[str], now: int, s: Settings,
               probing: set[str] | None = None) -> dict[str, dict]:
    """Classify each caller ID as healthy (measured and fine) / degraded / unknown (not enough data).

    Caller ID is randomised per dial, so within a window every DID sees the same hour and person mix in
    expectation; comparing a DID's pickup with the pooled pickup of the other DIDs isolates the number itself.
    Two windows: fast (6h, catches a sudden spam flag) and slow (24h, catches gradual decline). A DID is
    degraded if either window shows ratio < 0.85 with z < -3.5 on >= 300 dials.
    """
    out: dict[str, dict] = {}
    windows = {"fast": s.did_fast_window_minutes, "slow": s.did_slow_window_minutes}
    stats = {}
    for name, w in windows.items():
        rows = db.q("SELECT did, COUNT(*), SUM(conn) FROM calls WHERE wf=? AND minute>=? AND minute<? GROUP BY did",
                    (wf, now - w, now))
        stats[name] = {db.decode("caller_id", d): (n, c) for d, n, c in rows}
    for opt in options:
        rec = {"state": "unknown", "windows": {}}
        degraded = healthy = False
        for name in windows:
            st = stats[name]
            n, c = st.get(opt, (0, 0))
            on = sum(v[0] for k, v in st.items() if k != opt)
            oc = sum(v[1] for k, v in st.items() if k != opt)
            if n == 0 or on == 0:
                rec["windows"][name] = {"dials": n, "connected": c}
                continue
            cmp_ = compare(Prop(oc, on), Prop(c, n))
            ratio = (c / n) / (oc / on) if oc else 1.0
            # delta-method SE of the ratio; "healthy" needs the ~84% lower bound above the degraded line
            p1, p0 = (c + 1) / (n + 2), (oc + 1) / (on + 2)
            se_ratio = ratio * ((1 - p1) / (n * p1) + (1 - p0) / (on * p0)) ** 0.5
            rec["windows"][name] = {"dials": n, "connected": c, "pickup": round(c / n, 4),
                                    "others_pickup": round(oc / on, 4), "ratio": round(ratio, 3), "z": round(cmp_.z, 2)}
            rec["windows"][name]["ratio_lcb"] = round(ratio - se_ratio, 3)
            if n >= s.did_min_dials and ratio < s.did_degraded_ratio and cmp_.z < -s.did_degraded_z:
                degraded = True
            # a number on probe only has to show it is bad to stay out (low-risk action): lower bar
            if probing and opt in probing and n >= s.did_healthy_min_dials and ratio < s.did_degraded_ratio                     and cmp_.z < -2.33:
                degraded = True
            if name == "slow" and n >= s.did_healthy_min_dials and ratio - se_ratio >= s.did_degraded_ratio:
                healthy = True   # measured, and confidently not meaningfully worse than the other numbers
        rec["state"] = "degraded" if degraded else ("healthy" if healthy else "unknown")
        out[opt] = rec
    return out


def halluc_baseline(db: DB, wf: int, until: int) -> dict[str, dict]:
    """Observed QA flag rate per prompt over all history we hold (flags are noisy: FP and FN)."""
    rows = db.q("SELECT prompt, SUM(conn), SUM(flag), SUM(eng) FROM calls WHERE wf=? AND minute<? AND conn=1"
                " GROUP BY prompt", (wf, until))
    return {db.decode("prompt_version", p): {"connected": n, "flags": f, "engaged": e,
                                             "flag_rate": f / n if n else None, "engagement": e / n if n else None}
            for p, n, f, e in rows}


def halluc_spike(db: DB, wf: int, prompt: str, since: int, now: int, ref_rate: float, s: Settings) -> dict:
    """Is the flag rate on the current prompt, since `since` (window start or prompt change), above the
    workflow's own reference rate? Fires on rate > 1.5x reference and z > 3.5 with >= 250 connected calls."""
    pc = db.code("prompt_version", prompt)
    r = db.q1("SELECT COUNT(*), SUM(flag), SUM(eng) FROM calls WHERE wf=? AND minute>=? AND minute<? AND conn=1"
              " AND prompt=?", (wf, max(since, now - s.halluc_window_minutes * 6), now, pc))
    n, f, e = r[0], r[1] or 0, r[2] or 0
    rate = f / n if n else 0.0
    z = binom_excess(f, n, ref_rate) if n else 0.0
    fired = n >= s.halluc_min_connected and rate > s.halluc_ratio * ref_rate and z > s.halluc_z
    return {"prompt": prompt, "connected": n, "flags": f, "flag_rate": round(rate, 4), "ref_rate": round(ref_rate, 4),
            "z": round(z, 2), "engagement": round(e / n, 4) if n else None, "fired": fired}


def kpi_drift(db: DB, wf: int, now: int, s: Settings) -> dict:
    """Workflow-level pickup and engagement: last 24h vs the trailing 7 days before it. Alert-only."""
    def q(a, b):
        return db.q1("SELECT COUNT(*), SUM(conn), SUM(eng) FROM calls WHERE wf=? AND minute>=? AND minute<?",
                     (wf, a, b))
    rn, rc, re_ = q(now - 1440, now)
    bn, bc, be = q(now - 8 * 1440, now - 1440)
    out = {"recent": {"dials": rn, "connected": rc or 0, "engaged": re_ or 0},
           "baseline": {"dials": bn, "connected": bc or 0, "engaged": be or 0}, "alerts": []}
    if rn >= 1000 and bn >= 1000:
        pk = compare(Prop(bc, bn), Prop(rc, rn))
        out["pickup"] = {"recent": round(rc / rn, 4), "baseline": round(bc / bn, 4), "rel": round(pk.rel, 4),
                         "z": round(pk.z, 2)}
        if pk.rel < -s.drift_rel and pk.z < -s.drift_z:
            out["alerts"].append("pickup_drop")
    if (rc or 0) >= 500 and (bc or 0) >= 500:
        en = compare(Prop(be, bc), Prop(re_, rc))
        out["engagement"] = {"recent": round(re_ / rc, 4), "baseline": round(be / bc, 4), "rel": round(en.rel, 4),
                             "z": round(en.z, 2)}
        if en.rel < -s.drift_rel and en.z < -s.drift_z:
            out["alerts"].append("engagement_drop")
    return out
