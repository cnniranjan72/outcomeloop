"""Per-person call time (C4) as a randomised experiment — not a guess applied to everyone.

Hypothesis: a person who picked up at hour h before is more likely to pick up at h again. The simulator's
`schedule.lead_preferred_hour` multiplies a lead's dialling weight by 6 in its preferred hour and by 0.25 in every
other hour, so a wrong guess actively hurts that lead. We therefore:

1. take as candidates people with an active lead (inside cadence, not concluded) who connected at least once
   during the current cadence (the last cadence-length + 1 days), preferred hour = the hour of their most frequent connects (ties: earliest), inside the dialling window;
2. randomise each candidate deterministically by sha256(workflow|person): `treatment` gets a preferred hour,
   `control` does not (50/50 while testing);
3. compare pickup per dial (connected / dials) of treatment vs control, counting only dials made after the person
   became a candidate; daily looks, one-sided z at 1 % (repeated looks, at most ~5), minimum 400 dials per arm;
4. significantly better → expand to 90 % treatment (10 % holdout keeps measuring); significantly worse → stop and
   remove every preference; no evidence by the horizon (5 days) → stop: no evidence, no change.

Governance: the map changes daily as people connect, so it only runs where `schedule` is auto-appliable by policy
(an operational dimension the clients accepted); on approval-only workflows it would spend the daily request
budget, so it stays off there. The map is refreshed at most once per simulated day.
"""
from __future__ import annotations

import hashlib
import json

from .config import Settings
from .db import DB, dumps
from .stats import Prop, compare

SQL = """CREATE TABLE IF NOT EXISTS ptime_members (wf INTEGER, person INTEGER, arm TEXT, hour INTEGER,
  since_minute INTEGER, PRIMARY KEY (wf, person)) WITHOUT ROWID"""


def arm_of(workflow_id: str, person: int, treat_share: float) -> str:
    h = int.from_bytes(hashlib.sha256(f"{workflow_id}|{person}".encode()).digest()[:4], "big") / 2 ** 32
    return "treatment" if h < treat_share else "control"


class PersonTime:
    def __init__(self, db: DB, s: Settings):
        self.db = db
        self.s = s
        db.x(SQL)

    def state(self, wf: int) -> dict:
        return self.db.kv_get(f"ptime:{wf}", {"status": "off"})

    def eligible(self, spec: dict, supervisor_dims: set) -> bool:
        pol = spec["governance"]["auto_apply"]
        return bool(pol.get("enabled")) and "schedule" in pol.get("allowed_dims", []) and "schedule" not in supervisor_dims

    def refresh(self, wf: int, spec: dict, now: int) -> dict:
        """Add new candidates (deterministic arm) and return the current preference map for treated people."""
        db = self.db
        st = self.state(wf)
        if st["status"] in ("off", "stopped"):
            if st["status"] == "off":
                st = {"status": "testing", "start_minute": now, "treat_share": 0.5, "looks": []}
            else:
                return {}
        lo, hi = spec["dialling_window"]
        day, L = now // 1440, len(spec["cadence"])
        # connects during the current cadence only: a bounded (wf, minute) range scan, no extra index; these are the
        # people the dialler will retry. People returning from much older campaigns are not covered (scope limit).
        rows = db.q("""SELECT c.person, ((c.minute % 1440 + 1440) % 1440) / 60 AS h, COUNT(*) FROM calls c
                       WHERE c.wf=? AND c.minute>=? AND c.minute<? AND c.conn=1 AND c.person IN (
                         SELECT person FROM leads WHERE wf=? AND campaign_day>? AND concluded_minute IS NULL)
                       GROUP BY 1, 2""", (wf, now - (L + 1) * 1440, now, wf, day - L))
        best: dict[int, tuple[int, int]] = {}
        for person, h, n in rows:
            if lo <= h < hi and (person not in best or n > best[person][1] or (n == best[person][1] and h < best[person][0])):
                best[person] = (h, n)
        known = {p for (p,) in db.q("SELECT person FROM ptime_members WHERE wf=?", (wf,))}
        wid = spec["workflow_id"]
        new = [(wf, p, arm_of(wid, p, st["treat_share"]), h, now) for p, (h, _) in best.items() if p not in known]
        with db.tx():
            if new:
                db.conn.executemany("INSERT OR IGNORE INTO ptime_members VALUES (?,?,?,?,?)", new)
            db.kv_set(f"ptime:{wf}", st)
        active = {p for p in best}
        out = {}
        for p, arm, h in db.q("SELECT person, arm, hour FROM ptime_members WHERE wf=? AND arm='treatment'", (wf,)):
            if p in active:
                out[f"{wid}:p{p:07d}"] = int(h)
            if len(out) >= 200_000:
                break
        return out

    def look(self, wf: int, now: int) -> dict:
        """Daily look: treatment vs control pickup per dial on dials after each person became a candidate."""
        db = self.db
        st = self.state(wf)
        if st["status"] not in ("testing", "expanded"):
            return {"action": "none"}
        rows = db.q("""SELECT m.arm, COUNT(*), SUM(c.conn) FROM calls c JOIN ptime_members m
                       ON m.wf=c.wf AND m.person=c.person WHERE c.wf=? AND c.minute>=? AND c.minute<?
                       AND c.minute>=m.since_minute GROUP BY m.arm""", (wf, st["start_minute"], now))
        arms = {a: (n, k or 0) for a, n, k in rows}
        t, c = arms.get("treatment", (0, 0)), arms.get("control", (0, 0))
        res = {"minute": now, "treatment": {"dials": t[0], "connected": t[1]}, "control": {"dials": c[0], "connected": c[1]},
               "action": "continue"}
        if min(t[0], c[0]) >= 400:
            cmp_ = compare(Prop(c[1], c[0]), Prop(t[1], t[0]))
            res.update({"pickup_t": round(t[1] / t[0], 4), "pickup_c": round(c[1] / c[0], 4), "lift_rel": round(cmp_.rel, 4),
                        "z": round(cmp_.z, 2)})
            if cmp_.z < -2.33:
                res["action"] = "stop_harm"
            elif st["status"] == "testing" and cmp_.z > 2.33:
                res["action"] = "expand"
        if st["status"] == "testing" and res["action"] == "continue" and now - st["start_minute"] >= 5 * 1440:
            res["action"] = "stop_no_evidence"
        st["looks"] = (st.get("looks") or [])[-9:] + [res]
        if res["action"] == "expand":
            st["status"], st["treat_share"] = "expanded", 0.9
            with db.tx():   # newly eligible people are randomised 90/10 from now on; existing members keep their arm
                db.kv_set(f"ptime:{wf}", st)
        elif res["action"] in ("stop_harm", "stop_no_evidence"):
            st["status"] = "stopped"
            with db.tx():
                db.kv_set(f"ptime:{wf}", st)
        else:
            with db.tx():
                db.kv_set(f"ptime:{wf}", st)
        return res
