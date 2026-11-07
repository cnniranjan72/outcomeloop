"""Crash-recovery harness: hard-kill the controller at chosen moments, restart it, let it finish, verify.

    python scripts/crash_recovery.py                       # defaults: public_02_incidents on :8711
    python scripts/crash_recovery.py --port 8712 --skip-grade

What it does
  1. starts the simulator (`python -m sim serve ... --force`) and waits for /health;
  2. launches the controller (`python -m outcomeloop run --url ...`, PYTHONPATH=src, OUTCOMELOOP_DB=...) and
     HARD-kills it (Popen.kill(): SIGKILL on Linux, TerminateProcess on Windows — no graceful shutdown, no
     atexit, no finally blocks) when a trigger fires. Triggers watch the controller's SQLite store (opened
     read-only) and the simulator's public API, so each kill lands on a specific in-flight state;
  3. after each kill records a timeline entry (wall time, sim minute, DB counts, what was in flight);
  4. after the last kill lets the controller run to completion, then runs scripts/verify_recovery.py
     (exactly-once ingestion, no double apply, no lost approvals, learning kept, run finished, grade);
  5. stops the simulator (only the process this script started, by its PID).

This is a TEST HARNESS, not the controller: it is allowed to read runs/ (sim output) after the run.
Only the standard library is used, so it runs anywhere the controller runs (Linux grader box, Windows dev box).
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OPEN_STATES = ("SUBMITTING", "PENDING", "APPROVED", "APPLYING", "AUTO_APPLYING")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


def label(minute: int | None) -> str:
    if minute is None:
        return "?"
    d, m = divmod(minute, 1440)
    return f"D{d} {m // 60:02d}:{m % 60:02d}"


# ------------------------------------------------------------------------------------------ simulator API
class Sim:
    def __init__(self, url: str):
        self.url = url.rstrip("/")

    def get(self, path: str, timeout: float = 30.0):
        with urllib.request.urlopen(self.url + path, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def healthy(self) -> bool:
        try:
            return bool(self.get("/health", timeout=2).get("ok"))
        except Exception:
            return False


# ------------------------------------------------------------------------------------------ DB observer
class DBView:
    """Read-only view of the controller's SQLite store. Never writes; tolerates the file not existing yet."""

    def __init__(self, path: Path):
        self.path = path
        self.conn: sqlite3.Connection | None = None

    def _c(self) -> sqlite3.Connection | None:
        if self.conn is None:
            if not self.path.exists():
                return None
            try:
                self.conn = sqlite3.connect(f"file:{self.path.as_posix()}?mode=ro", uri=True, timeout=5,
                                            isolation_level=None)
            except sqlite3.Error:
                return None
        return self.conn

    def close(self):
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def q(self, sql: str, args=()) -> list:
        c = self._c()
        if c is None:
            return []
        try:
            return c.execute(sql, args).fetchall()
        except sqlite3.OperationalError:
            # table not created yet / transient lock: report "nothing"
            return []

    def q1(self, sql: str, args=(), default=None):
        r = self.q(sql, args)
        return r[0][0] if r and r[0][0] is not None else default

    # -------------------------------------------------------------- cheap probes used while polling
    def max_start_decision(self) -> int:
        return self.q1("SELECT MAX(decision_id) FROM decisions WHERE kind IN ('controller_start','controller_restart')",
                       default=0)

    def proposals_in(self, states: tuple[str, ...]) -> list:
        return self.q(f"SELECT proposal_id, state, route, kind, approval_id, base_version FROM proposals WHERE state IN"
                      f" ({','.join('?' * len(states))})", states)

    def ledger_sent(self) -> list:
        return self.q("SELECT id, minute, kind, purpose, cost FROM credits_ledger WHERE state='sent'")

    def prompt_probes(self) -> list:
        return [(k, v) for k, v in self.q("SELECT k, v FROM kv WHERE k LIKE 'prompt_probe:%'") if v not in ("[]", "null")]

    # -------------------------------------------------------------- full snapshot (taken when the process is dead)
    def snapshot(self) -> dict:
        if self._c() is None:
            return {"db_exists": False}
        snap = {
            "db_exists": True,
            "chunks": self.q1("SELECT COUNT(*) FROM chunks", default=0),
            "max_chunk": self.q1("SELECT MAX(chunk) FROM chunks"),
            "events_ingested": self.q1("SELECT SUM(events) FROM chunks", default=0),
            "ingested_until_minute": self.q1("SELECT MAX(until_minute) FROM chunks"),
            "calls": self.q1("SELECT COUNT(*) FROM calls", default=0),
            "decisions": self.q1("SELECT COUNT(*) FROM decisions", default=0),
            "max_decision_id": self.q1("SELECT MAX(decision_id) FROM decisions", default=0),
            "proposals_by_state": dict(self.q("SELECT state, COUNT(*) FROM proposals GROUP BY state")),
            "experiments_by_status": dict(self.q("SELECT status, COUNT(*) FROM experiments GROUP BY status")),
            "incidents_by_state": dict(self.q("SELECT state, COUNT(*) FROM incidents GROUP BY state")),
            "credits_ledger_by_state": dict(self.q("SELECT state, COUNT(*) FROM credits_ledger GROUP BY state")),
            "inbox_undone": self.q1("SELECT COUNT(*) FROM inbox WHERE done=0", default=0),
            "bootstrapped_workflows": self.q1("SELECT COUNT(*) FROM kv WHERE k LIKE 'boot:%' AND v!='null'", default=0),
        }
        snap["in_flight"] = {
            "open_proposals": [dict(zip(("proposal_id", "state", "route", "kind", "approval_id", "base_version"), r))
                               for r in self.proposals_in(OPEN_STATES)],
            "credits_ledger_sent": [dict(zip(("id", "minute", "kind", "purpose", "cost"), r)) for r in self.ledger_sent()],
            "pending_prompt_probes": [{"key": k, "value": json.loads(v)} for k, v in self.prompt_probes()],
            "open_incidents": [dict(zip(("incident_id", "state", "opened_minute"), r)) for r in
                               self.q("SELECT incident_id, state, opened_minute FROM incidents WHERE state!='closed'")],
            "active_experiments": [dict(zip(("experiment_id", "dim", "status"), r)) for r in
                                   self.q("SELECT experiment_id, dim, status FROM experiments WHERE status IN"
                                          " ('designed','running','promoting','promoted','concluding','rolling_back')")],
        }
        snap["last_decisions"] = [dict(zip(("decision_id", "minute", "kind", "summary"), r)) for r in
                                  self.q("SELECT decision_id, minute, kind, substr(summary,1,140) FROM decisions"
                                         " ORDER BY decision_id DESC LIMIT 6")]
        return snap


# ------------------------------------------------------------------------------------------ simulator watcher
class SimWatcher(threading.Thread):
    """Polls /sim/state (and, when asked, /approvals?status=approved) in the background. Those calls block while
    the simulator is busy with the controller's /sim/advance (it serialises requests), and the fast DB poll that
    times the kills must never wait for them."""

    def __init__(self, sim: Sim, interval: float = 0.01):
        super().__init__(daemon=True)
        self.sim, self.interval = sim, interval
        self.minute: int | None = None
        self.approved: list[str] = []
        self.want_approvals = False
        self.halt = threading.Event()

    def run(self):
        while not self.halt.is_set():
            try:
                self.minute = self.sim.get("/sim/state", timeout=30)["sim_minute"]
                if self.want_approvals:
                    self.approved = [x["approval_id"] for x in self.sim.get("/approvals?status=approved", timeout=30)]
            except Exception:
                pass
            time.sleep(self.interval)


# ------------------------------------------------------------------------------------------ kill schedule
# A kill spec: label, aim, arm(ctx), fire(ctx) -> reason|None, fallback(ctx) -> reason|None,
# want(snapshot) -> bool (did the kill land on the targeted state?), attempts (re-try the same target after a
# restart when the kill landed just after the state had already moved on).
# ctx: elapsed (s since launch), started (this launch wrote its start/restart decision), minute (sim, from the
# watcher), db (DBView), watcher, args, st (per-attempt scratch dict).

def fallback_after(minute_limit):
    def f(ctx):
        if ctx["started"] and ctx["minute"] is not None and ctx["minute"] >= minute_limit:
            return f"fallback: sim reached {label(minute_limit)} without the targeted state"
    return f


def fallback_elapsed(sec):
    def f(ctx):
        if ctx["elapsed"] >= sec:
            return f"fallback: {ctx['elapsed']:.1f}s after launch"
    return f


def arm_from(minute_from):
    def a(ctx):
        return ctx["started"] and ctx["minute"] is not None and ctx["minute"] >= minute_from
    return a


def armed_started(ctx):
    return ctx["started"]


def trig_history(ctx):
    # (a) start-up has registered the workflows (so it is past the world-identity check) and is now fetching /
    # ingesting history chunk 0 (~187k pre-D0 events, one transaction). Kill --history-dwell-s into that.
    db = ctx["db"]
    if db.q1("SELECT COUNT(*) FROM workflows", default=0) > 0 and db.q1("SELECT COUNT(*) FROM chunks", default=0) == 0:
        t = ctx["st"].setdefault("ingest_seen", time.time())
        if time.time() - t >= ctx["args"].history_dwell_s:
            return (f"history backlog ingestion in progress: workflows registered, 0 chunks committed,"
                    f" {time.time() - t:.1f}s into ingest ({ctx['elapsed']:.1f}s after launch)")


def trig_pending(ctx):
    # (c) a proposal is PENDING at the approver according to OUR store
    rows = ctx["db"].proposals_in(("PENDING",))
    if rows:
        return f"proposal {rows[0][0]} is PENDING (approval {rows[0][4]})"


def trig_approved(ctx):
    # (d) APPROVED/APPLYING in our store (preferred), or approved at the simulator while our row is still PENDING
    ctx["watcher"].want_approvals = True
    rows = ctx["db"].proposals_in(("APPROVED", "APPLYING"))
    if rows:
        return f"proposal {rows[0][0]} is {rows[0][1]} in our store (approval {rows[0][4]})"
    pend = {r[4]: r[0] for r in ctx["db"].proposals_in(("PENDING",))}
    hit = [x for x in ctx["watcher"].approved if x in pend]
    if hit:
        return f"approval {hit[0]} ({pend[hit[0]]}) is 'approved' at the simulator, our row still PENDING (not yet applied)"


def trig_midday(ctx):
    # (b) mid-day while dialling (D1 11:00, inside every workflow's dialling window)
    if ctx["minute"] is not None and ctx["minute"] >= 1440 + 660:
        return f"mid-day while dialling ({label(ctx['minute'])})"


def trig_incident(ctx):
    # (e) around the D3 11:30 supervisor prompt change: kill while a credit-spending validation is in flight
    sent = ctx["db"].ledger_sent()
    if sent:
        return f"credit-spending call in flight: ledger row {sent[0][0]} '{sent[0][3]}' state=sent"


def trig_supervisor_d5(ctx):
    # D5 15:00: second supervisor edit (nw_renewal, mid-experiment)
    if ctx["minute"] is not None and ctx["minute"] >= 5 * 1440 + 900:
        return f"around the D5 15:00 supervisor edit ({label(ctx['minute'])})"


def trig_inflight_write(ctx):
    # (g) a governance write whose outcome is uncertain: SUBMITTING / APPLYING / AUTO_APPLYING row
    rows = ctx["db"].proposals_in(("SUBMITTING", "APPLYING", "AUTO_APPLYING"))
    if rows:
        return f"write in flight: {rows[0][0]} {rows[0][1]}"


def _open_states(snap) -> set:
    return {p["state"] for p in (snap.get("in_flight") or {}).get("open_proposals", [])}


SCHEDULE = [
    dict(label="a", aim="during history ingestion", arm=lambda c: True, fire=trig_history,
         fallback=fallback_elapsed(20), want=lambda s: not s.get("chunks"), attempts=1),
    dict(label="c", aim="while a proposal is PENDING", arm=armed_started, fire=trig_pending,
         fallback=fallback_after(1440 + 540), want=lambda s: "PENDING" in _open_states(s), attempts=1),
    dict(label="d", aim="approval APPROVED/APPLYING (approved, not yet applied)", arm=armed_started,
         fire=trig_approved, fallback=fallback_after(1440 + 600),
         want=lambda s: bool({"APPROVED", "APPLYING"} & _open_states(s)), attempts=3),
    dict(label="b", aim="mid-day while dialling", arm=armed_started, fire=trig_midday, fallback=None,
         want=None, attempts=1),
    dict(label="e", aim="around the D3 11:30 supervisor prompt incident (validation in flight)",
         arm=arm_from(3 * 1440 + 675), fire=trig_incident, fallback=fallback_after(3 * 1440 + 750),
         want=lambda s: bool((s.get("in_flight") or {}).get("credits_ledger_sent")), attempts=2),
    dict(label="f", aim="around the D5 15:00 supervisor edit", arm=armed_started, fire=trig_supervisor_d5,
         fallback=None, want=None, attempts=1),
    dict(label="g", aim="uncertain governance write in flight (SUBMITTING/APPLYING/AUTO_APPLYING)",
         arm=arm_from(6 * 1440), fire=trig_inflight_write, fallback=fallback_after(8 * 1440 + 720),
         want=lambda s: bool({"SUBMITTING", "APPLYING", "AUTO_APPLYING"} & _open_states(s)), attempts=4),
]


# ------------------------------------------------------------------------------------------ driver
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", default="scenarios/public_02_incidents.yaml")
    ap.add_argument("--run-dir", default="runs/crash_public_02")
    ap.add_argument("--baseline", default="runs/base_public_02_incidents")
    ap.add_argument("--db", default="state/crash_public_02.db")
    ap.add_argument("--port", type=int, default=8711)
    ap.add_argument("--timeline", default="reports/crash_recovery_timeline.json")
    ap.add_argument("--grade-out", default="reports/crash_public_02_grade.md")
    ap.add_argument("--ctl-log", default="runs/crash_public_02_ctl.log")
    ap.add_argument("--sim-log", default="runs/crash_public_02_sim.log")
    ap.add_argument("--history-dwell-s", type=float, default=1.0,
                    help="(a) kill this long after start-up reaches history ingestion")
    ap.add_argument("--poll-s", type=float, default=0.001)
    ap.add_argument("--timeout-s", type=float, default=1800)
    ap.add_argument("--skip-grade", action="store_true")
    a = ap.parse_args(argv)
    os.chdir(ROOT)
    os.environ["PYTHONUTF8"] = "1"
    py = sys.executable
    url = f"http://127.0.0.1:{a.port}"
    for p in (a.timeline, a.ctl_log, a.sim_log, a.db):
        Path(p).parent.mkdir(parents=True, exist_ok=True)

    if not (Path(a.baseline) / "_truth" / "aggregates.json").exists():
        print(f"[crash] baseline missing; building {a.baseline}", flush=True)
        subprocess.run([py, "-m", "sim", "baseline", "--scenario", a.scenario, "--run-dir", a.baseline], check=True)

    db_path = Path(a.db)
    for suf in ("", "-wal", "-shm"):
        q = Path(str(db_path) + suf)
        if q.exists():
            q.unlink()

    sim = Sim(url)
    if sim.healthy():
        print(f"[crash] something already answers on {url}; refusing to reuse it", flush=True)
        return 2
    sim_log = open(a.sim_log, "w", encoding="utf-8")
    sim_proc = subprocess.Popen([py, "-m", "sim", "serve", "--scenario", a.scenario, "--run-dir", a.run_dir,
                                 "--port", str(a.port), "--force"], stdout=sim_log, stderr=subprocess.STDOUT,
                                cwd=ROOT)
    timeline = {"scenario": a.scenario, "sim_url": url, "run_dir": a.run_dir, "db": a.db, "platform": sys.platform,
                "python": sys.version.split()[0], "kill_method": "subprocess.Popen.kill() (SIGKILL on POSIX,"
                " TerminateProcess on Windows)", "started": now_iso(), "launches": []}
    rc = 1
    ctl_log = open(a.ctl_log, "w", encoding="utf-8")
    proc = None
    watcher = SimWatcher(sim)
    try:
        t0 = time.time()
        while not sim.healthy():
            if sim_proc.poll() is not None:
                print("[crash] simulator died during start-up; see", a.sim_log, flush=True)
                return 2
            if time.time() - t0 > 900:
                print("[crash] simulator did not become healthy", flush=True)
                return 2
            time.sleep(0.5)
        print(f"[crash] simulator up on {url} after {time.time() - t0:.1f}s (pid {sim_proc.pid})", flush=True)
        watcher.start()

        env = dict(os.environ, PYTHONUTF8="1", OUTCOMELOOP_DB=a.db,
                   PYTHONPATH=str(ROOT / "src") + (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else ""))
        dbv = DBView(db_path)
        deadline = time.time() + a.timeout_s
        schedule = [dict(s, attempt=1) for s in SCHEDULE]
        launch_no = 0
        while True:
            launch_no += 1
            dbv.close()
            at_launch = dbv.snapshot()
            dbv.close()
            base_start = at_launch.get("max_decision_id", 0) if at_launch.get("db_exists") else 0
            st = sim.get("/sim/state")
            ctl_log.write(f"\n===== launch {launch_no} at {now_iso()} sim {label(st['sim_minute'])} =====\n")
            ctl_log.flush()
            proc = subprocess.Popen([py, "-m", "outcomeloop", "run", "--url", url], stdout=ctl_log,
                                    stderr=subprocess.STDOUT, env=env, cwd=ROOT)
            t_launch = time.time()
            entry = {"launch": launch_no, "pid": proc.pid, "started_wall": now_iso(), "started_epoch": t_launch,
                     "sim_minute_at_launch": st["sim_minute"], "sim_label_at_launch": label(st["sim_minute"]),
                     "db_at_launch": {k: at_launch.get(k) for k in ("db_exists", "chunks", "events_ingested", "calls",
                                                                    "decisions", "max_decision_id",
                                                                    "proposals_by_state")}}
            timeline["launches"].append(entry)
            print(f"[crash] launch {launch_no} pid {proc.pid} at sim {label(st['sim_minute'])}", flush=True)
            if not schedule:
                # final run: let it finish on its own
                rcode = proc.wait(timeout=max(60, deadline - time.time()))
                entry.update({"ended_wall": now_iso(), "ended_epoch": time.time(), "exit_code": rcode,
                              "outcome": "ran to completion"})
                dbv.close()
                entry["db_at_end"] = dbv.snapshot()
                dbv.close()
                print(f"[crash] final launch exited with code {rcode}", flush=True)
                break
            spec = schedule.pop(0)
            started = False
            ctx_state: dict = {}
            reason, how = None, None
            while reason is None:
                if proc.poll() is not None:
                    entry.update({"ended_wall": now_iso(), "exit_code": proc.returncode,
                                  "outcome": f"controller exited on its own before kill '{spec['label']}' fired"})
                    Path(a.timeline).write_text(json.dumps(timeline, indent=2, default=str), encoding="utf-8")
                    print(f"[crash] controller exited ({proc.returncode}) before kill {spec['label']}", flush=True)
                    raise SystemExit(3)
                if time.time() > deadline:
                    raise SystemExit("[crash] timeout")
                if not started:
                    started = dbv.max_start_decision() > base_start
                ctx = {"elapsed": time.time() - t_launch, "started": started, "minute": watcher.minute, "db": dbv,
                       "watcher": watcher, "args": a, "st": ctx_state}
                if spec["arm"](ctx):
                    reason = spec["fire"](ctx)
                    how = "targeted" if reason else None
                if reason is None and spec["fallback"] is not None:
                    reason = spec["fallback"](ctx)
                    how = "fallback" if reason else None
                if reason is None:
                    time.sleep(a.poll_s)
            minute_before = watcher.minute
            t_kill = time.time()
            proc.kill()                          # hard kill: SIGKILL / TerminateProcess
            proc.wait()
            watcher.want_approvals = False
            dbv.close()
            st_after = sim.get("/sim/state")
            snap = dbv.snapshot()
            dbv.close()
            landed = None if spec["want"] is None else bool(spec["want"](snap))
            entry.update({"ended_wall": now_iso(), "ended_epoch": t_kill, "exit_code": proc.returncode,
                          "outcome": "hard-killed",
                          "kill": {"label": spec["label"], "attempt": spec["attempt"], "aim": spec["aim"],
                                   "trigger": how, "reason": reason, "landed_on_target_state": landed,
                                   "elapsed_since_launch_s": round(t_kill - t_launch, 3),
                                   "startup_done_before_kill": started,
                                   "sim_minute_last_polled": minute_before, "sim_label_last_polled": label(minute_before),
                                   "sim_minute_after_kill": st_after["sim_minute"],
                                   "sim_label_after_kill": label(st_after["sim_minute"]),
                                   "sim_last_event_id": st_after["last_event_id"], "sim_chunks": st_after["chunks"],
                                   "sim_credits_remaining": st_after["credits_remaining"]},
                          "db_after_kill": snap})
            print(f"[crash] KILL {spec['label']}#{spec['attempt']} ({how}, landed={landed}) at sim"
                  f" {label(st_after['sim_minute'])}: {reason}", flush=True)
            print(f"        db: chunks={snap.get('chunks')} calls={snap.get('calls')} decisions={snap.get('decisions')}"
                  f" proposals={snap.get('proposals_by_state')} open={snap.get('in_flight', {}).get('open_proposals')}"
                  f" ledger_sent={snap.get('in_flight', {}).get('credits_ledger_sent')}", flush=True)
            if landed is False and how == "targeted" and spec["attempt"] < spec["attempts"]:
                schedule.insert(0, dict(spec, attempt=spec["attempt"] + 1))   # the state moved on: try again
            Path(a.timeline).write_text(json.dumps(timeline, indent=2, default=str), encoding="utf-8")

        st = sim.get("/sim/state")
        timeline["final_sim_state"] = st
        timeline["finished"] = now_iso()
        Path(a.timeline).write_text(json.dumps(timeline, indent=2, default=str), encoding="utf-8")

        # ---------------------------------------------------------------- verification (sim still up: API checks)
        sys.path.insert(0, str(ROOT / "scripts"))
        import verify_recovery
        vargs = ["--url", url, "--db", a.db, "--run-dir", a.run_dir, "--baseline", a.baseline,
                 "--timeline", a.timeline, "--grade-out", a.grade_out]
        if a.skip_grade:
            vargs.append("--skip-grade")
        rc = verify_recovery.main(vargs)
    finally:
        watcher.halt.set()
        if proc is not None and proc.poll() is None:     # only ever the controller WE started, by its handle
            proc.kill()
            proc.wait()
        if sim_proc.poll() is None:                       # and the simulator we started, by its handle
            sim_proc.terminate()
            try:
                sim_proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                sim_proc.kill()
                sim_proc.wait()
        sim_log.close()
        ctl_log.close()
        print(f"[crash] simulator (pid {sim_proc.pid}) stopped", flush=True)
    print(f"[crash] timeline: {a.timeline}   verification: {'PASS' if rc == 0 else 'FAIL'}", flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
