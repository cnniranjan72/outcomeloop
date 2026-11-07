"""Population-level detectors (never single calls). Each returns evidence dicts that go into the audit log."""
from __future__ import annotations

from .config import Settings
from .db import DB
from .stats import Prop, binom_excess, compare


def did_health(db: DB, wf: int, options: list[str], now: int, s: Settings,
               probing: set[str] | None = None, since: dict[str, int] | None = None,
               own_past: dict[str, tuple[int, int]] | None = None) -> dict[str, dict]:
    """Classify each caller ID as healthy (measured and fine) / degraded / unknown (not enough data).

    Caller ID is randomised per dial, so within a window every DID sees the same hour and person mix in
    expectation; comparing a DID's pickup with the pooled pickup of the other DIDs isolates the number itself.
    Windows: fast (6h, catches a sudden spam flag) and slow (24h, gradual decline) decide "degraded" (ratio < 0.85,
    z < -3.5, >= 300 dials, and — when the number has a week of its own history — a drop of > 15% against that
    history with z < -3, so steady volume fatigue next to a fresh number is not mistaken for a flag); "healthy"
    may also use a long 72h window so low-volume probes can complete.
    """
    out: dict[str, dict] = {}
    windows = {"fast": s.did_fast_window_minutes, "slow": s.did_slow_window_minutes,
               "long": s.did_long_window_minutes}
    stats = {}
    def window(lo):   # hourly rollup (hour resolution): a few rows per workflow-hour instead of every call
        rows = db.q("SELECT did, SUM(dials), SUM(conn) FROM did_hour WHERE wf=? AND hb>=? AND hb<? GROUP BY did",
                    (wf, lo // 60, -(-now // 60)))
        return {db.decode("caller_id", d): (n, c) for d, n, c in rows}
    for name, w in windows.items():
        stats[name] = window(now - w)
    # each number's own recent past (the week before the slow window): a spam flag is a drop against it,
    # while volume fatigue is steady — the relative test alone cannot tell the two apart
    if own_past is None:
        own_past = did_own_past(db, wf, now, s)
    since = since or {}
    for opt in options:
        rec = {"state": "unknown", "windows": {}}
        degraded = healthy = False
        for name in windows:
            st = stats[name]
            # evidence must postdate the number's last state change (a re-probe must not be judged on data from
            # before it was flagged)
            lo = since.get(opt)
            if lo is not None and lo > now - windows[name]:
                st = window(lo)
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
            pn, pc = own_past.get(opt, (0, 0))
            self_cmp = compare(Prop(pc, pn), Prop(c, n)) if pn >= s.did_min_dials else None
            if self_cmp is not None:
                rec["windows"][name]["own_past_pickup"] = round(pc / pn, 4)
                rec["windows"][name]["z_vs_own_past"] = round(self_cmp.z, 2)
            # a number in rotation with its own history must also have dropped against that history
            dropped = self_cmp is None or (self_cmp.rel < -0.15 and self_cmp.z < -3.0)
            if name != "long" and n >= s.did_min_dials and ratio < s.did_degraded_ratio and cmp_.z < -s.did_degraded_z                     and dropped:
                degraded = True
            # a number on probe only has to show it is bad to stay out (low-risk action): lower bar
            if name != "long" and probing and opt in probing and n >= s.did_healthy_min_dials \
                    and ratio < s.did_degraded_ratio and cmp_.z < -2.33 and dropped:
                degraded = True
            # healthy may use the 72h window: a 5% probe on a small workflow never reaches the minimum in 24h
            if name in ("slow", "long") and n >= s.did_healthy_min_dials and ratio - se_ratio >= s.did_degraded_ratio:
                healthy = True   # measured, and confidently not meaningfully worse than the other numbers
        rec["state"] = "degraded" if degraded else ("healthy" if healthy else "unknown")
        out[opt] = rec
    return out


def did_own_past(db: DB, wf: int, now: int, s: Settings) -> dict[str, tuple[int, int]]:
    """Per-number dials/connected over the week before the slow window (the number's own baseline)."""
    rows = db.q("SELECT did, SUM(dials), SUM(conn) FROM did_hour WHERE wf=? AND hb>=? AND hb<? GROUP BY did",
                (wf, (now - 7 * 1440 - s.did_slow_window_minutes) // 60, (now - s.did_slow_window_minutes) // 60))
    return {db.decode("caller_id", d): (n, c) for d, n, c in rows}


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


def incident_interaction(db: DB, wf: int, bad_prompt: str, until: int, min_connected: int = 150,
                         alpha: float = 0.05) -> dict:
    """Did the bad prompt hurt some variant options more than others (incident x variant interaction)?

    Welcome message, voice and caller ID are randomised per dial both before and during a prompt incident. For each
    option o present in both windows, (QA flag rate during - before) for o minus the same change for the *other
    options present in both windows* is a randomised difference-in-differences: anything that moved every option
    alike (time, campaign mix, the prompt's main effect) cancels. The comparison group is restricted to options
    present in both windows — comparing o with W3 before and W2 during would compare different things.

    Only the QA flag rate can raise an interaction: hallucination is what a prompt changes, and options do not have
    their own flag trends. Engagement is reported but never flagged: an option's engagement effect can change over
    the window by itself (a decaying winner), which a before/during comparison cannot tell apart from an interaction.
    Two-sided, Bonferroni across the flag tests; every cell needs `min_connected` connected calls.

    Diagnostic only: the fix (reverting the prompt) is workflow-wide either way."""
    from .stats import z_of
    pc = db.code("prompt_version", bad_prompt)
    first = db.q1("SELECT MIN(minute) FROM calls WHERE wf=? AND prompt=? AND minute<?", (wf, pc, until))[0]
    if first is None:
        return {"checked": False, "reason": "no calls on the incident prompt"}
    lo = first - 1440
    names = {(kind, c): value for (kind, value), c in db._codes.items()}
    tests, out = [], {"checked": True, "window_before": [lo, first], "window_during": [first, until], "dims": {},
                      "interactions": [], "flagged_metric": "flag"}

    def rate_did(o, r, i):
        p = [x[i] / x[0] for x in (o[1], o[0], r[1], r[0])]
        did = (p[0] - p[1]) - (p[2] - p[3])
        se = sum(q * (1 - q) / x[0] for q, x in zip(p, (o[1], o[0], r[1], r[0]))) ** 0.5
        return round(did, 4), round(did / se, 2) if se else 0.0

    for dim, col in (("welcome_message", "wm"), ("voice", "voice"), ("caller_id", "did")):
        rows = db.q(f"SELECT {col}, prompt=?, COUNT(*), SUM(flag), SUM(eng) FROM calls WHERE wf=? AND conn=1 AND"
                    " ((minute>=? AND minute<? AND prompt!=?) OR (minute>=? AND minute<? AND prompt=?)) GROUP BY 1, 2",
                    (pc, wf, lo, first, pc, first, until, pc))
        cells: dict[int, dict[int, tuple[int, int, int]]] = {}
        for opt, during, n, f, e in rows:
            cells.setdefault(opt, {})[during] = (n, f or 0, e or 0)
        both = {o: (c.get(0, (0, 0, 0)), c.get(1, (0, 0, 0))) for o, c in cells.items()}
        ok = sorted(o for o, (b, d) in both.items() if min(b[0], d[0]) >= min_connected)
        recs = {}
        for opt in sorted(both):
            name = names.get((dim, opt), str(opt))
            b, d = both[opt]
            if opt not in ok:
                recs[name] = {"insufficient": True, "connected": [b[0], d[0]]}
                continue
            others = [both[o] for o in ok if o != opt]
            if not others:
                recs[name] = {"insufficient": True, "connected": [b[0], d[0]], "reason": "no comparison option"}
                continue
            rest = tuple(tuple(sum(x[w][i] for x in others) for i in range(3)) for w in (0, 1))
            fd, fz = rate_did((b, d), rest, 1)
            ed, ez = rate_did((b, d), rest, 2)
            recs[name] = {"connected": [b[0], d[0]], "flag": {"did": fd, "z": fz},
                          "engagement": {"did": ed, "z": ez, "descriptive_only": True}}
            tests.append((dim, name, fz))
        out["dims"][dim] = recs
    zc = z_of(alpha / 2 / max(len(tests), 1))
    out["z_critical"] = round(zc, 2)
    out["tests"] = len(tests)
    out["interactions"] = [{"dim": d, "option": o, "metric": "flag", "z": z} for d, o, z in tests if abs(z) > zc]
    return out
