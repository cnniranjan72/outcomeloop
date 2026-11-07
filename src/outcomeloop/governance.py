"""Governance client (C9): proposal lifecycle, timing, fatigue, auto-apply, crash-safe reconciliation.

Proposal states (ours):
  approval route: SUBMITTING → PENDING → APPROVED → APPLYING → APPLIED
                      ↘ SUBMIT_FAILED   ↘ REJECTED | EXPIRED    ↘ LAPSED | STALE
                  PENDING/APPROVED → WITHDRAWN (we no longer want it; never applied, still counts toward fatigue)
  auto route:     AUTO_APPLYING → APPLIED | AUTO_DENIED | AUTO_FAILED

Crash-safety rule: the row (with deterministic id and full body) is committed BEFORE the HTTP call; after any
uncertain outcome we reconcile against `/approvals` or `/config/history` before doing anything else.
"""
from __future__ import annotations

import json
import logging

from .config import Settings
from .db import DB, dumps
from .simclient import ApiError, SimClient, Uncertain
from .timeutil import minute_to_label, next_working, ts_to_minute

log = logging.getLogger("outcomeloop.gov")

OPEN_STATES = ("SUBMITTING", "PENDING", "APPROVED", "APPLYING")


class Governance:
    def __init__(self, db: DB, sim: SimClient, s: Settings):
        self.db = db
        self.sim = sim
        self.s = s

    # ------------------------------------------------------------------ queries
    def open_proposal(self, wf: int) -> tuple | None:
        return self.db.q1(f"SELECT proposal_id, state, kind, base_version, approval_id FROM proposals WHERE wf=? AND"
                          f" route='approval' AND state IN ({','.join('?' * len(OPEN_STATES))})", (wf, *OPEN_STATES))

    def requests_last_24h(self, wf: int, now: int) -> int:
        # every request the approver received counts, whatever happened to it afterwards
        r = self.db.q1("SELECT COUNT(*) FROM proposals WHERE wf=? AND route='approval' AND state NOT IN"
                       " ('SUBMIT_FAILED') AND created_minute > ?", (wf, now - 1440))
        return r[0]

    def fatigue_cap(self, spec: dict) -> int:
        pol = spec["governance"]["max_requests_per_24h"]
        pref = self.s.tenant_pref(spec["tenant_id"]).get("max_requests_per_24h")
        return min(pol, pref) if pref else pol

    def can_request(self, wf: int, spec: dict, now: int, emergency: bool) -> tuple[bool, str]:
        cap = self.fatigue_cap(spec)
        used = self.requests_last_24h(wf, now)
        routine_cap = cap - 1 if cap >= 2 else cap   # keep one slot for incidents
        if used >= cap:
            return False, f"fatigue: {used}/{cap} requests in trailing 24h"
        if not emergency and used >= routine_cap:
            return False, f"fatigue: {used}/{cap} used, last slot reserved for incidents"
        r = self.db.q1("SELECT MAX(updated_minute) FROM proposals WHERE wf=? AND state='REJECTED'", (wf,))
        if not emergency and r[0] is not None and now - r[0] < self.s.reject_cooldown_hours * 60:
            return False, "cool-down after a rejection"
        return True, "ok"

    def submit_window(self, spec: dict, now: int, emergency: bool = False) -> tuple[bool, str]:
        """Only send when a human is there, after the tenant's preferred start, and when even the slowest
        approver response lands before the request expires. For an emergency the fastest response is enough:
        an expired emergency request costs one request slot, waiting costs customers."""
        g = spec["governance"]
        lo, hi = g["approver_hours"]
        lo = max(lo, self.s.tenant_pref(spec["tenant_id"]).get("not_before_hour", lo))
        h = (now % 1440) / 60
        if not lo <= h < hi:
            return False, f"outside approver hours [{lo},{hi})"
        worst = next_working(now + g["approver_latency_minutes"][1 if not emergency else 0], g["approver_hours"])
        ttl = g["proposal_ttl_hours"] * 60
        if worst > now + ttl - 30:
            return False, f"{'best' if emergency else 'worst'}-case decision {minute_to_label(worst)} would be after expiry"
        return True, "ok"

    # ------------------------------------------------------------------ submit / auto-apply
    def new_id(self, workflow_id: str, now: int) -> str:
        n = self.db.q1("SELECT COUNT(*) FROM proposals")[0]
        return f"ol-{workflow_id}-{now}-{n + 1}"

    def submit(self, wf: int, workflow_id: str, kind: str, body: dict, now: int) -> tuple[str, dict | None]:
        pid = body["proposal_id"]
        with self.db.tx():
            self.db.x("INSERT INTO proposals (proposal_id, wf, route, state, kind, base_version, body, created_minute,"
                      " updated_minute) VALUES (?,?,?,?,?,?,?,?,?)",
                      (pid, wf, "approval", "SUBMITTING", kind, body["base_version"], dumps(body), now, now))
        try:
            resp = self.sim.request_approval(body)
        except Uncertain as e:
            log.warning("submit %s uncertain: %s — reconciling", pid, e)
            self.reconcile_submitting(wf, workflow_id, now)
            r = self.db.q1("SELECT state FROM proposals WHERE proposal_id=?", (pid,))
            return r[0], None
        except ApiError as e:
            state = "STALE" if e.code == "stale_base_version" else "SUBMIT_FAILED"
            if e.code == "duplicate_proposal_id":   # it did land earlier: reconcile
                self.reconcile_submitting(wf, workflow_id, now)
                return self.db.q1("SELECT state FROM proposals WHERE proposal_id=?", (pid,))[0], None
            with self.db.tx():
                self._set(pid, state, now, notes=f"{e.code}: {e.detail}")
                self.db.decide(now, wf, "proposal_failed", f"{pid} not accepted by simulator ({e.code})",
                               evidence={"detail": e.detail}, outcome=state, proposal_id=pid)
            return state, None
        with self.db.tx():
            self.db.x("UPDATE proposals SET state='PENDING', approval_id=?, approval=?, updated_minute=? WHERE proposal_id=?",
                      (resp["approval_id"], dumps(resp), now, pid))
        return "PENDING", resp

    def auto_apply(self, wf: int, workflow_id: str, kind: str, body: dict, now: int,
                   on_applied=None) -> tuple[str, dict | None]:
        pid = body["proposal_id"]
        with self.db.tx():
            self.db.x("INSERT INTO proposals (proposal_id, wf, route, state, kind, base_version, body, created_minute,"
                      " updated_minute) VALUES (?,?,?,?,?,?,?,?,?)",
                      (pid, wf, "auto", "AUTO_APPLYING", kind, body["base_version"], dumps(body), now, now))
        try:
            resp = self.sim.auto_apply(workflow_id, body)
        except Uncertain:
            self.reconcile_auto(wf, workflow_id, now)
            return self.db.q1("SELECT state FROM proposals WHERE proposal_id=?", (pid,))[0], None
        except ApiError as e:
            with self.db.tx():
                self._set(pid, "AUTO_DENIED" if e.status == 403 else "AUTO_FAILED", now, notes=f"{e.code}: {e.detail}")
            return ("AUTO_DENIED" if e.status == 403 else "AUTO_FAILED"), {"error": e.code, "detail": e.detail}
        with self.db.tx():
            self.db.x("UPDATE proposals SET state='APPLIED', applied_version=?, updated_minute=? WHERE proposal_id=?",
                      (resp["version"], now, pid))
            if on_applied:
                on_applied()
        return "APPLIED", resp

    # ------------------------------------------------------------------ polling / applying
    def tick(self, now: int, specs: dict[int, dict], on_change) -> None:
        """Poll every open approval; apply approved ones. on_change(kind, wf, pid, info) records audit."""
        rows = self.db.q("SELECT proposal_id, wf, state, approval_id, base_version, kind FROM proposals WHERE"
                         " route='approval' AND state IN ('PENDING','APPROVED','APPLYING') ORDER BY CASE kind WHEN"
                         " 'incident' THEN 0 WHEN 'urgent' THEN 1 ELSE 2 END, created_minute")
        # emergencies first; a routine approval waits while an emergency for the same workflow is still open, so our
        # own routine change can never make the safety fix stale (approvals cannot be withdrawn remotely)
        emergency_open = {wf for _, wf, _, _, _, kind in rows if kind in ("incident", "urgent")}
        for pid, wf, state, aid, base, kind in rows:
            spec = specs[wf]
            wid = spec["workflow_id"]
            try:
                ap = self.sim.approval(aid)
            except ApiError as e:
                log.error("poll %s failed: %s", aid, e)
                continue
            st = ap["status"]
            if st == "pending":
                continue
            if st in ("rejected", "expired"):
                with self.db.tx():
                    self._set(pid, st.upper(), now, approval=ap)
                    on_change(st, wf, pid, ap)
                continue
            if st == "applied":
                with self.db.tx():
                    self.db.x("UPDATE proposals SET state='APPLIED', approval=?, applied_version=COALESCE(applied_version, ?),"
                              " updated_minute=? WHERE proposal_id=?", (dumps(ap), ap.get("applied_version"), now, pid))
                continue
            if st == "lapsed":
                with self.db.tx():
                    self._set(pid, "LAPSED", now, approval=ap)
                    on_change("lapsed", wf, pid, ap)
                continue
            if st == "approved" and kind not in ("incident", "urgent") and wf in emergency_open:
                if state == "PENDING":
                    with self.db.tx():
                        self._set(pid, "APPROVED", now, approval=ap)
                        on_change("approved", wf, pid, ap)
                continue   # apply after the emergency (it will likely go stale and be re-planned: intended)
            if st == "approved":
                if state == "PENDING":
                    with self.db.tx():
                        self._set(pid, "APPROVED", now, approval=ap)
                        on_change("approved", wf, pid, ap)
                self._apply(pid, wf, wid, aid, base, now, on_change)

    def _apply(self, pid, wf, wid, aid, base, now, on_change):
        cur = self.sim.config(wid)
        if cur["version"] != base:
            # someone (a supervisor) changed the config after we proposed: never force it, re-plan instead
            with self.db.tx():
                self._set(pid, "STALE", now, notes=f"base v{base} != current v{cur['version']} ({cur['actor']})")
                on_change("stale", wf, pid, {"base_version": base, "current_version": cur["version"],
                                             "current_actor": cur["actor"]})
            return
        with self.db.tx():
            self._set(pid, "APPLYING", now)
        try:
            resp = self.sim.apply(wid, aid)
        except Uncertain:
            self.reconcile_applying(pid, wf, wid, aid, now, on_change)
            return
        except ApiError as e:
            state = {"stale_base_version": "STALE", "approval_lapsed": "LAPSED"}.get(e.code, "APPROVED")
            with self.db.tx():
                self._set(pid, state, now, notes=f"apply: {e.code}: {e.detail}")
                on_change(state.lower(), wf, pid, {"error": e.code, "detail": e.detail})
            return
        with self.db.tx():
            self.db.x("UPDATE proposals SET state='APPLIED', applied_version=?, updated_minute=? WHERE proposal_id=?",
                      (resp["version"], now, pid))
            on_change("applied", wf, pid, resp)

    # ------------------------------------------------------------------ reconciliation (restart, uncertainty)
    def reconcile_all(self, specs: dict[int, dict], now: int, on_change) -> list[str]:
        notes = []
        for pid, wf, state, aid in self.db.q("SELECT proposal_id, wf, state, approval_id FROM proposals WHERE state IN"
                                             " ('SUBMITTING','APPLYING','AUTO_APPLYING')"):
            wid = specs[wf]["workflow_id"]
            if state == "SUBMITTING":
                self.reconcile_submitting(wf, wid, now)
            elif state == "APPLYING":
                self.reconcile_applying(pid, wf, wid, aid, now, on_change)
            else:
                self.reconcile_auto(wf, wid, now)
            new = self.db.q1("SELECT state FROM proposals WHERE proposal_id=?", (pid,))[0]
            notes.append(f"{pid}: {state} -> {new}")
            with self.db.tx():
                self.db.decide(now, wf, "recovery_reconcile", f"reconciled {pid}: {state} -> {new}", proposal_id=pid,
                               reasoning="state was uncertain at shutdown; resolved against the simulator before any retry")
        # also pick up approvals the simulator knows that we lost track of (should never happen; verify anyway)
        known = {r[0] for r in self.db.q("SELECT approval_id FROM proposals WHERE approval_id IS NOT NULL")}
        for wf, spec in specs.items():
            for ap in self.sim.approvals(workflow_id=spec["workflow_id"]):
                if ap["approval_id"] not in known and ap["proposal_id"].startswith("ol-"):
                    # landed remotely although our row says it did not (uncertain submit reconciled too early):
                    # adopt it so it is applied or expires under our control and counts toward fatigue
                    st = {"pending": "PENDING", "approved": "APPROVED", "rejected": "REJECTED", "expired": "EXPIRED",
                          "applied": "APPLIED", "lapsed": "LAPSED"}[ap["status"]]
                    with self.db.tx():
                        n = self.db.x("UPDATE proposals SET state=?, approval_id=?, approval=?, updated_minute=? WHERE"
                                      " proposal_id=?", (st, ap["approval_id"], dumps(ap), now, ap["proposal_id"])).rowcount
                    if not n:
                        # no local row at all (state rebuilt after corruption). A terminal remote status is a fact and
                        # is recorded as such (APPLIED with the version the simulator's config history attributes to
                        # this approval; REJECTED / EXPIRED / LAPSED). A still-open one (pending / approved) is
                        # WITHDRAWN: we no longer hold the context that justified it, so it is never applied. Either
                        # way it counts toward the approver's fatigue budget.
                        if st in ("PENDING", "APPROVED"):
                            st, ver, why = "WITHDRAWN", None, "orphan adopted after state loss; open, never applied"
                        elif st == "APPLIED":
                            ver = next((h["version"] for h in self.sim.config_history(spec["workflow_id"])
                                        if h.get("approval_id") == ap["approval_id"]), None)
                            why = (f"orphan adopted after state loss; applied remotely as v{ver} (config history)"
                                   if ver is not None else "orphan adopted after state loss; simulator reports applied,"
                                   " version not found in config history")
                        else:
                            ver, why = None, f"orphan adopted after state loss; {ap['status']} remotely"
                        with self.db.tx():
                            self.db.x("INSERT OR IGNORE INTO proposals (proposal_id, wf, route, state, kind, base_version,"
                                      " body, approval_id, approval, applied_version, created_minute, updated_minute,"
                                      " notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                      (ap["proposal_id"], wf, "approval", st, "adopted", ap["base_version"],
                                       "{}", ap["approval_id"], dumps(ap), ver,
                                       ts_to_minute(ap["created_at"]) if ap.get("created_at") else now, now, why))
                            self.db.decide(now, wf, "recovery_reconcile", f"orphan approval {ap['approval_id']}"
                                           f" ({ap['proposal_id']}) adopted as {st}", proposal_id=ap["proposal_id"],
                                           approval_id=ap["approval_id"], config_version=ver, evidence=ap, reasoning=why)
                    notes.append(f"orphan approval {ap['approval_id']} for {ap['proposal_id']}: adopted as {st}"
                                 + ("" if n else " (no local context)"))
        return notes

    def reconcile_submitting(self, wf: int, wid: str, now: int):
        remote = {a["proposal_id"]: a for a in self.sim.approvals(workflow_id=wid)}
        for (pid,) in self.db.q("SELECT proposal_id FROM proposals WHERE wf=? AND state='SUBMITTING'", (wf,)):
            ap = remote.get(pid)
            with self.db.tx():
                if ap:
                    st = {"pending": "PENDING", "approved": "APPROVED", "rejected": "REJECTED", "expired": "EXPIRED",
                          "applied": "APPLIED", "lapsed": "LAPSED"}[ap["status"]]
                    self.db.x("UPDATE proposals SET state=?, approval_id=?, approval=?, updated_minute=? WHERE proposal_id=?",
                              (st, ap["approval_id"], dumps(ap), now, pid))
                else:
                    self._set(pid, "SUBMIT_FAILED", now, notes="not found remotely after uncertain submit")

    def reconcile_applying(self, pid, wf, wid, aid, now, on_change):
        ap = self.sim.approval(aid)
        with self.db.tx():
            if ap["status"] == "applied":
                hist = self.sim.config_history(wid)
                ver = next((h["version"] for h in hist if h.get("approval_id") == aid), None)
                self.db.x("UPDATE proposals SET state='APPLIED', applied_version=?, approval=?, updated_minute=? WHERE"
                          " proposal_id=?", (ver, dumps(ap), now, pid))
                on_change("applied", wf, pid, {"version": ver, "reconciled": True})
            elif ap["status"] == "approved":
                self._set(pid, "APPROVED", now, approval=ap)   # safe to retry on next tick
            else:
                self._set(pid, ap["status"].upper(), now, approval=ap)

    def reconcile_auto(self, wf, wid, now):
        hist = {h.get("proposal_id"): h for h in self.sim.config_history(wid) if h.get("proposal_id")}
        for (pid,) in self.db.q("SELECT proposal_id FROM proposals WHERE wf=? AND state='AUTO_APPLYING'", (wf,)):
            h = hist.get(pid)
            with self.db.tx():
                if h:
                    self.db.x("UPDATE proposals SET state='APPLIED', applied_version=?, updated_minute=? WHERE proposal_id=?",
                              (h["version"], now, pid))
                else:
                    self._set(pid, "AUTO_FAILED", now, notes="not in config history after uncertain auto-apply")

    def withdraw_carrying(self, wf: int, experiment_id: str, now: int, reason: str) -> list[str]:
        """Withdraw our open approval requests that carry an experiment change we no longer want."""
        out = []
        for pid, body in self.db.q("SELECT proposal_id, body FROM proposals WHERE wf=? AND route='approval' AND state"
                                   " IN ('PENDING','APPROVED')", (wf,)):
            exps = (json.loads(body).get("evidence") or {}).get("experiments") or {}
            if experiment_id in exps.values():
                self._set(pid, "WITHDRAWN", now, notes=reason)
                out.append(pid)
        return out

    def _set(self, pid, state, now, approval=None, notes=None):
        self.db.x("UPDATE proposals SET state=?, updated_minute=?, approval=COALESCE(?, approval), notes=COALESCE(?, notes)"
                  " WHERE proposal_id=?", (state, now, dumps(approval) if approval else None, notes, pid))
