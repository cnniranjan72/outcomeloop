"""Verify that a run that was hard-killed and restarted (scripts/crash_recovery.py) finished correctly.

    python scripts/verify_recovery.py --url http://127.0.0.1:8711 --db state/crash_public_02.db \
        --run-dir runs/crash_public_02 --baseline runs/base_public_02_incidents \
        --timeline reports/crash_recovery_timeline.json

Needs the simulator still running (it cross-checks our store against the simulator's API: config history,
approvals, chunk list, state). As a test harness it may also read the simulator's run dir (event files,
sim_log.jsonl) — the controller never does. Exits non-zero if any check fails. Results are printed and, when
--timeline is given, appended to the timeline JSON under "verification".
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sqlite3
import subprocess
import sys
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ACTIVE_EXP = ("designed", "running", "promoting", "promoted", "rolling_back", "concluding")
# remote approval status -> states our store may legitimately hold for it at the end of the run
ALLOWED = {
    "pending": {"PENDING"},
    "approved": {"APPROVED", "STALE"},   # STALE: base changed under it (supervisor edit), we refused to force it
    "rejected": {"REJECTED"},
    "expired": {"EXPIRED"},
    "applied": {"APPLIED"},
    "lapsed": {"LAPSED"},
}


class Checks:
    def __init__(self):
        self.items: list[dict] = []

    def add(self, name: str, ok: bool | None, detail, **numbers):
        status = "INFO" if ok is None else ("PASS" if ok else "FAIL")
        self.items.append({"check": name, "status": status, "detail": detail, **numbers})
        print(f"[{status}] {name}: {detail}" + (f"  {numbers}" if numbers else ""), flush=True)

    @property
    def failed(self) -> list[dict]:
        return [i for i in self.items if i["status"] == "FAIL"]


def get(url: str, path: str):
    with urllib.request.urlopen(url.rstrip("/") + path, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8711")
    ap.add_argument("--db", default="state/crash_public_02.db")
    ap.add_argument("--run-dir", default="runs/crash_public_02")
    ap.add_argument("--baseline", default="runs/base_public_02_incidents")
    ap.add_argument("--timeline", default="reports/crash_recovery_timeline.json")
    ap.add_argument("--grade-out", default="reports/crash_public_02_grade.md")
    ap.add_argument("--skip-grade", action="store_true")
    a = ap.parse_args(argv)
    os.chdir(ROOT)
    C = Checks()
    db = sqlite3.connect(f"file:{Path(a.db).as_posix()}?mode=ro", uri=True)
    q = lambda sql, args=(): db.execute(sql, args).fetchall()          # noqa: E731
    q1 = lambda sql, args=(): db.execute(sql, args).fetchone()[0]      # noqa: E731
    tl = json.loads(Path(a.timeline).read_text(encoding="utf-8")) if a.timeline and Path(a.timeline).exists() else None

    st = get(a.url, "/sim/state")
    wfs = {w["workflow_id"]: w for w in get(a.url, "/workflows")}
    wf_code = {wid: code for code, wid in q("SELECT wf, workflow_id FROM workflows")}
    approvals = get(a.url, "/approvals")
    history = {wid: get(a.url, f"/workflows/{wid}/config/history") for wid in wfs}
    props = {r[0]: dict(zip(("proposal_id", "wf", "route", "state", "kind", "base_version", "approval_id",
                             "applied_version"), r))
             for r in q("SELECT proposal_id, wf, route, state, kind, base_version, approval_id, applied_version"
                        " FROM proposals")}
    sim_log = [json.loads(l) for l in open(Path(a.run_dir) / "sim_log.jsonl", encoding="utf-8") if l.strip()]

    # ============================================================== 1. no double apply
    dup_pid, dup_aid, ctrl_versions = [], [], 0
    for wid, h in history.items():
        ctrl = [v for v in h if str(v["actor"]).startswith("controller")]
        ctrl_versions += len(ctrl)
        cp = Counter(v["proposal_id"] for v in ctrl if v.get("proposal_id"))
        ca = Counter(v["approval_id"] for v in ctrl if v.get("approval_id"))
        dup_pid += [(wid, p, n) for p, n in cp.items() if n > 1]
        dup_aid += [(wid, x, n) for x, n in ca.items() if n > 1]
    C.add("config history: each proposal_id/approval_id applied at most once", not dup_pid and not dup_aid,
          "no duplicates" if not dup_pid and not dup_aid else f"duplicates: {dup_pid + dup_aid}",
          controller_versions=ctrl_versions)

    applied = [ap for ap in approvals if ap["status"] == "applied"]
    hist_by_aid = Counter(v["approval_id"] for h in history.values() for v in h if v.get("approval_id"))
    bad = [ap["approval_id"] for ap in applied if hist_by_aid.get(ap["approval_id"]) != 1]
    log_applied = Counter(r["approval_id"] for r in sim_log if r["kind"] == "approval_applied")
    log_auto = Counter(r["proposal_id"] for r in sim_log if r["kind"] == "auto_applied")
    bad_log = [k for k, n in list(log_applied.items()) + list(log_auto.items()) if n > 1]
    C.add("every 'applied' approval applied exactly once (config history + sim_log)", not bad and not bad_log
          and len(log_applied) == len(applied),
          f"{len(applied)} applied approvals, each exactly one config version; sim_log approval_applied="
          f"{sum(log_applied.values())}, auto_applied={sum(log_auto.values())}" if not bad and not bad_log else
          f"mismatch: history {bad}, sim_log {bad_log}",
          applied_approvals=len(applied), sim_log_approval_applied=sum(log_applied.values()),
          sim_log_auto_applied=sum(log_auto.values()))

    # our APPLIED rows <-> controller versions, 1:1, with the same version number
    ver_by_pid = {(wid, v["proposal_id"]): v["version"] for wid, h in history.items() for v in h if v.get("proposal_id")}
    ours_applied = [p for p in props.values() if p["state"] == "APPLIED"]
    wid_of = {code: wid for wid, code in wf_code.items()}
    mism = [(p["proposal_id"], p["applied_version"], ver_by_pid.get((wid_of[p["wf"]], p["proposal_id"])))
            for p in ours_applied if ver_by_pid.get((wid_of[p["wf"]], p["proposal_id"])) != p["applied_version"]]
    missing = [pid for (wid, pid) in ver_by_pid if pid.startswith("ol-") and pid not in props]
    C.add("our APPLIED proposals == controller config versions (1:1, same version)",
          not mism and not missing and len(ours_applied) == ctrl_versions,
          f"{len(ours_applied)} APPLIED rows vs {ctrl_versions} controller versions" +
          (f"; version mismatches {mism}" if mism else "") + (f"; unknown to us {missing}" if missing else ""),
          our_applied=len(ours_applied), controller_versions=ctrl_versions)

    # ============================================================== 2. no lost approvals
    lost, wrong = [], []
    for ap in approvals:
        if not ap["proposal_id"].startswith("ol-"):
            continue
        p = props.get(ap["proposal_id"])
        if p is None or p["approval_id"] != ap["approval_id"]:
            lost.append(ap["approval_id"])
        elif p["state"] not in ALLOWED[ap["status"]]:
            wrong.append((ap["approval_id"], ap["status"], p["state"]))
    by_status = Counter(ap["status"] for ap in approvals)
    C.add("every simulator approval is in our store with a consistent state", not lost and not wrong,
          f"{len(approvals)} approvals {dict(by_status)}; lost={lost}; inconsistent={wrong}",
          approvals=len(approvals))
    remote_pids = {ap["proposal_id"] for ap in approvals}
    ghost = [p["proposal_id"] for p in props.values() if p["route"] == "approval" and p["approval_id"]
             and p["proposal_id"] not in remote_pids]
    failed_but_remote = [p["proposal_id"] for p in props.values() if p["state"] == "SUBMIT_FAILED"
                         and p["proposal_id"] in remote_pids]
    C.add("no phantom approvals (ours with approval_id unknown remotely; SUBMIT_FAILED that actually landed)",
          not ghost and not failed_but_remote, f"ghost={ghost}; submit_failed_but_landed={failed_but_remote}")
    uncertain = [(p["proposal_id"], p["state"]) for p in props.values()
                 if p["state"] in ("SUBMITTING", "APPLYING", "AUTO_APPLYING")]
    C.add("no proposal left in an uncertain state at the end", not uncertain, f"{uncertain or 'none'}")
    pending_end = [(p["proposal_id"], p["approval_id"]) for p in props.values() if p["state"] == "PENDING"]
    C.add("proposals by state (ours)", None, dict(Counter(p["state"] for p in props.values())),
          pending_at_end=len(pending_end))

    # ============================================================== 3. exactly-once ingestion
    remote_chunks = get(a.url, "/events/chunks?kind=history&after=-1") + get(a.url, "/events/chunks?kind=events&after=-1")
    rc = {c["chunk"]: c for c in remote_chunks}
    ours = q("SELECT chunk, events, first_event_id, last_event_id FROM chunks ORDER BY chunk")
    dupc = q("SELECT chunk, COUNT(*) FROM chunks GROUP BY chunk HAVING COUNT(*)>1")
    nums = [r[0] for r in ours]
    per_chunk_bad = [r[0] for r in ours if r[0] not in rc or rc[r[0]]["events"] != r[1]
                     or rc[r[0]]["last_event_id"] != r[3]]
    C.add("chunks: each chunk number exactly once, all simulator chunks ingested, per-chunk event counts match",
          not dupc and nums == sorted(rc) and not per_chunk_bad and len(nums) == st["chunks"],
          f"ours {len(nums)} chunks (0..{max(nums) if nums else None}), simulator {st['chunks']}; dup={dupc};"
          f" per-chunk mismatches={per_chunk_bad}", our_chunks=len(nums), sim_chunks=st["chunks"])
    ev_sum = q1("SELECT SUM(events) FROM chunks") or 0
    C.add("SUM(chunks.events) == simulator last_event_id", ev_sum == st["last_event_id"],
          f"{ev_sum} vs {st['last_event_id']}", our_events=ev_sum, sim_last_event_id=st["last_event_id"])
    n_call_events, n_lines = 0, 0
    for f in sorted(glob.glob(str(Path(a.run_dir) / "history" / "*.jsonl")) +
                    glob.glob(str(Path(a.run_dir) / "events" / "*.jsonl"))):
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    n_lines += 1
                    if '"type":"call"' in line:
                        n_call_events += 1
    n_calls = q1("SELECT COUNT(*) FROM calls")
    n_calls_distinct = q1("SELECT COUNT(DISTINCT event_id) FROM calls")
    C.add("calls table rows == call events in the simulator's event files (no loss, no duplicates)",
          n_calls == n_call_events == n_calls_distinct,
          f"calls rows {n_calls} (distinct event_id {n_calls_distinct}) vs call events {n_call_events}"
          f" in {n_lines} event lines", calls_rows=n_calls, call_events=n_call_events)

    # ============================================================== 4. decisions / learning kept
    dec = q("SELECT decision_id, wall, kind, proposal_id, experiment_id, incident_id, minute, summary FROM decisions"
            " ORDER BY decision_id")
    ids = [d[0] for d in dec]
    walls = [d[1] for d in dec]
    inc_ids = all(b > a_ for a_, b in zip(ids, ids[1:]))
    back = sum(1 for a_, b in zip(walls, walls[1:]) if b < a_ - 1e-3)
    trig = {r[0] for r in q("SELECT name FROM sqlite_master WHERE type='trigger'")}
    C.add("decisions: ids strictly increasing, wall clock monotone in id order, append-only triggers present",
          inc_ids and back == 0 and {"decisions_append_only_u", "decisions_append_only_d"} <= trig,
          f"{len(ids)} decisions, ids {ids[0] if ids else None}..{ids[-1] if ids else None}, wall regressions={back}",
          decisions=len(ids))
    kinds = Counter(d[2] for d in dec)
    restart_rows = [(d[0], d[1], d[2], d[7]) for d in dec if d[2] in ("controller_start", "controller_restart")]
    recon_rows = [(d[0], d[1], d[3], d[7]) for d in dec if d[2] == "recovery_reconcile"]
    if tl:
        problems, per_launch = [], []
        for i, L in enumerate(tl["launches"]):
            lo = L["started_epoch"]
            hi = tl["launches"][i + 1]["started_epoch"] if i + 1 < len(tl["launches"]) else float("inf")
            mine = [r for r in restart_rows if lo <= r[1] < hi]
            expect = "controller_restart" if (L["db_at_launch"].get("chunks") or 0) > 0 else "controller_start"
            reached = (L.get("kill") or {}).get("startup_done_before_kill", True)
            recs = [r for r in recon_rows if lo <= r[1] < hi]
            per_launch.append({"launch": L["launch"], "expected": expect if reached else "(killed during start-up)",
                               "got": [r[2] for r in mine], "recovery_reconcile": [r[3] for r in recs]})
            if reached and [r[2] for r in mine] != [expect]:
                problems.append((L["launch"], expect, [r[2] for r in mine]))
            if not reached and len(mine) > 1:
                problems.append((L["launch"], "<=1", [r[2] for r in mine]))
            # every write that was uncertain at a kill must be reconciled by the next launch
            if i > 0:
                prev = tl["launches"][i - 1].get("db_after_kill") or {}
                need = [p["proposal_id"] for p in (prev.get("in_flight") or {}).get("open_proposals", [])
                        if p["state"] in ("SUBMITTING", "APPLYING", "AUTO_APPLYING")]
                got = {r[2] for r in recs}
                for pid in need:
                    if pid not in got:
                        problems.append((L["launch"], f"recovery_reconcile for {pid}", "missing"))
        C.add("one controller_start/controller_restart decision per launch; uncertain writes reconciled after restart",
              not problems, f"{per_launch}" + (f"; problems {problems}" if problems else ""),
              restarts=kinds.get("controller_restart", 0), starts=kinds.get("controller_start", 0),
              recovery_reconcile=kinds.get("recovery_reconcile", 0))
    C.add("exactly one controller_finish decision", kinds.get("controller_finish", 0) == 1,
          f"{kinds.get('controller_finish', 0)}")

    n_wf = len(wfs)
    C.add("bootstrap from history ran once per workflow (not repeated after restarts)", kinds.get("bootstrap", 0) == n_wf,
          f"{kinds.get('bootstrap', 0)} bootstrap decisions for {n_wf} workflows")
    exps = q("SELECT experiment_id, wf, dim, status, created_minute, updated_minute FROM experiments ORDER BY created_minute")
    designed = kinds.get("experiment_designed", 0)
    by_key = defaultdict(list)
    for e in exps:
        by_key[(e[1], e[2])].append(e)
    overlap = [k for k, es in by_key.items() if sum(1 for e in es if e[3] in ACTIVE_EXP) > 1
               or any(e[3] in ACTIVE_EXP for e in es[:-1])]
    C.add("experiments: no duplicates (one design decision per experiment, <=1 active per workflow x dimension)",
          designed == len(exps) and not overlap, f"{len(exps)} experiments, {designed} experiment_designed decisions;"
          f" overlapping actives {overlap}", experiments=len(exps))
    if tl:
        spans = {}
        bounds = [(L["started_epoch"], (tl["launches"][i + 1]["started_epoch"] if i + 1 < len(tl["launches"])
                                        else float("inf"))) for i, L in enumerate(tl["launches"])]
        for d in dec:
            if d[4]:
                li = next((i + 1 for i, (lo, hi) in enumerate(bounds) if lo <= d[1] < hi), None)
                spans.setdefault(d[4], set()).add(li)
        multi = {k: sorted(v) for k, v in spans.items() if len(v) > 1}
        # experiments that were active at a kill must still be the same experiment afterwards (not re-created)
        carried, recreated = [], []
        for L in tl["launches"]:
            for e in ((L.get("db_after_kill") or {}).get("in_flight") or {}).get("active_experiments", []):
                carried.append(e["experiment_id"])
        exp_ids = {e[0] for e in exps}
        lost_exp = [x for x in set(carried) if x not in exp_ids]
        C.add("learning kept: experiments active at a kill continue under the same id after restart",
              not lost_exp, f"{len(set(carried))} experiments were active at some kill, all still present;"
              f" {len(multi)} experiments have decisions in more than one controller launch: {multi}",
              experiments_spanning_launches=len(multi))
    incs = q("SELECT incident_id, wf, state, opened_minute, closed_minute FROM incidents ORDER BY opened_minute")
    open_by_wf = Counter(i[1] for i in incs if i[2] != "closed")
    C.add("incidents: no duplicates (one incident_opened decision per incident, <=1 open per workflow)",
          kinds.get("incident_opened", 0) == len(incs) and all(v <= 1 for v in open_by_wf.values()),
          f"{len(incs)} incidents {[(i[0], i[2]) for i in incs]}; incident_opened decisions={kinds.get('incident_opened', 0)}")
    first = q("SELECT evidence FROM decisions WHERE kind='controller_start' ORDER BY decision_id LIMIT 1")
    credits0 = json.loads(first[0][0]).get("credits") if first and first[0][0] else None
    used = None if credits0 is None else round(float(credits0) - st["credits_remaining"], 2)
    led = dict(q("SELECT state, SUM(cost) FROM credits_ledger GROUP BY state"))
    done, sent = led.get("done", 0) or 0, led.get("sent", 0) or 0
    C.add("credits: simulator spend accounted for by our ledger (done <= spent <= done + sent-with-unknown-outcome)",
          None if used is None else (done - 1e-6 <= used <= done + sent + 1e-6),
          f"simulator credits used {used} (start {credits0}, remaining {st['credits_remaining']}); our ledger cost"
          f" by state {led}", credits_used=used)

    # ============================================================== 5. finished + grade
    final = tl["launches"][-1] if tl else {}
    C.add("simulator finished and the final controller launch exited 0",
          bool(st["finished"]) and (not tl or final.get("exit_code") == 0),
          f"finished={st['finished']} at minute {st['sim_minute']}; final exit code {final.get('exit_code')}")
    grade_table = None
    if not a.skip_grade:
        p = subprocess.run([sys.executable, "-m", "sim", "grade", "--run", a.run_dir, "--baseline", a.baseline,
                            "--out", a.grade_out], capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
        ok = p.returncode == 0 and Path(a.grade_out).exists()
        if ok:
            lines = Path(a.grade_out).read_text(encoding="utf-8").splitlines()
            i = next((k for k, l in enumerate(lines) if l.startswith("| workflow")), None)
            if i is not None:
                grade_table = "\n".join(l for l in lines[i:i + 8] if l.startswith("|"))
        C.add("sim grade succeeds", ok, f"rc={p.returncode} -> {a.grade_out}" + ("" if ok else f" {p.stderr[-500:]}"))
        if grade_table:
            print(grade_table)

    n_fail = len(C.failed)
    print(f"\nverification: {len(C.items)} checks, {n_fail} failed -> {'PASS' if not n_fail else 'FAIL'}", flush=True)
    if tl is not None:
        tl["verification"] = {"result": "PASS" if not n_fail else "FAIL", "checks": C.items,
                              "decision_kinds": dict(kinds), "restart_decisions": restart_rows,
                              "recovery_reconcile_decisions": recon_rows, "grade_table": grade_table}
        Path(a.timeline).write_text(json.dumps(tl, indent=2, default=str), encoding="utf-8")
    db.close()
    return 0 if not n_fail else 1


if __name__ == "__main__":
    sys.exit(main())
