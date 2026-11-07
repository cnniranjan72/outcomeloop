"""The control loop: ingest → handle events → governance → decide → advance.

Planning model: every decision tick we compute the *desired* config for a workflow from our own state
(cohort set, schedule, caller-ID health, experiment plans, incident fixes) layered on top of the *current live*
config. The proposal is simply current → desired. Re-basing after a supervisor edit or a stale/expired
proposal is therefore automatic: the next plan starts from the new live config, and dimensions a supervisor
touched recently are locked so we never overwrite them silently.
"""
from __future__ import annotations

import copy
import json
import logging
import math
import os
import time
from pathlib import Path

from .cohorts import Cohort, bootstrap_cohorts, load_cohorts, membership_sql, save_cohorts, schedule_weights
from .config import Settings
from .db import DB, dumps
from .detectors import did_health, did_own_past, halluc_baseline, halluc_spike, kpi_drift
from .experiments import EXP_DIMS, Experiment, ExperimentEngine
from .instancelock import InstanceLock
from .persontime import PersonTime
from .governance import Governance
from .ingest import Ingestor
from .simclient import ApiError, SimClient, Uncertain
from .stats import tv_distance
from .timeutil import minute_to_label

log = logging.getLogger("outcomeloop")

AGENT_DIMS = ("welcome_message", "voice", "caller_id")
CHANGE_DIMS = ("cohorts", "welcome_message", "voice", "caller_id", "prompt_version", "schedule")


# ------------------------------------------------------------------------------------------ config algebra
def _dist(cfg: dict, cohort: str, dim: str) -> dict:
    return (cfg["allocations"].get(cohort) or {}).get(dim) or cfg["allocations"]["default"][dim]


def _norm(d: dict) -> dict:
    z = sum(d.values()) or 1.0
    return {k: v / z for k, v in d.items() if v > 0}


def changed_dims(old: dict, new: dict) -> list[str]:
    """Same semantics as the governance boundary uses (docs/SIMULATOR.md §4.2)."""
    ch = set()
    if old.get("cohorts", []) != new.get("cohorts", []):
        ch.add("cohorts")
    keys = set(old["allocations"]) | set(new["allocations"])
    for dim in AGENT_DIMS:
        if any(tv_distance(_dist(old, k, dim), _dist(new, k, dim)) > 1e-9 for k in keys):
            ch.add(dim)
    if old.get("prompt_version") != new.get("prompt_version"):
        ch.add("prompt_version")
    if old.get("schedule") != new.get("schedule"):
        ch.add("schedule")
    return [d for d in CHANGE_DIMS if d in ch]


def _fixpoint(d: dict) -> dict:
    """A distribution the governance boundary's normalisation (w / sum(w)) maps to itself bit-for-bit.
    The boundary compares stored distributions with exact equality after re-normalising what we send, so a
    stored dist that is not a fixed point is reported as 'changed' by every later proposal that merely copies
    it (spurious dims -> e.g. 403 auto_apply_not_permitted)."""
    x = {k: float(v) for k, v in d.items() if v > 0}
    for _ in range(8):
        s = float(sum(x.values()))
        y = {k: v / s for k, v in x.items()}
        if y == x:
            return x
        x = y
    big = max(sorted(x), key=x.get)          # rare 2-cycle: force the sum to 1.0 through the largest weight
    x[big] = 1.0 - sum(v for k, v in x.items() if k != big)
    return x


def canonical_config(old: dict, new: dict) -> dict:
    """Copy of `new` whose allocation dists that differ from `old` are fixed points of the boundary's
    normalisation. A dist whose effective distribution did not change is sent byte-identical to the live one."""
    out = copy.deepcopy(new)
    for scope, dims in out["allocations"].items():
        for dim, dist in list((dims or {}).items()):
            try:
                o = _dist(old, scope, dim)
            except KeyError:
                o = None
            if o is not None and tv_distance(o, dist) <= 1e-9:
                dims[dim] = dict(o)
            else:
                dims[dim] = _fixpoint(dist)
    return out


def max_shift(old: dict, new: dict) -> float:
    keys = {"default"} | {c["id"] for c in old.get("cohorts", [])} | {c["id"] for c in new.get("cohorts", [])}
    return max((tv_distance(_dist(old, k, d), _dist(new, k, d)) for k in keys for d in AGENT_DIMS), default=0.0)


class Controller:
    def __init__(self, s: Settings):
        self.s = s
        self.sim = SimClient(s.sim_url, s.http_timeout_s, s.http_retries)
        self.lock = InstanceLock(s.db_path).acquire()   # one controller per state file, before touching it
        self._prepare_db()
        self.db = DB(s.db_path)
        self.ing = Ingestor(self.db, self.sim)
        self.gov = Governance(self.db, self.sim, s)
        self.exp = ExperimentEngine(self.db, s)
        self.ptime = PersonTime(self.db, s)
        self.specs: dict[int, dict] = {}
        self.wf_by_id: dict[str, int] = {}
        self.now = 0
        self.decisions_this_hour = 0
        self.stopping = False
        self.urgent: set[int] = set()   # workflows to decide on at the next tick regardless of cadence
        self.t_start = time.time()
        self.day_wall: dict[int, float] = {}
        self.day_acc: dict[int, dict] = {}
        self._own_past: dict[int, tuple] = {}

    # ------------------------------------------------------------------ world identity
    def _prepare_db(self):
        """If the simulator is a different world from the one our DB remembers, archive the DB and start fresh.
        If the controller restarts against the same world, keep everything (that's crash recovery)."""
        st = self._wait_for_sim()
        p = Path(self.s.db_path)
        if not p.exists():
            return
        try:   # a damaged store is archived (never deleted) and rebuilt from the simulator: events are re-listable,
            #    configs and approvals are read live, so governance stays safe; experiment memory is what is lost
            import sqlite3
            c = sqlite3.connect(str(p))
            try:
                ok = c.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            finally:
                c.close()   # must close even on failure: an open handle blocks the archive rename on Windows
        except sqlite3.DatabaseError:
            ok = False
        if not ok:
            arch = p.with_suffix(f".{int(time.time())}.corrupt")
            log.error("state file %s failed integrity check; archived to %s and rebuilding from the simulator", p, arch)
            for suf in ("", "-wal", "-shm"):
                q = Path(str(p) + suf)
                if q.exists():
                    q.rename(Path(str(arch) + suf))
            self._rebuilt_from_corrupt = str(arch)
            return
        db = DB(p)
        known = db.meta_get("scenario")
        last = db.q1("SELECT MAX(until_minute) FROM chunks")[0]
        first = db.meta_get("first_history_event")
        db.close()
        same = known == st["scenario"] and (last is None or last <= st["sim_minute"])
        if same and first:
            try:
                ch = self.sim.list_chunks("history", -1)
                same = bool(ch) and str(ch[0].get("last_event_id")) == first
            except Exception:
                pass
        if not same:
            arch = p.with_suffix(f".{int(time.time())}.old")
            log.warning("simulator world changed (%s -> %s); archiving %s to %s", known, st["scenario"], p, arch)
            for suf in ("", "-wal", "-shm"):
                q = Path(str(p) + suf)
                if q.exists():
                    q.rename(Path(str(arch) + suf))

    def _wait_for_sim(self) -> dict:
        for i in range(600):
            try:
                return self.sim.state()
            except Exception:
                if i % 10 == 0:
                    log.info("waiting for simulator at %s …", self.s.sim_url)
                time.sleep(1)
        raise SystemExit(f"simulator at {self.s.sim_url} not reachable")

    # ------------------------------------------------------------------ startup
    def startup(self):
        st = self.sim.state()
        db = self.db
        with db.tx():
            db.meta_set("scenario", st["scenario"])
        hist = self.sim.list_chunks("history", -1)
        if hist:
            with db.tx():
                db.meta_set("first_history_event", str(hist[0]["last_event_id"]))
        for w in self.sim.workflows():
            wf = db.code("wf", w["workflow_id"])
            with db.tx():
                db.x("INSERT INTO workflows VALUES (?,?,?,?) ON CONFLICT(wf) DO UPDATE SET spec=excluded.spec",
                     (wf, w["workflow_id"], w["tenant_id"], dumps(w)))
            self.specs[wf] = w
            self.wf_by_id[w["workflow_id"]] = wf
        restarted = db.q1("SELECT COUNT(*) FROM chunks")[0] > 0
        if getattr(self, "_rebuilt_from_corrupt", None):
            with db.tx():
                db.decide(self.now, None, "error", f"state file failed its integrity check; archived to "
                          f"{self._rebuilt_from_corrupt} and rebuilt from the simulator",
                          reasoning="events re-ingested and approvals reconciled from the simulator; learning state"
                                    " (experiments, caller-ID memory) restarts from scratch")
        t0 = time.time()
        n = self.ing.ingest_all()
        self.now = st["sim_minute"]
        with db.tx():
            db.decide(self.now, None, "controller_start" if not restarted else "controller_restart",
                      f"{'restarted' if restarted else 'started'} at {minute_to_label(self.now)}; ingested {n} events"
                      f" in {time.time() - t0:.1f}s", evidence={"scenario": st["scenario"],
                                                              "credits": st["credits_remaining"]})
        notes = self.gov.reconcile_all(self.specs, self.now, self._on_gov)
        if restarted:
            log.info("recovery: %s", notes or "nothing in flight")
        self.handle_inbox()
        for wf in self.specs:
            self._sync_config(wf)

    # ------------------------------------------------------------------ main loop
    def _install_signal_handlers(self):
        """SIGTERM/SIGINT: finish the current step, then stop. Every step is already transactional, so stopping
        between steps is clean; a SIGKILL (no handler) is covered by crash recovery instead."""
        import signal

        def handler(signum, _frame):
            log.warning("signal %s: stopping after the current step", signum)
            self.stopping = True
        for sig in (getattr(signal, "SIGTERM", None), signal.SIGINT):
            if sig is not None:
                try:
                    signal.signal(sig, handler)
                except ValueError:   # not in the main thread (e.g. tests): no handler, nothing to do
                    pass

    def run(self):
        self._install_signal_handlers()
        self.startup()
        while True:
            if self.stopping:
                with self.db.tx():
                    self.db.decide(self.now, None, "controller_stop", f"graceful stop at {minute_to_label(self.now)}",
                                   reasoning="SIGTERM/SIGINT received; stopped between steps, all state committed")
                log.info("stopped gracefully at %s", minute_to_label(self.now))
                return
            day = self.now // 1440
            self.day_wall.setdefault(day, time.time())
            try:
                self.governance_tick()
            except Exception as e:
                self.db.rollback()
                log.exception("governance tick failed")
                with self.db.tx():
                    self.db.decide(self.now, None, "error", f"governance tick failed: {type(e).__name__}: {e}")
            hourly = self.now % self.s.decision_every_minutes == 0
            due = sorted(self.specs) if hourly else sorted(self.urgent)
            self.urgent = set()
            td = time.time()
            if due:
                for wf in due:
                    try:
                        self.decide(wf)
                    except Exception as e:   # isolate: one workflow's failure must not stop the others
                        self.db.rollback()
                        log.exception("decide %s failed", self.specs[wf]["workflow_id"])
                        with self.db.tx():
                            self.db.decide(self.now, wf, "error", f"decision step failed: {type(e).__name__}: {e}",
                                           reasoning="isolated; the loop continues and retries next cycle")
            decide_s = time.time() - td
            ta = time.time()
            st = self._advance()
            if st is None:
                break
            advance_s = time.time() - ta
            t0 = time.time()
            n = self.ing.ingest_all()
            self.handle_inbox()
            self._metrics(n, time.time() - t0, st, decide_s, advance_s)
            if st["finished"]:
                break
        self.finish()

    def _advance(self) -> dict | None:
        try:
            st = self.sim.advance(self.s.tick_minutes)
        except ApiError as e:
            if e.code == "finished":
                return None
            raise
        except Uncertain:
            st = self.sim.state()   # time may or may not have moved: read it, never assume
        self.now = st["sim_minute"]
        return st

    def finish(self):
        st = self.sim.state()
        with self.db.tx():
            self.db.decide(self.now, None, "controller_finish", f"scenario finished at {minute_to_label(self.now)}",
                           evidence={"credits_remaining": st["credits_remaining"],
                                     "wall_seconds": round(time.time() - self.t_start, 1),
                                     "events_ingested": self.ing.events_total})
        log.info("finished: %s", st)

    # ------------------------------------------------------------------ events
    def handle_inbox(self):
        """Process side-effect events in event_id order. A failed event is retried next tick (not dropped: a lost
        supervisor edit would mean overwriting it); later events of the same workflow wait behind it, and decide()
        holds that workflow until its events are processed. Dead-lettered (audited) only after 10 attempts."""
        blocked: set[int] = set()
        for event_id, typ, wf, minute, payload in self.ing.inbox():
            if wf in blocked:
                continue
            ev = json.loads(payload)
            try:
                self._handle_one(event_id, typ, wf, minute, ev)
            except Exception as e:
                self.db.rollback()
                log.exception("event %s failed", event_id)
                with self.db.tx():
                    n = self.db.kv_get(f"inbox_attempts:{event_id}", 0) + 1
                    self.db.kv_set(f"inbox_attempts:{event_id}", n)
                    if n >= 10:
                        self.db.decide(minute, wf, "error", f"event {event_id} ({typ}) dead-lettered after {n}"
                                       f" attempts: {e}", reasoning="needs a human: the event could not be processed")
                        self.ing.mark_done(event_id)
                    else:
                        blocked.add(wf)

    def pending_events(self, wf: int) -> int:
        return self.db.q1("SELECT COUNT(*) FROM inbox WHERE done=0 AND wf=?", (wf,))[0]

    def _handle_one(self, event_id, typ, wf, minute, ev):
        with self.db.tx():
            if typ == "config_changed":
                self._on_config_changed(wf, ev, minute)
            elif typ == "approval_decided":
                self.db.decide(minute, wf, "approval_decided",
                               f"{ev['approval_id']} {ev['status']}", evidence=ev, actor="approver",
                               approval_id=ev["approval_id"], outcome=ev["status"])
            self.ing.mark_done(event_id)

    def _on_config_changed(self, wf: int, ev: dict, minute: int):
        actor, ver, dims = ev["actor"], ev["version"], ev.get("changed_dims") or []
        if actor == "supervisor" and minute >= 0:
            # a dimension a supervisor set stays approval-only (never auto-applied over) until one of our approved
            # changes to it is applied
            sup = set(self.db.kv_get(f"supervisor_dims:{wf}", []))
            self.db.kv_set(f"supervisor_dims:{wf}", sorted(sup | set(dims)))
        elif actor == "controller_approved" and minute >= 0:
            sup = set(self.db.kv_get(f"supervisor_dims:{wf}", []))
            if sup & set(dims):
                self.db.kv_set(f"supervisor_dims:{wf}", sorted(sup - set(dims)))
        cur = self.sim.config(self.specs[wf]["workflow_id"])
        if cur["version"] == ver:
            self.db.x("UPDATE config_versions SET config=? WHERE wf=? AND version=?", (dumps(cur["config"]), wf, ver))
        if minute >= 0:
            self.db.decide(minute, wf, "config_changed", f"v{ver} by {actor}: {', '.join(dims) or 'no dims'}",
                           actor=actor, evidence=ev, proposal_id=ev.get("proposal_id"),
                           approval_id=ev.get("approval_id"), config_version=ver)
        if actor == "supervisor" and minute >= 0:
            locks = self.db.kv_get(f"locks:{wf}", {})
            for d in dims:
                locks[d] = minute + int(self.s.supervisor_lock_hours * 60)
            self.db.kv_set(f"locks:{wf}", locks)
            self.db.decide(minute, wf, "supervisor_edit", f"supervisor changed {dims}; locked for "
                           f"{self.s.supervisor_lock_hours:.0f}h — we will not propose changes to these dims",
                           reasoning="supervisor edits are authoritative and bypass governance; we never overwrite"
                                     " them silently. Pending proposals on an older base will be re-planned.",
                           config_version=ver, actor="controller")
            if "prompt_version" in dims:
                self.urgent.add(wf)
                inc = self.db.kv_get(f"prompt_probe:{wf}", [])
                inc.append({"version": ver, "minute": minute, "prompt": cur["config"]["prompt_version"]})
                self.db.kv_set(f"prompt_probe:{wf}", inc)
        # experiments react to every version
        for e in Experiment.load_active(self.db, wf).values():
            tr = self.exp.on_config(e, cur["config"], ver, actor, dims, minute)
            if tr:
                e.save(self.db, minute)
            if tr and tr != "versions":
                self.db.decide(minute, wf, f"experiment_{tr}", f"{e.dim} experiment {tr} (v{ver})",
                               evidence={"plan": e.plan, "versions": e.versions, "result": e.result},
                               experiment_id=e.experiment_id, config_version=ver)
        # cohort set becomes live when the config carries it
        mine = load_cohorts(self.db, wf, ("proposed",))
        if mine and [c.to_config() for c in mine] == cur["config"].get("cohorts"):
            self.db.x("UPDATE cohorts SET status='live' WHERE wf=? AND status='proposed'", (wf,))
        # incidents waiting on a prompt fix
        for iid, data in self.db.q("SELECT incident_id, data FROM incidents WHERE wf=? AND state='proposed'", (wf,)):
            d = json.loads(data)
            if (ev.get("proposal_id") and ev.get("proposal_id") == d.get("proposal_id")) or                     ("prompt_version" in dims and cur["config"]["prompt_version"] == d.get("fix_prompt")):
                d["applied_minute"] = minute
                self.db.x("UPDATE incidents SET state='verifying', data=? WHERE incident_id=?", (dumps(d), iid))
                self.db.decide(minute, wf, "incident_fix_applied", f"{iid}: prompt {d['fix_prompt']} live (v{ver})",
                               incident_id=iid, config_version=ver)

    def _on_gov(self, kind: str, wf: int, pid: str, info: dict):
        msg = {"approved": "approved by client approver", "rejected": "rejected", "expired": "expired unanswered",
               "lapsed": "approval lapsed before apply", "stale": "base version changed — will re-plan on new base",
               "applied": "applied"}.get(kind, kind)
        self.db.decide(self.now, wf, f"proposal_{kind}", f"{pid}: {msg}", evidence=info, proposal_id=pid,
                       approval_id=info.get("approval_id"), config_version=info.get("version"),
                       reasoning={"expired": "an expired proposal is treated as a rejection: re-plan from fresh data,"
                                             " never resubmit the stale body",
                                  "stale": "never force a stale proposal over a newer (possibly supervisor) config",
                                  "rejected": f"reasons: {info.get('reasons')}"}.get(kind, ""))

    def governance_tick(self):
        self.gov.tick(self.now, self.specs, self._on_gov)

    def _sync_config(self, wf: int) -> dict:
        cur = self.sim.config(self.specs[wf]["workflow_id"])
        with self.db.tx():
            self.db.x("INSERT INTO config_versions (wf, version, actor, config) VALUES (?,?,?,?) ON CONFLICT(wf, version)"
                      " DO UPDATE SET config=excluded.config", (wf, cur["version"], cur["actor"], dumps(cur["config"])))
        return cur

    # ------------------------------------------------------------------ decisions
    def decide(self, wf: int):
        spec = self.specs[wf]
        now = self.now
        db = self.db
        if self.pending_events(wf):
            self._hold(wf, "unprocessed events for this workflow (retrying); no decisions on a stale view")
            return
        if not db.kv_get(f"boot:{wf}"):
            self.bootstrap(wf)
        cur = self.sim.config(spec["workflow_id"])
        cfg = cur["config"]
        locks = {d: t for d, t in db.kv_get(f"locks:{wf}", {}).items() if t > now}
        ctx = {"locks": locks, "notes": [], "evidence": {}, "emergency": False, "kinds": []}

        dids = self.detect_did(wf, spec, now, ctx)
        self.detect_halluc(wf, spec, cfg, now, ctx)
        if now % 1440 == 12 * 60:
            drift = kpi_drift(db, wf, now, self.s)
            if drift["alerts"]:
                with db.tx():
                    db.decide(now, wf, "alert", f"KPI drift: {drift['alerts']}", evidence=drift)
            self.check_cohort_agreement(wf, cfg, now)
        self.step_experiments(wf, spec, cfg, now, ctx)
        self.step_persontime(wf, spec, now, ctx)
        self.verify_applied(wf, spec, now)

        desired = self.desired_config(wf, spec, cfg, dids, ctx)
        self.route(wf, spec, cur, desired, ctx)

    def check_cohort_agreement(self, wf, cfg, now) -> dict | None:
        """Daily consistency check of the shared-cohort guarantee: for calls in the last 24 h dialled under a config
        carrying exactly our cohort set, our membership rule must assign the same cohort the simulator stamped on the
        call. A mismatch means our cohort definition and the live one have diverged — an alert, not a guess."""
        db = self.db
        cohorts = load_cohorts(db, wf, ("live",))
        if not cohorts or cfg.get("cohorts") != [c.to_config() for c in cohorts]:
            return None
        live_vs = [v for v, c in db.q("SELECT version, config FROM config_versions WHERE wf=? AND config IS NOT NULL",
                                      (wf,)) if json.loads(c).get("cohorts") == cfg["cohorts"]]
        if not live_vs:
            return None
        rows = db.q(f"SELECT {membership_sql(db, cohorts)}, cohort, COUNT(*) FROM calls WHERE wf=? AND minute>=?"
                    f" AND minute<? AND cfg_ver IN ({','.join('?' * len(live_vs))}) GROUP BY 1, 2",
                    (wf, now - 1440, now, *live_vs))
        total = sum(n for _, _, n in rows)
        bad = sum(n for ours, theirs, n in rows if ours != db.decode("cohort", theirs))
        out = {"calls": total, "mismatched": bad}
        with db.tx():   # recorded either way, so the guarantee is checkable from the store, not recomputed
            db.decide(now, wf, "cohort_check", f"cohort agreement: {bad} of {total} calls assigned differently",
                      evidence=out)
        if total and bad:
            with db.tx():
                db.decide(now, wf, "alert", f"cohort definitions diverged: {bad}/{total} calls assigned differently"
                          f" by us and by the simulator", evidence=out)
        return out

    # ---- post-apply verification: "what happened afterwards", for every applied change
    def verify_applied(self, wf, spec, now):
        """24 h after any applied change (approval or auto route), compare the workflow's pickup and engagement in
        the 24 h before vs after and evaluate the guardrail KPI against the policy margin. Recorded as a
        `post_apply_verification` decision linked to the proposal and version; a significant guardrail breach is
        an alert. Before/after is confounded by time (campaign mix, other changes), so it is a check, not an
        estimate of the change's effect — randomised comparisons (experiments, holdouts) carry that."""
        from .stats import Prop, compare
        db = self.db
        rows = db.q("SELECT p.proposal_id, p.applied_version, v.minute, v.changed_dims FROM proposals p JOIN"
                    " config_versions v ON v.wf=p.wf AND v.version=p.applied_version WHERE p.wf=? AND p.state='APPLIED'"
                    " AND v.minute IS NOT NULL AND v.minute <= ? AND v.minute > ?", (wf, now - 1440, now - 3 * 1440))
        if not rows:
            return
        obj = spec["objective"]
        primary = obj.get("primary", "engagement_rate")
        g = obj.get("guardrail") or {}
        gname, margin = (next(iter(g.items())) if g else ("pickup_rate_max_drop", 0.02))
        gkpi = gname.replace("_max_drop", "")
        for pid, ver, applied, dims in rows:
            if db.q1("SELECT 1 FROM decisions WHERE kind='post_apply_verification' AND proposal_id=?", (pid,)):
                continue
            q = lambda a, b: db.q1("SELECT COUNT(*), SUM(conn), SUM(eng) FROM calls WHERE wf=? AND minute>=? AND"
                                   " minute<?", (wf, a, b))
            bn, bc, be = q(applied - 1440, applied)
            an, ac, ae = q(applied, applied + 1440)
            bc, be, ac, ae = bc or 0, be or 0, ac or 0, ae or 0
            out = {"window_before": [applied - 1440, applied], "window_after": [applied, applied + 1440],
                   "changed_dims": json.loads(dims or "[]"), "primary": primary, "guardrail": gkpi, "margin": margin}
            if bn and an and bc and ac:
                pk = compare(Prop(bc, bn), Prop(ac, an))
                en = compare(Prop(be, bc), Prop(ae, ac))
                out.update({"pickup": {"before": round(bc / bn, 4), "after": round(ac / an, 4), "z": round(pk.z, 2)},
                            "engagement": {"before": round(be / bc, 4), "after": round(ae / ac, 4), "z": round(en.z, 2)}})
                gc = pk if gkpi == "pickup_rate" else en
                breach = -gc.diff > margin and gc.z < -2.33
                out["guardrail_breach"] = breach
            else:
                breach = False
                out["note"] = "not enough calls on one side of the change"
            with db.tx():
                db.decide(now, wf, "post_apply_verification", f"{pid} (v{ver}): "
                          + (f"pickup {out['pickup']['before']:.3f}→{out['pickup']['after']:.3f}, engagement "
                             f"{out['engagement']['before']:.3f}→{out['engagement']['after']:.3f}"
                             + (f"; GUARDRAIL BREACH on {gkpi}" if breach else "; guardrail ok")
                             if "pickup" in out else out["note"]),
                          evidence=out, proposal_id=pid, config_version=ver,
                          reasoning="before/after on the whole workflow (24 h each side); confounded by time, so a"
                                    " check rather than an effect estimate")
                if breach:
                    db.decide(now, wf, "alert", f"guardrail {gkpi} fell beyond the policy margin after {pid}",
                              evidence=out, proposal_id=pid)

    # ---- per-person call time (C4), as a randomised experiment
    def step_persontime(self, wf, spec, now, ctx):
        """Daily at the start of the dialling window: look (expand / stop / continue), then refresh the treated
        people's preferred hours. Only where `schedule` is auto-appliable by policy (see persontime.py)."""
        if not self.s.person_time or now < 0 or (now % 1440) // 60 != spec["dialling_window"][0]                 or "schedule" in ctx["locks"]:
            return
        if not self.ptime.eligible(spec, set(self.db.kv_get(f"supervisor_dims:{wf}", []))):
            return
        st = self.ptime.state(wf)
        if st["status"] in ("testing", "expanded"):
            res = self.ptime.look(wf, now)
            with self.db.tx():
                self.db.decide(now, wf, "person_time_look", f"per-person call time: {res['action']}"
                               + (f" (pickup {res['pickup_t']:.3f} treated vs {res['pickup_c']:.3f} control, z {res['z']})"
                                  if "z" in res else ""), evidence=res,
                               reasoning="randomised by person; pickup per dial after each person became a candidate;"
                                         " one-sided z at 1 % per daily look, >= 400 dials per arm; no evidence by"
                                         " day 5 -> stop")
        pmap = self.ptime.refresh(wf, spec, now)
        with self.db.tx():
            self.db.kv_set(f"ptime_map:{wf}", {"day": now // 1440, "map": pmap,
                                                "status": self.ptime.state(wf)["status"]})
            self.db.decide(now, wf, "person_time_refresh", f"per-person call time ({self.ptime.state(wf)['status']}):"
                           f" {len(pmap)} treated people with a preferred hour", evidence={"treated": len(pmap)})

    # ---- bootstrap from history (C3)
    def bootstrap(self, wf: int):
        spec = self.specs[wf]
        db = self.db
        lo = db.q1("SELECT MIN(minute) FROM calls WHERE wf=?", (wf,))[0] or 0
        until = min(self.now, 0) if lo < 0 else self.now
        cohorts, ev = bootstrap_cohorts(db, wf, self.s, lo, max(until, lo + 1))
        weights, dry = schedule_weights(db, wf, cohorts, spec["dialling_window"], self.s, lo, max(until, lo + 1)) \
            if cohorts else ({}, {})
        base = halluc_baseline(db, wf, max(until, lo + 1))
        tot_c = sum(v["connected"] for v in base.values())
        ref = (sum(v["flags"] for v in base.values()) / tot_c) if tot_c else 0.015
        with db.tx():
            save_cohorts(db, wf, cohorts, self.now, rationale=json.dumps(ev, default=str))
            db.kv_set(f"schedule:{wf}", {"hour_weights": weights, "dry_run": dry})
            db.kv_set(f"halluc_ref:{wf}", {"rate": ref, "by_prompt": base})
            db.kv_set(f"boot:{wf}", {"minute": self.now, "history": [lo, until]})
            db.decide(self.now, wf, "bootstrap", f"bootstrapped from history {minute_to_label(lo)}..{minute_to_label(until)}:"
                      f" cohorts by {ev.get('chosen')} {[c.cohort_id for c in cohorts]}, schedule dry-run pickup lift"
                      f" {dry.get('rel_lift', 0):+.1%}, QA flag reference rate {ref:.4f}",
                      reasoning="cohort feature = the one whose values have the most different hour-of-day pickup"
                                " profiles (likelihood-ratio test p<0.001, largest G²/df); groups below 10% of dials are"
                                " merged so no cohort is too small to measure",
                      evidence={"cohorts": ev, "schedule_dry_run": dry, "halluc_baseline": base})

    # ---- caller ID (C5)
    def detect_did(self, wf, spec, now, ctx) -> dict:
        opts = spec["options"]["caller_id"]
        mem = self.db.kv_get(f"did:{wf}", {})
        probing = {d for d in opts if mem.get(d, {}).get("state", "unknown") in ("unknown", "probe")}
        since = {d: mem[d]["since"] for d in opts if mem.get(d, {}).get("state") == "probe"}
        # a week-long baseline barely moves in an hour: recompute it every 6 sim hours (saves a large scan at scale)
        key = (wf, now // 360)
        if self._own_past.get(wf, (None,))[0] != key:
            self._own_past[wf] = (key, did_own_past(self.db, wf, now, self.s))
        health = did_health(self.db, wf, opts, now, self.s, probing, since, self._own_past[wf][1])
        changed = []
        for d, h in health.items():
            prev = mem.get(d, {}).get("state", "unknown")
            if h["state"] == "degraded" and prev != "degraded":
                mem[d] = {"state": "degraded", "since": now, "rest": mem.get(d, {}).get("rest", 1440)}
                changed.append((d, prev, "degraded", h))
            elif prev == "degraded":
                # a resting number (0 share) produces no data; after the rest period re-probe it, because number
                # reputation recovers when volume drops. Rest doubles each time it degrades again.
                rest = mem[d].get("rest", 1440)
                if now - mem[d]["since"] >= rest:
                    mem[d] = {"state": "probe", "since": now, "rest": rest * 2}
                    changed.append((d, "degraded", "probe", h))
            elif prev == "probe" and h["state"] != "healthy" and now - mem[d]["since"] >= self.s.did_probe_hours * 60:
                mem[d] = {"state": "degraded", "since": now, "rest": mem[d].get("rest", 1440)}
                changed.append((d, "probe", "degraded", h))
            elif h["state"] == "healthy" and prev != "healthy":
                mem[d] = {"state": "healthy", "since": now, "rest": mem.get(d, {}).get("rest", 1440)}
                changed.append((d, prev, "healthy", h))
        with self.db.tx():
            self.db.kv_set(f"did:{wf}", mem)
            for d, a, b, h in changed:
                self.db.decide(now, wf, "did_health", f"caller ID {d}: {a} -> {b}", evidence=h,
                               reasoning="caller ID is randomised per dial, so its pickup vs the other numbers in the"
                                         " same window isolates the number's reputation; degraded = ratio<0.85 and"
                                         " z<-3.5 on >=300 dials")
        if any(b == "degraded" for _, _, b, _ in changed):
            ctx["emergency"] = True
            ctx["kinds"].append("did_incident")
        ctx["evidence"]["caller_id"] = {d: {"state": mem.get(d, {}).get("state", "unknown"),
                                            "slow": health[d]["windows"].get("slow")} for d in opts}
        return mem

    def did_target(self, opts: list[str], mem: dict, cur: dict) -> dict:
        """Equal split over healthy numbers; 0 for degraded; untested numbers get a small probe.
        * Insufficient evidence never moves traffic between healthy and unknown numbers: an unknown number keeps
          the share it already has (next_campaign_only workflows see a new allocation a campaign later).
        * A measured-degraded number always gives up its share, even if the remaining numbers are only unknown:
          an untested number is a better bet than one we have measured as flagged.
        * Probing is budgeted: at most 10 % of traffic in total on untested numbers."""
        state = {d: mem.get(d, {}).get("state", "unknown") for d in opts}
        degraded = {d for d in opts if state[d] == "degraded"}
        healthy = [d for d in opts if state[d] == "healthy"]
        unknown = [d for d in opts if d not in degraded and d not in healthy]
        new_probes = [d for d in unknown if state[d] == "unknown" and cur.get(d, 0) <= self.s.did_probe_share]
        probe_each = min(self.s.did_probe_share, 0.10 / len(new_probes)) if new_probes else 0.0
        tgt: dict[str, float] = {}
        for d in unknown:
            if state[d] == "probe":
                tgt[d] = self.s.did_reprobe_share           # a previously degraded number risks little traffic
            elif d in new_probes:
                tgt[d] = probe_each
            else:
                tgt[d] = cur.get(d, 0.0)                     # unknown with real traffic: keep what it has
        if not healthy:
            if not any(cur.get(d, 0) > 0 for d in degraded) and not any(w > self.s.did_probe_share for w in tgt.values()):
                return cur                                    # nothing measured, nothing degraded: no change
            # freed traffic goes to numbers already carrying real traffic; only if none does, to the untested ones
            carriers = [d for d in unknown if state[d] != "probe" and cur.get(d, 0) > self.s.did_probe_share]                 or [d for d in unknown if state[d] != "probe"] or unknown
            if not carriers:
                return cur                                    # every number is degraded: nothing better to move to
            freed = 1 - sum(tgt.values())
            for d in carriers:                               # degraded share goes to the non-degraded numbers
                tgt[d] += freed / len(carriers)
            return {d: round(w, 4) for d, w in tgt.items() if w > 0}
        rest = max(1 - sum(tgt.values()), 0.0)
        for d in healthy:
            tgt[d] = rest / len(healthy)
        return {d: round(w, 4) for d, w in tgt.items() if w > 0}

    # ---- hallucination (C8)
    def detect_halluc(self, wf, spec, cfg, now, ctx):
        db = self.db
        ref = db.kv_get(f"halluc_ref:{wf}", {"rate": 0.015})["rate"]
        prompt = cfg["prompt_version"]
        open_inc = db.q1("SELECT incident_id, state, data FROM incidents WHERE wf=? AND state NOT IN ('closed')"
                         " ORDER BY opened_minute DESC", (wf,))
        if open_inc:
            d0 = json.loads(open_inc[2])
            if prompt not in (d0.get("bad_prompt"), d0.get("fix_prompt")):
                # someone (a supervisor) shipped a different prompt: this incident no longer describes what is live.
                # Close it so the new prompt is probed and judged on its own evidence.
                with db.tx():
                    db.x("UPDATE incidents SET state='closed', closed_minute=? WHERE incident_id=?", (now, open_inc[0]))
                    db.decide(now, wf, "incident_superseded", f"{open_inc[0]}: live prompt is now {prompt} (not"
                              f" {d0.get('bad_prompt')} or our fix {d0.get('fix_prompt')}) — closed as superseded",
                              incident_id=open_inc[0])
                open_inc = None
        # probe a supervisor's new prompt with a validation run (3 credits): earliest population evidence
        probes = db.kv_get(f"prompt_probe:{wf}", [])
        if probes:
            p = probes[-1]
            thr = spec["governance"].get("min_validation_pass_rate", 0.97)
            run = None
            if p["prompt"] == prompt and self.sim.state()["credits_remaining"] >= 10:
                def on_probe(r, inc_open=bool(open_inc), prior=p.get("prior")):
                    # inside _validate's ledger transaction: the paid result, the probe's state and the incident
                    # commit together. Clearing the probe BEFORE the call lost it on a crash mid-call (the
                    # supervisor's unsafe prompt then waited for the slower QA-flag detector).
                    fails, n = r["failures"], r["n"]
                    if prior:   # second run: decide on the pooled sample
                        fails, n = fails + prior["failures"], n + prior["n"]
                    pooled = 1 - fails / n
                    se = (pooled * (1 - pooled) / n) ** 0.5
                    if not prior and thr <= pooled < thr + se and self.sim.state()["credits_remaining"] >= 30:
                        # within one standard error of the threshold: a coin flip, not a pass. Buy a second run
                        # next tick and decide on the pooled evidence.
                        db.kv_set(f"prompt_probe:{wf}", [{**p, "prior": r}])
                        self.urgent.add(wf)
                        return
                    db.kv_set(f"prompt_probe:{wf}", [])
                    if pooled < thr and not inc_open:
                        self._open_incident(wf, prompt, now, {"trigger": "validation_probe", "validation": r,
                                                              "prior_validation": prior, "pooled_pass_rate":
                                                              round(pooled, 4), "pooled_n": n, "threshold": thr})
                run = self._validate(wf, spec, prompt, purpose=f"probe supervisor prompt change v{p['version']}"
                                     + (" (second run, pooled)" if p.get("prior") else ""), persist=on_probe)
            if run is None:   # prompt moved on, no credits, or the call failed: drop the probe as before
                with db.tx():
                    db.kv_set(f"prompt_probe:{wf}", [])
            else:
                open_inc = db.q1("SELECT incident_id, state, data FROM incidents WHERE wf=? AND state!='closed'"
                                 " ORDER BY opened_minute DESC", (wf,))
        since = db.q1("SELECT MAX(minute) FROM config_versions WHERE wf=? AND changed_dims LIKE '%prompt_version%'",
                      (wf,))[0] or (now - 1440)
        sp = halluc_spike(db, wf, prompt, max(since, now - 1440), now, ref, self.s)
        ctx["evidence"]["halluc"] = sp
        quiet = db.kv_get(f"halluc_quiet:{wf}", {})
        if sp["fired"] and not open_inc and quiet.get(prompt, -1) < now:
            self._open_incident(wf, prompt, now, {"trigger": "flag_rate", "detector": sp})
            open_inc = db.q1("SELECT incident_id, state, data FROM incidents WHERE wf=? AND state!='closed'"
                             " ORDER BY opened_minute DESC", (wf,))
        if not open_inc:
            return
        iid, state, data = open_inc
        d = json.loads(data)
        if state == "open":
            det = d.get("detector") or {}
            strong = det.get("connected", 0) >= 400 and det.get("ref_rate", 0) > 0 and                 det.get("flag_rate", 0) >= 2.0 * det["ref_rate"] and det.get("z", 0) >= 5.0
            if d.get("trigger") == "flag_rate" and strong and "confirmation" not in d:
                d["confirmation"] = {"basis": "production QA flag rate >= 2x baseline with z >= 5 on >= 400 calls"}
                with db.tx():
                    db.x("UPDATE incidents SET data=? WHERE incident_id=?", (dumps(d), iid))
            if d.get("trigger") == "flag_rate" and "confirmation" not in d:
                # second, independent evidence source before touching a customer-facing script: QA flags are a
                # noisy detector, a validation run measures the prompt itself (3 credits)
                thr = spec["governance"].get("min_validation_pass_rate", 0.97)

                def keep_conf(r):   # inside the ledger transaction: a paid confirmation is never re-bought
                    d["confirmation"] = r
                    db.x("UPDATE incidents SET data=? WHERE incident_id=?", (dumps(d), iid))
                run = self._validate(wf, spec, d["bad_prompt"], purpose=f"confirm {iid}", persist=keep_conf)
                if run is None:
                    return   # no second signal yet (credits, transport): retry next tick, never act on flags alone
                se = (run["pass_rate"] * (1 - run["pass_rate"]) / run["n"]) ** 0.5 if run else 0
                # the production detector has already fired: only a clearly safe validation (>= threshold + 1 SE)
                # vetoes it; a result inside the noise band of the threshold gives the benefit of the doubt to safety
                if run and run["pass_rate"] >= thr + se:
                    with db.tx():
                        db.x("UPDATE incidents SET state='closed', closed_minute=?, data=? WHERE incident_id=?",
                             (now, dumps(d), iid))
                        quiet[d["bad_prompt"]] = now + 1440
                        db.kv_set(f"halluc_quiet:{wf}", quiet)
                        db.decide(now, wf, "incident_not_confirmed",
                                  f"{iid}: QA flag spike not confirmed — {d['bad_prompt']} passes validation"
                                  f" {run['pass_rate']:.3f} >= {thr}; no prompt change, watching for 24h",
                                  evidence=d, incident_id=iid,
                                  reasoning="the flag detector has false positives; acting needs both signals")
                    return
                with db.tx():
                    db.x("UPDATE incidents SET data=? WHERE incident_id=?", (dumps(d), iid))
            self._find_fix(wf, spec, iid, d, prompt, now)
            r = db.q1("SELECT state, data FROM incidents WHERE incident_id=?", (iid,))
            if r[0] == "fix_ready":
                ctx["prompt_fix"] = (iid, json.loads(r[1]))
                ctx["emergency"] = True
                ctx["kinds"].append("halluc_incident")
        elif state == "verifying" and now - d.get("applied_minute", now) >= 240:
            v = halluc_spike(db, wf, prompt, d["applied_minute"], now, ref, self.s)
            eng = self._engagement_check(wf, d, prompt, now)
            if eng.get("harmed"):
                with db.tx():
                    d.setdefault("tried", {}).setdefault(prompt, {})["engagement_harm"] = eng
                    d["verification_failed"] = eng
                    db.x("UPDATE incidents SET state='open', data=? WHERE incident_id=?", (dumps(d), iid))
                    db.decide(now, wf, "incident_fix_harmful", f"{iid}: fix {prompt} is safe but engagement fell"
                              f" {eng['rel']:+.1%} (z {eng['z']}) — trying the next candidate", evidence=eng,
                              incident_id=iid, reasoning="validation measures safety only; a fix nobody stays on the"
                                                         " call for is not a fix")
                return
            ok = not v["fired"] and v["connected"] >= 100 and eng.get("checked", False)
            if ok or now - d["applied_minute"] > 1440:
                with db.tx():
                    d["verification"] = v
                    db.x("UPDATE incidents SET state=?, closed_minute=?, data=? WHERE incident_id=?",
                         ("closed", now, dumps(d), iid))
                    db.decide(now, wf, "incident_verified" if ok else "incident_closed_unverified",
                              f"{iid}: after fix flag rate {v['flag_rate']:.4f} vs ref {v['ref_rate']:.4f}"
                              f" on {v['connected']} connected calls", evidence=v, incident_id=iid)
        elif state == "fix_ready":
            if cfg["prompt_version"] == d.get("fix_prompt"):
                with db.tx():
                    d["applied_minute"] = now
                    db.x("UPDATE incidents SET state='verifying', data=? WHERE incident_id=?", (dumps(d), iid))
            else:
                ctx["prompt_fix"] = (iid, d)
                ctx["emergency"] = True
                ctx["kinds"].append("halluc_incident")
        elif state == "proposed":
            pid = d.get("proposal_id")
            st = db.q1("SELECT state FROM proposals WHERE proposal_id=?", (pid,))
            if st and st[0] == "APPLIED":
                applied = db.q1("SELECT updated_minute FROM proposals WHERE proposal_id=?", (pid,))[0]
                with db.tx():
                    d["applied_minute"] = applied
                    db.x("UPDATE incidents SET state='verifying', data=? WHERE incident_id=?", (dumps(d), iid))
                    db.decide(now, wf, "incident_fix_applied", f"{iid}: fix proposal {pid} applied", incident_id=iid,
                              proposal_id=pid)
            elif st and st[0] in ("REJECTED", "EXPIRED", "LAPSED", "STALE", "SUBMIT_FAILED", "WITHDRAWN"):
                with db.tx():
                    db.x("UPDATE incidents SET state='fix_ready' WHERE incident_id=?", (iid,))
                    db.decide(now, wf, "incident_repropose", f"{iid}: fix proposal {pid} {st[0]} — re-proposing",
                              incident_id=iid, proposal_id=pid)

    def _engagement_check(self, wf, d, prompt, now) -> dict:
        """Engagement on the fix prompt since it went live vs the 7 days before the incident opened."""
        from .stats import Prop, compare
        db = self.db
        pc = db.code("prompt_version", prompt)
        a = db.q1("SELECT SUM(conn), SUM(eng) FROM calls WHERE wf=? AND minute>=? AND minute<? AND conn=1 AND prompt!=?",
                  (wf, d.get("opened", now) - 7 * 1440, d.get("opened", now), db.code("prompt_version", d["bad_prompt"])))
        b = db.q1("SELECT SUM(conn), SUM(eng) FROM calls WHERE wf=? AND minute>=? AND minute<? AND conn=1 AND prompt=?",
                  (wf, d["applied_minute"], now, pc))
        if not a[0] or not b[0] or b[0] < 300:
            return {"checked": False, "connected_after": b[0] or 0}
        c = compare(Prop(a[1], a[0]), Prop(b[1], b[0]))
        return {"checked": True, "before": round(a[1] / a[0], 4), "after": round(b[1] / b[0], 4), "rel": round(c.rel, 4),
                "z": round(c.z, 2), "harmed": c.rel < -0.05 and c.z < -2.0}

    def _open_incident(self, wf, prompt, now, evidence):
        iid = f"inc-{self.specs[wf]['workflow_id']}-{now}"
        with self.db.tx():
            self.db.x("INSERT OR IGNORE INTO incidents VALUES (?,?,?,?,?,?,?)",
                      (iid, wf, "hallucination", "open", now, None, dumps({"bad_prompt": prompt, "opened": now,
                                                                          **evidence})))
            self.db.decide(now, wf, "incident_opened", f"hallucination incident on prompt {prompt}",
                           evidence=evidence, incident_id=iid,
                           reasoning="population evidence (validation run of n synthetic calls, or QA flag rate on"
                                     " >=250 connected calls) shows the live prompt is unsafe")

    def _credits_ok(self, cost: float, incident: bool) -> bool:
        st = self.sim.state()
        budget0 = self.db.kv_get("credits_start") or st["credits_remaining"]
        if not self.db.kv_get("credits_start"):
            with self.db.tx():
                self.db.kv_set("credits_start", budget0)
        floor = 0 if incident else budget0 * self.s.credit_incident_reserve
        return st["credits_remaining"] - cost >= floor

    def _validation_n(self) -> int:
        """300 synthetic calls when credits are plentiful, fewer when scarce: a 100-call run (1 credit) still
        separates a 1% from a 5% failure rate; running out mid-incident is the worse failure."""
        left = self.sim.state()["credits_remaining"]
        return self.s.validation_n if left >= 60 else (200 if left >= 20 else 100)

    def _validate(self, wf, spec, prompt, purpose, persist=None) -> dict | None:
        """persist(run), if given, runs inside the transaction that records the paid result, so a crash can never
        leave a paid-for validation committed in the ledger but unknown to the state that uses it."""
        n = self._validation_n()
        cost = math.ceil(n / 100)
        if not self._credits_ok(cost, incident=True):
            return None
        with self.db.tx():
            cur = self.db.x("INSERT INTO credits_ledger (minute, wf, kind, purpose, state, cost, request) VALUES"
                            " (?,?,?,?,?,?,?)", (self.now, wf, "validation", purpose, "sent", cost,
                                                 dumps({"prompt_version": prompt, "n": n})))
            lid = cur.lastrowid
        try:
            run = self.sim.validate(spec["workflow_id"], prompt, n)
        except (ApiError, Uncertain) as e:
            with self.db.tx():
                self.db.x("UPDATE credits_ledger SET state=?, response=? WHERE id=?", ("failed", str(e), lid))
            return None
        with self.db.tx():
            self.db.x("UPDATE credits_ledger SET state='done', response=? WHERE id=?", (dumps(run), lid))
            self.db.decide(self.now, wf, "validation_run", f"validated {prompt}: pass_rate {run['pass_rate']:.3f}"
                           f" (n={n}, {cost} credits) — {purpose}", evidence=run)
            if persist is not None:
                persist(run)
        return run

    def _find_fix(self, wf, spec, iid, d, bad_prompt, now):
        """Known-good prompts from our own history first; the LLM only if none validates. The LLM proposes;
        validation and our deterministic rule decide."""
        db = self.db
        thr = spec["governance"].get("min_validation_pass_rate", 0.97)
        ref = db.kv_get(f"halluc_ref:{wf}", {"rate": 0.015})["rate"]
        obs = halluc_baseline(db, wf, now)
        known = sorted([p for p, v in obs.items() if p != bad_prompt and p in spec["options"]["prompt_version"]
                        and v["connected"] >= self.s.known_good_min_connected and v["flag_rate"] <= 1.25 * ref],
                       key=lambda p: (-(obs[p]["engagement"] or 0), p))
        tried = d.setdefault("tried", {})
        cands = [(p, "known_good") for p in known if p not in tried]
        if not cands and d.get("llm_called"):
            cands = [(x["prompt_version"], "llm") for x in d.get("llm_suggestions", []) if x["prompt_version"] not in tried]
        if not cands and not d.get("llm_called"):
            cost = 3
            if self._credits_ok(cost, incident=True):
                try:
                    with db.tx():
                        lid = db.x("INSERT INTO credits_ledger (minute, wf, kind, purpose, state, cost) VALUES"
                                   " (?,?,?,?,?,?)", (now, wf, "llm", f"suggest fixes for {iid}", "sent", cost)).lastrowid
                    r = self.sim.suggest_fixes(spec["workflow_id"],
                                               f"hallucination flag rate spike on prompt {bad_prompt}")
                    with db.tx():   # paid suggestions are persisted with the ledger row (crash-safe, no re-buy)
                        db.x("UPDATE credits_ledger SET state='done', response=? WHERE id=?", (dumps(r), lid))
                        d["llm_called"] = True
                        d["llm_suggestions"] = r["suggestions"]
                        db.x("UPDATE incidents SET data=? WHERE incident_id=?", (dumps(d), iid))
                    cands = [(x["prompt_version"], "llm") for x in r["suggestions"] if x["prompt_version"] not in tried]
                except (ApiError, Uncertain) as e:
                    log.error("llm call failed: %s", e)
                    with db.tx():
                        db.x("UPDATE credits_ledger SET state=?, response=? WHERE id=?",
                             ("failed" if isinstance(e, ApiError) else "uncertain", str(e), lid))
        best = None

        def keep(run, p, src):
            # runs inside _validate's ledger transaction: the paid result, the incident's `tried` list and (if it
            # passes) the fix selection commit together, so a restart never pays to validate the same prompt again
            tried[p] = {"source": src, "validation": run}
            if run["pass_rate"] < thr:
                db.x("UPDATE incidents SET data=? WHERE incident_id=?", (dumps(d), iid))
                return
            d.update({"fix_prompt": p, "fix_source": src, "validation_run_id": run["validation_run_id"],
                      "validation": run})
            db.x("UPDATE incidents SET state='fix_ready', data=? WHERE incident_id=?", (dumps(d), iid))
            db.decide(now, wf, "incident_fix_selected", f"{iid}: fix = prompt {p} ({src}),"
                      f" validation pass {run['pass_rate']:.3f} >= {thr}", evidence=d, incident_id=iid,
                      reasoning="deterministic rule: candidates with observed history first (ordered by observed"
                                " engagement, because validation measures safety only), then LLM suggestions;"
                                " first candidate passing the policy validation threshold wins")

        for p, src in cands[:3]:
            run = self._validate(wf, spec, p, purpose=f"candidate fix for {iid} ({src})",
                                 persist=lambda r, p=p, src=src: keep(r, p, src))
            if not run:
                break
            if run["pass_rate"] >= thr:
                best = (p, src, run)
                break   # known-good list is already ordered by observed engagement: first passing wins
        with db.tx():
            if not best:
                db.x("UPDATE incidents SET data=? WHERE incident_id=?", (dumps(d), iid))
                db.decide(now, wf, "incident_no_fix", f"{iid}: no candidate passed validation yet", evidence=d,
                          incident_id=iid)

    # ---- experiments (C6/C7)
    def step_experiments(self, wf, spec, cfg, now, ctx):
        db = self.db
        active = Experiment.load_active(db, wf)
        cohorts = load_cohorts(db, wf, ("live",))
        margin = list(spec["objective"]["guardrail"].values())[0] if spec["objective"].get("guardrail") else 0.02
        look_hour = max(spec["governance"]["approver_hours"][0],
                        self.s.tenant_pref(spec["tenant_id"]).get("not_before_hour", 0))
        for dim in EXP_DIMS:
            black = db.kv_get(f"blacklist:{wf}", {})
            e = active.get(dim)
            if e is None:
                if dim in ctx["locks"] or len(spec["options"][dim]) < 2 or now < 0:
                    continue
                last = db.q1("SELECT MAX(updated_minute) FROM experiments WHERE wf=? AND dim=? AND status IN"
                             " ('rolled_back','aborted')", (wf, dim))[0]
                if last is not None and now - last < 1440:
                    continue
                last_nw = db.q1("SELECT MAX(updated_minute) FROM experiments WHERE wf=? AND dim=? AND status="
                                "'no_winner'", (wf, dim))[0]
                if last_nw is not None and now - last_nw < self.s.no_winner_cooldown_days * 1440:
                    continue
                r = db.q1("SELECT SUM(conn), SUM(eng) FROM calls WHERE wf=? AND minute>=? AND minute<?",
                          (wf, now - 7 * 1440, now))
                conn, eng = r[0] or 0, r[1] or 0
                if conn < 500:
                    continue
                days = min(7, (now - (db.q1("SELECT MIN(minute) FROM calls WHERE wf=?", (wf,))[0] or now)) / 1440) or 1
                e = self.exp.design(wf, dim, cfg, spec["options"][dim], black, now, eng / conn, conn / days)
                if e:
                    with db.tx():
                        e.save(db, now)
                        db.decide(now, wf, "experiment_designed",
                                  f"{dim}: test {e.arms} (incumbent {e.incumbent} keeps {e.design[e.incumbent]:.0%})",
                                  evidence={"design": e.design, "p_base": e.p_base, "n_plan_per_arm": e.n_plan,
                                            "achieved_mde_rel": e.achieved_mde},
                                  reasoning=f"factorial with the other dimension; alpha {self.s.alpha} family-wise"
                                            f" (Holm across challengers, O'Brien-Fleming spending across daily looks),"
                                            f" power {self.s.power}; planned n per challenger {e.n_plan} gives an MDE of"
                                            f" {e.achieved_mde:.1%} relative within {self.s.max_experiment_days:.0f} days",
                                  experiment_id=e.experiment_id)
                continue
            if e.status == "running":
                due_look = (now % 1440) // 60 == look_hour and now - (e.start_minute if e.start_minute is not None else now) >= 20 * 60
                final = now - (e.start_minute if e.start_minute is not None else now) >= e.horizon_days * 1440
                if due_look or final:
                    other_dim = "voice" if dim == "welcome_message" else "welcome_message"
                    od = cfg["allocations"]["default"][other_dim]
                    other = (other_dim, max(sorted(od), key=lambda o: od[o])) if len(spec["options"][other_dim]) > 1                         else None
                    res = self.exp.look(e, now, cohorts, {"margin": margin, "other": other}, final)
                    e.looks.append({k: v for k, v in res.items() if k != "cohort_check"} | {"cohort_check": res.get("cohort_check")})
                    with db.tx():
                        self._apply_look(e, res, now, wf)
                        e.save(db, now)
                else:
                    # hourly harm watch, stricter threshold because it is repeated (does not spend alpha)
                    counts = self.exp.arm_counts(e, until=now)["ALL"]
                    inc = counts.get(e.incumbent, (0, 0, 0))
                    from .stats import Prop, compare
                    bad = [o for o in e.arms if o != e.incumbent and o not in e.dropped
                           and counts.get(o, (0, 0, 0))[1] >= self.s.harm_min_connected
                           and compare(Prop(inc[2], inc[1]), Prop(counts[o][2], counts[o][1])).z < -2.33]
                    if bad and set(bad) - set(e.dropped):
                        with db.tx():
                            self._blacklist(wf, bad, days=self.s.harm_blacklist_days)
                            self.exp.plan_drop(e, bad)
                            e.save(db, now)
                            db.decide(now, wf, "experiment_drop_arm", f"{dim}: dropping {bad} (significantly worse)",
                                      evidence={o: counts.get(o) for o in bad} | {"incumbent": inc},
                                      experiment_id=e.experiment_id)
            elif e.status == "promoting" and "default" in e.promo and e.winner and ":" not in e.winner:
                # pooled promotions only; cohort-level winners ("cohort:option") have no pooled comparison to re-check
                # the promotion was decided at a look but is not live yet (approval latency, stale base, rejection):
                # re-check that the effect has not faded before we keep asking for it
                st = self.exp._unstable(e, now, [e.winner], {e.winner: _Cmp(e.promo["default"])}, cohorts)
                w = st.get(e.winner, {})
                # this check repeats hourly while the approval is pending: require evidence of fading (recent lift
                # <= 0 AND significantly below the overall lift at 1 %), not merely a noisy dip on a small sample
                if w.get("recent_lift") is not None and w["recent_lift"] <= 0                         and w.get("z_vs_overall", 0) < -self.s.decay_z:
                    with db.tx():
                        e.status, e.plan, e.promo, e.winner = "running", {"default": e.design}, {}, None
                        e.save(db, now)
                        wd = self.gov.withdraw_carrying(wf, e.experiment_id, now, "promotion withdrawn: effect faded")
                        st["withdrawn_proposals"] = wd
                        db.decide(now, wf, "promotion_withdrawn", f"{dim}: pending promotion withdrawn — the effect"
                                  f" has faded in the last 24 h; the test continues", evidence=st,
                                  experiment_id=e.experiment_id,
                                  reasoning="evidence must still hold when the change is applied, not only when it"
                                            " was decided")
            elif e.status == "promoted":
                dc = self.exp.decay_check(e, now, cohorts)
                if dc["decayed"]:
                    with db.tx():
                        bl = self.exp.plan_rollback(e, dc["decayed"], now)
                        self._blacklist(wf, bl)
                        e.save(db, now)
                        db.decide(now, wf, "decay_detected", f"{dim}: winner stopped winning in {dc['decayed']} —"
                                  f" rolling back to incumbent", evidence=dc, experiment_id=e.experiment_id,
                                  reasoning="recent winner-vs-holdout lift is significantly below the lift measured at"
                                            " promotion (z<-2.33) or significantly negative")
                    ctx["kinds"].append("decay_rollback")
                    ctx["urgent"] = True

    def _blacklist(self, wf: int, opts: list[str], days: float | None = None):
        """Options we have evidence against are not re-tested for a while: 7 days after a decay rollback,
        14 days after being dropped as significantly worse than the incumbent."""
        black = self.db.kv_get(f"blacklist:{wf}", {})
        for o in opts:
            black[o] = max(black.get(o, 0), self.now + int((days or self.s.rollback_blacklist_days) * 1440))
        self.db.kv_set(f"blacklist:{wf}", black)

    def _apply_look(self, e: Experiment, res: dict, now: int, wf: int):
        a = res["action"]
        if a == "extend":
            self.db.decide(now, wf, "experiment_extended", f"{e.dim}: horizon reached without significance but the best"
                           f" challenger trends positive — extending once to {e.horizon_days:.0f} days",
                           evidence=res, experiment_id=e.experiment_id,
                           reasoning="pre-registered single extension when under-powered; alpha is tracked as an explicit"
                                     f" budget (spent so far {e.alpha_spent:.4f} of {self.s.alpha}) so the family-wise"
                                     " false-winner rate stays <= alpha")
        elif a in ("promote", "promote_cohorts"):
            self.exp.plan_promotion(e, res)
            self.db.decide(now, wf, "experiment_winner",
                           f"{e.dim}: winner {e.winner} (look t={res['t']}, alpha_look={res.get('alpha_look')})",
                           evidence=res, experiment_id=e.experiment_id,
                           reasoning="Holm-adjusted one-sided z-test on engagement at the O'Brien-Fleming nominal level"
                                     " for this look; guardrail and per-cohort harm checks passed; highest 80% lower"
                                     " confidence bound chosen")
        elif a == "no_winner":
            self.exp.plan_no_winner(e)
            self.db.decide(now, wf, "experiment_no_winner", f"{e.dim}: no significant winner at horizon — keep"
                           f" incumbent {e.incumbent}", evidence=res, experiment_id=e.experiment_id,
                           reasoning="insufficient evidence keeps the incumbent")
        elif a == "drop":
            self._blacklist(wf, res["drop"], days=self.s.harm_blacklist_days)
            self.exp.plan_drop(e, res["drop"])
            self.db.decide(now, wf, "experiment_drop_arm", f"{e.dim}: dropping {res['drop']}", evidence=res,
                           experiment_id=e.experiment_id)
        else:
            self.db.decide(now, wf, "experiment_look", f"{e.dim}: look t={res.get('t')} — continue", evidence=res,
                           experiment_id=e.experiment_id)

    # ---- desired config
    def desired_config(self, wf, spec, cfg, dids, ctx) -> dict:
        db = self.db
        locks = ctx["locks"]
        new = copy.deepcopy(cfg)
        comps = ctx.setdefault("components", {})
        cohorts = load_cohorts(db, wf, ("proposed", "live"))
        ours = [c.to_config() for c in cohorts]
        if cohorts and "cohorts" not in locks and "schedule" not in locks:
            if not cfg.get("cohorts") or cfg["cohorts"] == ours:
                new["cohorts"] = ours
                sch = db.kv_get(f"schedule:{wf}", {})
                if sch.get("hour_weights"):
                    new["schedule"] = {"hour_weights": sch["hour_weights"],
                                       "lead_preferred_hour": cfg["schedule"].get("lead_preferred_hour", {})}
                    if new["schedule"] != cfg["schedule"]:
                        comps["schedule"] = {"summary": f"call-hour weights for {len(sch['hour_weights'])} cohorts",
                                             "dry_run": sch.get("dry_run")}
        pm = db.kv_get(f"ptime_map:{wf}")
        if pm and "schedule" not in locks:
            cur_lph = cfg["schedule"].get("lead_preferred_hour", {})
            mine = set(db.kv_get(f"ptime_written:{wf}", []))
            # keep entries someone else (a supervisor) set; ours are replaced by the current map or removed on stop
            lph = {k: v for k, v in cur_lph.items() if k not in mine}
            if pm["status"] in ("testing", "expanded"):
                lph.update(pm["map"])
            sched = new.setdefault("schedule", copy.deepcopy(cfg["schedule"]))
            if lph != cur_lph:
                sched["lead_preferred_hour"] = lph
                comps.setdefault("schedule", {"summary": "", "dry_run": None})
                comps["schedule"]["summary"] = (comps["schedule"]["summary"] + "; " if comps["schedule"]["summary"] else "")                     + f"per-person preferred hours for {len(pm['map'])} treated people ({pm['status']})"
                with db.tx():   # remember every entry we ever wrote, so a stop removes ours and only ours
                    db.kv_set(f"ptime_written:{wf}", sorted(mine | set(pm["map"])))
        if "caller_id" not in locks:
            cur = cfg["allocations"]["default"]["caller_id"]
            tgt = self.did_target(spec["options"]["caller_id"], dids, cur)
            removing_bad = any(dids.get(d, {}).get("state") == "degraded" and w > 0 for d, w in cur.items())
            changed = False
            if tv_distance(cur, tgt) >= self.s.did_min_tv_change or removing_bad:
                new["allocations"]["default"]["caller_id"] = tgt
                changed = True
            # a cohort-level caller-ID override that still dials a degraded number gets the same target
            for scope, dims_ in new["allocations"].items():
                if scope != "default" and "caller_id" in dims_ and any(
                        dids.get(d, {}).get("state") == "degraded" and w > 0 for d, w in dims_["caller_id"].items()):
                    dims_["caller_id"] = dict(tgt)
                    removing_bad = changed = True
            if changed:
                comps["caller_id"] = {"summary": "caller IDs: " + ", ".join(f"{d} {w:.0%}" for d, w in sorted(tgt.items())),
                                      "health": ctx["evidence"].get("caller_id"), "urgent": removing_bad}
        live_ids = {c["id"] for c in new.get("cohorts", [])}
        for dim, e in Experiment.load_active(db, wf).items():
            if dim in locks or e.status == "aborted":
                continue
            plan = e.design if e.status in ("designed", "running") else e.plan
            plan = {"default": plan} if e.status in ("designed", "running") else plan
            if e.status in ("designed", "running"):
                # a cohort-level override of the same dimension would give the arms different cohort mixes in the
                # pooled comparison; the test runs on one allocation for everyone (sent via approval, never silent)
                for scope in list(new["allocations"]):
                    if scope != "default" and dim in new["allocations"][scope]:
                        new["allocations"][scope].pop(dim)
            for scope, dist in plan.items():
                if scope != "default" and scope not in live_ids:
                    continue
                if scope == "default":
                    new["allocations"]["default"][dim] = dict(dist)
                else:
                    new["allocations"].setdefault(scope, {})[dim] = dict(dist)
            if _alloc_changed(cfg, new, dim):
                comps[dim] = {"summary": f"{dim}: {e.status} " + "; ".join(
                    f"{sc}={','.join(f'{o} {w:.0%}' for o, w in sorted(d.items()))}" for sc, d in plan.items()),
                    "experiment_id": e.experiment_id, "status": e.status, "evidence": e.looks[-1] if e.looks else
                    {"design": e.design, "n_plan": e.n_plan, "achieved_mde": e.achieved_mde}}
        if ctx.get("prompt_fix"):   # deliberately overrides a supervisor lock: always via an approval that says so
            iid, d = ctx["prompt_fix"]
            new["prompt_version"] = d["fix_prompt"]
            comps["prompt_version"] = {"summary": f"revert unsafe prompt {d['bad_prompt']} -> {d['fix_prompt']}",
                                       "incident_id": iid, "validation": d.get("validation")}
        return new

    # ---- routing through governance
    def route(self, wf, spec, cur, desired, ctx):
        db, now = self.db, self.now
        cfg = cur["config"]
        dims = changed_dims(cfg, desired)
        if not dims:
            return
        pol = spec["governance"]["auto_apply"]
        comps = ctx.get("components", {})
        wid = spec["workflow_id"]
        open_p = self.gov.open_proposal(wf)
        prompt_fix = "prompt_version" in dims
        did_urgent = bool(comps.get("caller_id", {}).get("urgent"))
        if any(e.status == "rolling_back" for e in Experiment.load_active(db, wf).values()):
            ctx["urgent"] = True   # moving off a variant that stopped working stays urgent until it is live

        # 1) prompt incident: a focused approval request (prompt only), emergency slot
        if prompt_fix:
            fix_cfg = copy.deepcopy(cfg)
            fix_cfg["prompt_version"] = desired["prompt_version"]
            if open_p is None or open_p[2] != "incident":
                ok, why = self.gov.submit_window(spec, now, emergency=True)
                ok2, why2 = self.gov.can_request(wf, spec, now, emergency=True)
                if ok and ok2:
                    self._submit(wf, spec, cur, fix_cfg, {"prompt_version": comps["prompt_version"]}, "incident",
                                 emergency=True)
                    return
                self._hold(wf, f"prompt fix waiting: {why if not ok else why2}")
            dims = [d for d in dims if d != "prompt_version"]
            desired = copy.deepcopy(desired)
            desired["prompt_version"] = cfg["prompt_version"]

        denied = {d for d, until in db.kv_get(f"auto_denied:{wf}", {}).items() if until > now}
        supervisor_set = set(db.kv_get(f"supervisor_dims:{wf}", []))
        auto_ok_dims = {d for d in dims if pol.get("enabled") and d in pol.get("allowed_dims", [])
                        and d not in self.s.customer_facing_dims and d != "cohorts"
                        and d not in denied                 # a 403 sends the dim to the approval route for 24h
                        and d not in supervisor_set}        # never auto-apply over a supervisor's choice
        approval_dims = [d for d in dims if d not in auto_ok_dims]

        # 2) urgent operational fix (degraded caller ID) via auto-apply, ramped within max_shift
        if did_urgent and "caller_id" in auto_ok_dims:
            if self._auto_step(wf, spec, cur, desired, ["caller_id"], urgent=True):
                return

        # 3) approval-route changes, batched into one request
        if approval_dims:
            emergency = did_urgent or ctx.get("urgent", False)
            if open_p is not None and not (emergency and open_p[2] == "routine"):
                return  # one open proposal per workflow: wait (an emergency may overtake a routine one)
            ok, why = self.gov.submit_window(spec, now, emergency=emergency)
            ok2, why2 = self.gov.can_request(wf, spec, now, emergency=emergency)
            if ok and ok2:
                self._submit(wf, spec, cur, desired, comps, "routine" if not emergency else "urgent",
                             emergency=emergency)
                return
            self._hold(wf, f"{approval_dims} waiting: {why if not ok else why2}")
        # 4) operational changes we may auto-apply now (only when nothing is pending, so we don't stale it)
        if auto_ok_dims and open_p is None:
            self._auto_step(wf, spec, cur, desired, sorted(auto_ok_dims), urgent=False)

    def _hold(self, wf, why):
        key = f"hold:{wf}"
        if self.db.kv_get(key) != why:
            with self.db.tx():
                self.db.kv_set(key, why)
                self.db.decide(self.now, wf, "hold", why,
                               reasoning="governance timing/fatigue rules: send when an approver is there and can"
                                         " answer before expiry, within the request budget")

    def _auto_step(self, wf, spec, cur, desired, dims, urgent) -> bool:
        cfg = cur["config"]
        pol = spec["governance"]["auto_apply"]
        step = copy.deepcopy(cfg)
        for d in dims:
            if d == "schedule":
                if desired.get("cohorts") != cfg.get("cohorts"):
                    continue  # schedule references cohorts that aren't live yet
                step["schedule"] = desired["schedule"]
            elif d in AGENT_DIMS:
                step["allocations"]["default"][d] = desired["allocations"]["default"][d]
        if not changed_dims(cfg, step):
            return False
        ms = pol.get("max_shift", 0.0)
        shift = max_shift(cfg, step)
        ramp = None
        if shift > ms + 1e-9:
            # ramp caller_id toward target by at most max_shift per step, >= 1h apart, cumulative cap per day
            last = self.db.q1("SELECT MAX(created_minute) FROM proposals WHERE wf=? AND route='auto' AND state='APPLIED'",
                              (wf,))[0]
            if last is not None and self.now - last < self.s.ramp_min_gap_minutes:
                return False
            moved = self.db.kv_get(f"ramp:{wf}:{self.now // 1440}", 0.0)
            budget = self.s.ramp_daily_shift_multiple * ms - moved
            frac = min(ms, budget) / shift if shift else 0
            if frac <= 0.01:
                self._hold(wf, "auto-apply ramp budget for today used")
                return False
            a = cfg["allocations"]["default"]["caller_id"]
            b = step["allocations"]["default"]["caller_id"]
            for margin in (0.98, 0.95, 0.9, 0.8):   # rounding + canonicalisation must not push past max_shift
                mix = {k: a.get(k, 0) + (b.get(k, 0) - a.get(k, 0)) * frac * margin for k in set(a) | set(b)}
                step["allocations"]["default"]["caller_id"] = {k: round(v, 4) for k, v in mix.items() if v > 1e-4}
                if max_shift(cfg, canonical_config(cfg, step)) <= ms - 1e-6:
                    break
            ramp = {"target": b, "fraction": round(frac, 3)}
            shift = max_shift(cfg, step)
        comps = {}
        body = {"proposal_id": self.gov.new_id(spec["workflow_id"], self.now), "base_version": cur["version"],
                "proposed_config": canonical_config(cfg, step),
                "rationale": self._rationale(wf, cfg, step, urgent),
                "evidence": {"caller_id": self.db.kv_get(f"did:{wf}"), "ramp": ramp,
                             "schedule_dry_run": (self.db.kv_get(f"schedule:{wf}") or {}).get("dry_run")}}
        day_key = f"ramp:{wf}:{self.now // 1440}"
        state, resp = self.gov.auto_apply(
            wf, spec["workflow_id"], "urgent" if urgent else "operational", body, self.now,
            on_applied=lambda: self.db.kv_set(day_key, self.db.kv_get(day_key, 0.0) + shift))   # same tx as APPLIED
        with self.db.tx():
            if state == "AUTO_DENIED":
                den = self.db.kv_get(f"auto_denied:{wf}", {})
                for d in changed_dims(cfg, step):
                    den[d] = self.now + 1440
                self.db.kv_set(f"auto_denied:{wf}", den)
            self.db.decide(self.now, wf, "auto_apply", f"auto-apply {changed_dims(cfg, step)} -> {state}"
                           + (f" (ramp {ramp['fraction']:.0%} of the way)" if ramp else ""),
                           reasoning=body["rationale"], evidence={"response": resp, "shift": round(shift, 3),
                                                                  "max_shift": ms, "ramp": ramp},
                           proposal_id=body["proposal_id"], config_version=(resp or {}).get("version"),
                           outcome=state)
        return state == "APPLIED"

    def _did_text(self, wf) -> str:
        mem = self.db.kv_get(f"did:{wf}", {})
        bad = [d for d, v in mem.items() if v.get("state") == "degraded"]
        return (("Move traffic off degraded caller IDs " + ", ".join(bad) + ". " if bad else "")
                + "Spread dials evenly over healthy numbers (lower per-number volume), 5% probe on untested"
                  " numbers so their health is measured before they carry real volume.")

    def _rationale(self, wf, old, new, urgent) -> str:
        parts = []
        dims = changed_dims(old, new)
        if "caller_id" in dims:
            parts.append(self._did_text(wf))
        if "schedule" in dims:
            parts.append("Call each cohort in the hours its own history shows the best pickup (smoothed estimates"
                         " from pre-D0 history; weights clipped to [0.25, 4] so no hour is starved).")
        return " ".join(parts) or "operational adjustment"

    # ---- proposal assembly (C10)
    def _submit(self, wf, spec, cur, desired, comps, kind, emergency):
        db, now = self.db, self.now
        cfg = cur["config"]
        dims = changed_dims(cfg, desired)
        diff = {}
        for d in dims:
            if d == "cohorts":
                diff[d] = {"before": [c["id"] for c in cfg.get("cohorts", [])],
                           "after": [c["id"] for c in desired.get("cohorts", [])]}
            elif d == "schedule":
                diff[d] = {"hour_weights_after": desired["schedule"]["hour_weights"]}
            elif d == "prompt_version":
                diff[d] = {"before": cfg["prompt_version"], "after": desired["prompt_version"]}
            else:
                scopes = set(cfg["allocations"]) | set(desired["allocations"])
                diff[d] = {sc: {"before": _dist(cfg, sc, d), "after": _dist(desired, sc, d)} for sc in sorted(scopes)
                           if tv_distance(_dist(cfg, sc, d), _dist(desired, sc, d)) > 1e-9}
        affected = self.affected_leads(wf, spec, cfg, desired, dims)
        impact, impact_detail = self.impact(wf, spec, comps, dims, kind)
        summary = "; ".join(c["summary"] for k, c in comps.items() if k in dims or (k == "schedule" and "cohorts" in dims))
        if "cohorts" in dims and "schedule" not in comps:
            summary = f"define cohorts {[c['id'] for c in desired['cohorts']]}; " + summary
        dry = {k: v.get("dry_run") or v.get("evidence") or v.get("validation") or v.get("health")
               for k, v in comps.items() if k in dims or k == "schedule"}
        dry["method_note"] = ("all figures replay our own recorded calls; experiment arms only count calls that actually"
                              " ran with that variant")
        body = {"proposal_id": self.gov.new_id(spec["workflow_id"], now), "workflow_id": spec["workflow_id"],
                "base_version": cur["version"], "proposed_config": canonical_config(cfg, desired),
                "change_summary": summary[:300] or f"update {', '.join(dims)}",
                "diff": diff, "affected_leads": affected, "dry_run": dry, "impact_score": round(impact, 3),
                "rationale": self._proposal_rationale(wf, comps, dims, kind),
                "evidence": {"impact_detail": impact_detail,
                             "experiments": {k: v.get("experiment_id") for k, v in comps.items() if v.get("experiment_id")}},
                "expires_in_hours": spec["governance"]["proposal_ttl_hours"]}
        if "prompt_version" in dims:
            body["evidence"]["validation_run_id"] = comps["prompt_version"]["validation"]["validation_run_id"]
            body["evidence"]["incident_id"] = comps["prompt_version"]["incident_id"]
        state, resp = self.gov.submit(wf, spec["workflow_id"], kind, body, now)
        with db.tx():
            db.decide(now, wf, "proposal_submitted", f"{body['proposal_id']} -> {state}: {body['change_summary']}",
                      reasoning=body["rationale"], evidence={"diff": diff, "affected_leads": affected,
                                                             "impact_score": body["impact_score"],
                                                             "impact_detail": impact_detail, "dry_run": dry},
                      proposal_id=body["proposal_id"], approval_id=(resp or {}).get("approval_id"), outcome=state,
                      incident_id=body["evidence"].get("incident_id"))
            if "prompt_version" in dims and state == "PENDING":
                iid = comps["prompt_version"]["incident_id"]
                d = json.loads(db.q1("SELECT data FROM incidents WHERE incident_id=?", (iid,))[0])
                d["proposal_id"] = body["proposal_id"]
                db.x("UPDATE incidents SET state='proposed', data=? WHERE incident_id=?", (dumps(d), iid))
            db.kv_set(f"hold:{wf}", None)

    def _proposal_rationale(self, wf, comps, dims, kind) -> str:
        out = []
        if "prompt_version" in dims:
            c = comps["prompt_version"]
            v = c.get("validation") or {}
            out.append(f"Safety incident {c['incident_id']}: the live prompt is producing hallucinations above the"
                       f" workflow's own baseline. {c['summary']}; validation run {v.get('validation_run_id')} passed at"
                       f" {v.get('pass_rate')}. This reverses a recent prompt change and is sent for your approval rather"
                       f" than applied silently.")
        for d in ("welcome_message", "voice"):
            if d in comps and d in dims:
                c = comps[d]
                st = c.get("status")
                out.append({"designed": f"Start a controlled test of {d}: the current option keeps most traffic, the"
                                        f" alternatives share the rest; a winner is declared only by a pre-registered"
                                        f" statistical rule (see evidence).",
                            "promoting": f"{d}: promote the statistically significant winner, keeping a holdout on the"
                                         f" previous option to detect if the effect fades.",
                            "concluding": f"{d}: the test found no significant winner — return all traffic to the"
                                          f" current option.",
                            "rolling_back": f"{d}: the promoted option stopped beating the holdout — roll back.",
                            "running": f"{d}: drop an alternative that is significantly worse."}.get(st, d))
        if "caller_id" in dims:
            out.append(self._did_text(wf))
        if "schedule" in dims or "cohorts" in dims:
            out.append("Cohort call-hour weights from history: each age/feature group is called more in the hours"
                       " it actually picks up (who is called when; capacity, windows and cadence unchanged).")
        return " ".join(out) or "configuration update"

    def affected_leads(self, wf, spec, cfg, new, dims) -> int:
        """Active leads (not concluded, inside cadence) whose experience changes. For next_campaign_only the
        customer-facing part only reaches the next campaign: count its expected size."""
        db, now = self.db, self.now
        day = now // 1440
        L = len(spec["cadence"])
        active = db.q1("SELECT COUNT(*) FROM leads WHERE wf=? AND campaign_day>? AND concluded_minute IS NULL",
                       (wf, day - L))[0]
        if spec["mid_flight"] == "next_campaign_only" and not ({"schedule", "prompt_version"} & set(dims)):
            return int(spec["daily_batch"]["size"])
        return int(active)

    def impact(self, wf, spec, comps, dims, kind) -> tuple[float, dict]:
        """impact = clip(lift_lcb/0.10, 0, 1) x share affected; exploration 0.15; incident >= 0.8."""
        detail = {}
        if "prompt_version" in dims:
            return 0.9, {"basis": "safety incident fix (validated)"}
        best = 0.0
        for d in ("welcome_message", "voice"):
            c = comps.get(d)
            if not c or d not in dims:
                continue
            ev = c.get("evidence") or {}
            if c.get("status") == "promoting" and ev.get("winner"):
                a = ev["arms"][ev["winner"]]
                inc = ev["incumbent"]
                from .stats import Prop, compare
                cmp_ = compare(Prop(inc["engaged"], inc["connected"]), Prop(a["engaged"], a["connected"]))
                lcb_rel = cmp_.lcb(0.8) / (inc["engaged"] / inc["connected"]) if inc["connected"] else 0
                score = min(max(lcb_rel / 0.10, 0), 1) * (1 - self.s.holdout_share)
                detail[d] = {"lift_lcb_rel": round(lcb_rel, 4), "score": round(score, 3)}
                best = max(best, score)
            elif c.get("status") == "rolling_back":
                detail[d] = {"basis": "decay rollback", "score": 0.6}
                best = max(best, 0.6)
            else:
                detail[d] = {"basis": "exploration (expected lift unknown)", "score": 0.15}
                best = max(best, 0.15)
        if "schedule" in comps and ("schedule" in dims or "cohorts" in dims):
            dl = (comps["schedule"].get("dry_run") or {}).get("rel_lift", 0) or 0
            sc = min(max(dl / 0.10, 0), 1) * 0.5   # dry run is an upper bound: halve it
            detail["schedule"] = {"dry_run_rel_lift": dl, "score": round(sc, 3)}
            best = max(best, sc)
        if "caller_id" in dims:
            sc = 0.7 if comps.get("caller_id", {}).get("urgent") else 0.1
            detail["caller_id"] = {"score": sc}
            best = max(best, sc)
        return best, detail

    # ------------------------------------------------------------------ observability (C14)
    def _metrics(self, n_events: int, ingest_s: float, st: dict, decide_s: float = 0.0, advance_s: float = 0.0):
        db, now = self.db, self.now
        acc = self.day_acc.setdefault(now // 1440 if now % 1440 else now // 1440 - 1,
                                      {"events": 0, "ingest_s": 0.0, "decide_s": 0.0, "advance_s": 0.0,
                                       "max_tick_controller_s": 0.0})
        acc["events"] += n_events
        acc["ingest_s"] += ingest_s
        acc["decide_s"] += decide_s
        acc["advance_s"] += advance_s
        acc["max_tick_controller_s"] = max(acc["max_tick_controller_s"], ingest_s + decide_s)
        lag = st["sim_minute"] - (db.q1("SELECT MAX(until_minute) FROM chunks")[0] or 0)
        with db.tx():
            db.metric(now, "ingest_events", n_events)
            db.metric(now, "ingest_seconds", ingest_s)
            db.metric(now, "ingest_lag_minutes", lag)
            db.metric(now, "decide_seconds", decide_s)
            db.metric(now, "advance_seconds", advance_s)
            if now % 60 == 0:
                st = self.sim.state()
                db.metric(now, "credits_remaining", st["credits_remaining"])
                db.metric(now, "open_proposals", db.q1("SELECT COUNT(*) FROM proposals WHERE state IN"
                                                       " ('PENDING','APPROVED','APPLYING')")[0])
                db.metric(now, "decisions_last_hour", db.q1("SELECT COUNT(*) FROM decisions WHERE minute>? AND minute<=?",
                                                            (now - 60, now))[0])
                db.metric(now, "rss_mb", _rss_mb())
            if now % 1440 == 0:
                d = now // 1440 - 1
                w0 = self.day_wall.get(d)
                if w0:
                    db.metric(now, "wall_seconds_per_sim_day", time.time() - w0, {"day": d})
                    a = self.day_acc.get(d, {})
                    db.metric(now, "controller_seconds_per_sim_day", a.get("ingest_s", 0) + a.get("decide_s", 0),
                              {"day": d, **{k: round(v, 2) for k, v in a.items()}})
                    log.info("D%d done: %.1fs wall, credits %.0f, ingest total %d events", d, time.time() - w0,
                             st["credits_remaining"], self.ing.events_total)


class _Cmp:
    """Minimal stand-in for stats.Comparison built from a stored promotion record (diff, se)."""
    def __init__(self, rec: dict):
        self.diff, self.se = rec["diff"], rec["se"]


def _alloc_changed(old, new, dim) -> bool:
    keys = set(old["allocations"]) | set(new["allocations"])
    return any(tv_distance(_dist(old, k, dim), _dist(new, k, dim)) > 1e-9 for k in keys)


def _rss_mb() -> float:
    try:
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    except ImportError:
        try:
            import ctypes
            from ctypes import wintypes

            class PMC(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
            c = PMC()
            c.cb = ctypes.sizeof(PMC)
            k32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
            k32.GetCurrentProcess.restype = wintypes.HANDLE
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
            psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
            if not psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb):
                return -1.0
            return c.PeakWorkingSetSize / 2 ** 20
        except Exception:
            return -1.0
