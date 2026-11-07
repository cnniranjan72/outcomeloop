"""Read-only views over our own store (C11 supervisor view, C12 audit, C14 loop health).

Everything here reads SQLite only — never the simulator — so it answers questions even when the
controller or the simulator is down.
"""
from __future__ import annotations

import json
import textwrap

from .db import DB
from .timeutil import label_to_minute, minute_to_label


def _wf(db: DB, workflow_id: str) -> int:
    r = db.q1("SELECT wf FROM workflows WHERE workflow_id=?", (workflow_id,))
    if not r:
        raise SystemExit(f"unknown workflow {workflow_id}")
    return r[0]


def _fmt_ev(s: str | None, width: int = 160) -> str:
    if not s:
        return ""
    return textwrap.shorten(s, width=width, placeholder=" …")


def why(db: DB, workflow_id: str, at: str) -> str:
    """Why did workflow X change at time T, who approved it, and what happened after?"""
    wf = _wf(db, workflow_id)
    t = label_to_minute(at)
    # the config version in force at T = latest version applied at or before T (+ one tick of slack)
    row = db.q1("SELECT version, actor, minute, changed_dims, proposal_id, approval_id FROM config_versions"
                " WHERE wf=? AND minute IS NOT NULL AND minute<=? ORDER BY minute DESC, version DESC LIMIT 1",
                (wf, t + 15))
    out = [f"# why: {workflow_id} at {minute_to_label(t)}", ""]
    if not row:
        out.append("No configuration change on record at or before that time (business default config in force).")
        return "\n".join(out)
    ver, actor, minute, dims, pid, aid = row
    out.append(f"Config v{ver} became live at {minute_to_label(minute)} — actor: {actor}, changed: {dims}")
    if actor == "supervisor":
        out.append("This was a client supervisor edit (bypasses governance). Our reaction:")
        for m, kind, summ in db.q("SELECT minute, kind, summary FROM decisions WHERE wf=? AND minute>=? AND minute<=?"
                                  " AND kind IN ('supervisor_edit','experiment_aborted','incident_opened',"
                                  "'validation_run','incident_fix_selected','proposal_submitted') ORDER BY decision_id",
                                  (wf, minute, minute + 360)):
            out.append(f"  {minute_to_label(m)}  {kind:24s} {summ}")
        return "\n".join(out)
    p = db.q1("SELECT proposal_id, route, kind, state, body, approval, created_minute FROM proposals WHERE proposal_id=?",
              (pid,)) if pid else None
    if p:
        body, appr = json.loads(p[4]), json.loads(p[5]) if p[5] else {}
        out += ["", f"## Proposal {p[0]} ({p[1]} route, {p[2]}), created {minute_to_label(p[6])}, state {p[3]}"]
        if p[1] == "approval":
            out.append(f"Approved by: client approver, approval {appr.get('approval_id')} "
                       f"(decided {appr.get('decided_at', '?')}, created {appr.get('created_at', '?')})")
            out.append(f"Summary: {body.get('change_summary')}")
            out.append(f"Impact score: {body.get('impact_score')} · affected leads: {body.get('affected_leads')}")
        else:
            out.append("Applied via policy-permitted auto-apply (no human approval required by this workflow's policy).")
        out.append(f"Rationale: {body.get('rationale')}")
        if body.get("diff") is not None:
            out.append("Diff: " + _fmt_ev(json.dumps(body.get("diff"), default=str), 600))
        else:   # auto route: the body carries the full proposed config and its evidence, not a diff
            cid = (body.get("evidence") or {}).get("caller_id") or {}
            if cid:
                out.append("Caller-ID health: " + ", ".join(
                    f"{d} {v.get('state')}" + (f" since {minute_to_label(v['since'])}" if v.get("state") != "healthy"
                                               and v.get("since") is not None else "") for d, v in sorted(cid.items())))
            dflt = ((body.get("proposed_config") or {}).get("allocations") or {}).get("default") or {}
            if dflt:
                out.append("Proposed default allocation: " + "; ".join(
                    f"{dim} " + ", ".join(f"{o} {w:.0%}" for o, w in sorted(alloc.items()))
                    for dim, alloc in dflt.items() if isinstance(alloc, dict)))
    out += ["", "## Decisions that led to it"]
    for m, kind, summ, reason in db.q(
            "SELECT minute, kind, summary, reasoning FROM decisions WHERE wf=? AND minute<=? AND minute>=? AND kind IN"
            " ('bootstrap','experiment_designed','experiment_winner','experiment_no_winner','experiment_drop_arm',"
            "'decay_detected','did_health','incident_opened','incident_fix_selected','validation_run','proposal_submitted',"
            "'proposal_approved','auto_apply','supervisor_edit') ORDER BY decision_id",
            (wf, minute, minute - 3 * 1440)):
        out.append(f"  {minute_to_label(m)}  {kind:24s} {summ}")
    out += ["", "## What happened next (48h)"]
    for m, kind, summ in db.q("SELECT minute, kind, summary FROM decisions WHERE wf=? AND minute>? AND minute<=? AND"
                              " kind NOT IN ('hold','approval_decided') ORDER BY decision_id",
                              (wf, minute, minute + 2880)):
        out.append(f"  {minute_to_label(m)}  {kind:24s} {_fmt_ev(summ, 140)}")
    k = db.q1("SELECT COUNT(*), SUM(conn), SUM(eng) FROM calls WHERE wf=? AND minute>=? AND minute<?", (wf, minute - 1440, minute))
    k2 = db.q1("SELECT COUNT(*), SUM(conn), SUM(eng) FROM calls WHERE wf=? AND minute>=? AND minute<?", (wf, minute, minute + 1440))
    if k[0] and k2[0]:
        out += ["", "KPIs 24h before → 24h after:",
                f"  pickup {k[1] / k[0]:.3f} → {k2[1] / k2[0]:.3f}   engagement {k[2] / max(k[1], 1):.3f} → "
                f"{k2[2] / max(k2[1], 1):.3f}   (dials {k[0]} → {k2[0]})"]
    return "\n".join(out)


def supervisor(db: DB, workflow_id: str) -> str:
    """One screen: what's being tested, what's winning, what we want from you, what changed today."""
    wf = _wf(db, workflow_id)
    now = db.q1("SELECT MAX(until_minute) FROM chunks")[0] or 0
    out = [f"# {workflow_id} — supervisor view at {minute_to_label(now)}", ""]
    cfg = db.q1("SELECT version, actor, config FROM config_versions WHERE wf=? AND config IS NOT NULL ORDER BY version DESC"
                " LIMIT 1", (wf,))
    if cfg:
        c = json.loads(cfg[2])
        fmt = lambda dist: " ".join(f"{o} {w:.0%}" for o, w in sorted(dist.items(), key=lambda kv: -kv[1]))
        out.append(f"Live config v{cfg[0]} (by {cfg[1]}): prompt {c['prompt_version']}")
        for d in ("welcome_message", "voice", "caller_id"):
            out.append(f"  {d:16s} {fmt(c['allocations']['default'][d])}"
                       + "".join(f" | {k}: {fmt(v[d])}" for k, v in c["allocations"].items() if k != "default" and d in v))
    k = db.q1("SELECT COUNT(*), SUM(conn), SUM(eng) FROM calls WHERE wf=? AND minute>=?", (wf, now - 1440))
    if k[0]:
        out.append(f"Last 24h: {k[0]} dials · pickup {k[1] / k[0]:.1%} · engagement {k[2] / max(k[1], 1):.1%}"
                   " (separate KPIs, never blended)")
    out += ["", "## Cohorts (shared definition used everywhere)"]
    for cid, w, st in db.q("SELECT cohort_id, where_json, status FROM cohorts WHERE wf=? AND status!='retired'"
                           " ORDER BY position", (wf,)):
        out.append(f"  {cid:14s} {w}  [{st}]")
    out += ["", "## Being tested / winning"]
    for (data,) in db.q("SELECT data FROM experiments WHERE wf=? ORDER BY created_minute", (wf,)):
        e = json.loads(data)
        last = e["looks"][-1] if e["looks"] else {}
        line = f"  {e['dim']:16s} {e['status']:12s} arms {e['arms']} incumbent {e['incumbent']}"
        if e.get("winner"):
            line += f" → winner {e['winner']}"
        if last.get("arms"):
            line += " | lifts " + ", ".join(f"{o} {v['lift_rel']:+.1%} (z {v['z']})" for o, v in last["arms"].items())
        out.append(line)
    out += ["", "## Waiting for you"]
    pend = db.q("SELECT proposal_id, state, body, created_minute FROM proposals WHERE wf=? AND state IN"
                " ('PENDING','APPROVED')", (wf,))
    for pid, st, body, cm in pend:
        b = json.loads(body)
        out.append(f"  {pid} [{st}] impact {b.get('impact_score')} · {b.get('affected_leads')} leads · {b.get('change_summary')}")
    if not pend:
        out.append("  nothing")
    out += ["", "## Changed today"]
    for m, actor, ver, dims in db.q("SELECT minute, actor, version, changed_dims FROM config_versions WHERE wf=? AND"
                                    " minute>=? ORDER BY version", (wf, now - now % 1440)):
        out.append(f"  {minute_to_label(m)} v{ver} by {actor}: {dims}")
    out += ["", "## Open incidents"]
    inc = db.q("SELECT incident_id, type, state, opened_minute FROM incidents WHERE wf=? AND state!='closed'", (wf,))
    out += [f"  {i} {t} {s} since {minute_to_label(m)}" for i, t, s, m in inc] or ["  none"]
    return "\n".join(out)


def status(db: DB) -> str:
    """Loop health for whoever is on call."""
    now = db.q1("SELECT MAX(until_minute) FROM chunks")[0] or 0
    def m(name):
        r = db.q1("SELECT value FROM metrics WHERE name=? ORDER BY id DESC LIMIT 1", (name,))
        return r[0] if r else None
    ev = db.q1("SELECT SUM(events), SUM(ingest_seconds) FROM chunks")
    days = db.q("SELECT labels, value FROM metrics WHERE name='wall_seconds_per_sim_day' ORDER BY id")
    out = [f"# OutcomeLoop status at {minute_to_label(now)}", "",
           f"events ingested: {ev[0] or 0:,} in {ev[1] or 0:.1f}s ({(ev[0] or 0) / max(ev[1] or 1e-9, 1e-9):,.0f} events/s while ingesting)",
           f"ingest lag: {_n(m('ingest_lag_minutes'))} sim-minutes · credits remaining: {_n(m('credits_remaining'))} · "
           f"open proposals: {_n(m('open_proposals'))} · peak RSS: {_n(m('rss_mb'))} MB",
           "wall seconds per sim day: " + ", ".join(f"{json.loads(l)['day']}:{v:.0f}s" for l, v in days)]
    alerts = db.q("SELECT minute, wf, kind, summary FROM decisions WHERE kind IN ('alert','error','incident_opened',"
                  "'decay_detected','proposal_lapsed','proposal_failed') ORDER BY decision_id DESC LIMIT 15")
    out += ["", "## Recent alerts / incidents"] + [f"  {minute_to_label(mm)} wf{w} {k}: {s}" for mm, w, k, s in alerts]
    out += ["", "## Proposals by state"] + [f"  {st}: {n}" for st, n in
                                            db.q("SELECT state, COUNT(*) FROM proposals GROUP BY state")]
    out += ["", "## Decisions by kind"] + [f"  {k}: {n}" for k, n in
                                           db.q("SELECT kind, COUNT(*) FROM decisions GROUP BY kind ORDER BY 2 DESC")]
    return "\n".join(out)


def decision(db: DB, decision_id: int, evidence_lines: int = 60) -> str:
    """One decision, fully: what, when, by whom, why (reasoning), on what evidence, every object it links to
    (proposal + approval, config version, experiment, incident), and the decisions just before and after it on the
    same workflow. Built for the live review question "explain this decision from your audit store"."""
    r = db.q1("SELECT d.decision_id, d.minute, d.wf, w.workflow_id, d.kind, d.actor, d.summary, d.reasoning, d.evidence,"
              " d.proposal_id, d.approval_id, d.config_version, d.experiment_id, d.incident_id FROM decisions d LEFT JOIN"
              " workflows w ON w.wf=d.wf WHERE d.decision_id=?", (decision_id,))
    if not r:
        return f"no decision #{decision_id}"
    did, m, wf, wid, kind, actor, summ, reason, ev, pid, aid, ver, eid, iid = r
    out = [f"# decision #{did} — {kind} · {minute_to_label(m)} · {wid or 'controller'} · by {actor}", "",
           f"What:  {summ}"]
    if reason:
        out.append(f"Why:   {reason}")
    links = []
    if pid:
        p = db.q1("SELECT route, kind, state, base_version, applied_version, approval_id, created_minute, notes FROM"
                  " proposals WHERE proposal_id=?", (pid,))
        if p:
            links.append(f"proposal {pid}: {p[0]} route, {p[1]}, state {p[2]}, base v{p[3]}"
                         + (f", applied as v{p[4]}" if p[4] is not None else "")
                         + (f", approval {p[5]}" if p[5] else "") + f", created {minute_to_label(p[6])}"
                         + (f" — {p[7]}" if p[7] else ""))
    if ver is not None and wf is not None:
        v = db.q1("SELECT actor, minute, changed_dims FROM config_versions WHERE wf=? AND version=?", (wf, ver))
        if v:
            links.append(f"config v{ver}: by {v[0]} at {minute_to_label(v[1])}, changed {v[2]}")
    if eid:
        e = db.q1("SELECT status, data FROM experiments WHERE experiment_id=?", (eid,))
        if e:
            d = json.loads(e[1])
            links.append(f"experiment {eid}: {d.get('dim')} {d.get('arms')}, status {e[0]}, winner {d.get('winner')}, "
                         f"alpha spent {d.get('alpha_spent', 0):.4f}")
    if iid:
        i = db.q1("SELECT type, state, opened_minute, closed_minute FROM incidents WHERE incident_id=?", (iid,))
        if i:
            links.append(f"incident {iid}: {i[0]}, {i[1]}, opened {minute_to_label(i[2])}"
                         + (f", closed {minute_to_label(i[3])}" if i[3] is not None else ""))
    if aid and not pid:
        links.append(f"approval {aid}")
    if links:
        out += ["", "Linked:"] + [f"  {x}" for x in links]
    if ev:
        try:
            pretty = json.dumps(json.loads(ev), indent=2, default=str).split("\n")
        except ValueError:
            pretty = [ev]
        out += ["", "Evidence:"] + ["  " + x for x in pretty[:evidence_lines]]
        if len(pretty) > evidence_lines:
            out.append(f"  … {len(pretty) - evidence_lines} more lines (python -m outcomeloop decision {did} --full)")
    if wf is not None:
        before = db.q("SELECT decision_id, minute, kind, summary FROM decisions WHERE wf=? AND decision_id<? AND"
                      " kind NOT IN ('hold','cohort_check') ORDER BY decision_id DESC LIMIT 5", (wf, did))
        after = db.q("SELECT decision_id, minute, kind, summary FROM decisions WHERE wf=? AND decision_id>? AND"
                     " kind NOT IN ('hold','cohort_check') ORDER BY decision_id LIMIT 8", (wf, did))
        fmt = lambda x: f"  #{x[0]:<5} {minute_to_label(x[1])}  {x[2]:24s} {_fmt_ev(x[3], 110)}"
        out += ["", "Before:"] + [fmt(x) for x in reversed(before)] + ["", "After:"] + [fmt(x) for x in after]
    return "\n".join(out)


def _n(v):
    """Metric for display: whole numbers without a trailing .0, others to one decimal; missing as '-'."""
    return "-" if v is None else (f"{v:,.0f}" if abs(v - round(v)) < 0.05 else f"{v:,.1f}")


def audit(db: DB, workflow_id: str | None, kind: str | None, limit: int) -> str:
    sql = "SELECT d.decision_id, d.minute, w.workflow_id, d.kind, d.actor, d.summary, d.proposal_id FROM decisions d LEFT JOIN" \
          " workflows w ON w.wf=d.wf WHERE 1=1"
    args = []
    if workflow_id:
        sql += " AND w.workflow_id=?"
        args.append(workflow_id)
    if kind:   # exact kind, or a prefix with a trailing * (e.g. experiment_*)
        sql += " AND d.kind LIKE ? ESCAPE '!'" if kind.endswith("*") else " AND d.kind=?"
        args.append(kind[:-1].replace("!", "!!").replace("_", "!_").replace("%", "!%") + "%" if kind.endswith("*") else kind)
    sql += " ORDER BY d.decision_id DESC LIMIT ?"
    args.append(limit)
    rows = db.q(sql, args)
    return "\n".join(f"#{i:<5} {minute_to_label(m)}  {w or '-':12s} {k:24s} {a:10s} {_fmt_ev(s, 130)}"
                     for i, m, w, k, a, s, p in reversed(rows))


def customer(db: DB, person_id: str, day: int | None) -> str:
    """IRDAI question: why did this customer hear what they heard on a given day?"""
    wid, p = person_id.rsplit(":p", 1)
    wf = _wf(db, wid)
    args = [wf, int(p)]
    sql = "SELECT minute, cfg_ver, cohort, wm, voice, did, prompt, conn, eng FROM calls WHERE wf=? AND person=?"
    if day is not None:
        sql += " AND minute>=? AND minute<?"
        args += [day * 1440, (day + 1) * 1440]
    out = [f"# calls to {person_id}" + (f" on D{day}" if day is not None else ""),
           "  time      cohort     variant (welcome voice prompt) from caller ID  outcome    config version and who set it"]
    for m, ver, coh, wm, vo, did, pr, conn, eng in db.q(sql + " ORDER BY minute", args):
        v = db.q1("SELECT actor, proposal_id, approval_id FROM config_versions WHERE wf=? AND version=?", (wf, ver))
        outcome = "engaged" if eng else ("connected" if conn else "no answer")
        if not v:
            who = "business default"
        elif v[0] == "supervisor":
            who = "by supervisor (direct edit, outside governance)"
        elif v[0] == "controller_approved":
            who = f"by controller_approved · {v[1]} · {v[2]}"
        elif v[0] == "controller_auto":
            who = f"by controller_auto · {v[1]} · auto route (policy)"
        else:
            who = f"by {v[0]}"
        out.append(f"{minute_to_label(m)}  {db.decode('cohort', coh)}  variant {db.decode('welcome_message', wm)}"
                   f" {db.decode('voice', vo)} {db.decode('prompt_version', pr)} from {db.decode('caller_id', did)}"
                   f"  {outcome:<9}  config v{ver} {who}")
    out.append("Run `why <workflow> --at <time>` on any config version above for the reasoning and approver.")
    return "\n".join(out)


# ------------------------------------------------------------------------------------------ paging rules (C14)
def alerts(db: DB) -> tuple[str, list[dict]]:
    """Evaluate the paging rules from SUBMISSION.md §10 against the store. Returns (text, firing alerts).
    Only conditions that need a human now page; everything else belongs in the supervisor view."""
    now = db.q1("SELECT MAX(until_minute) FROM chunks")[0] or 0
    last_wall = db.q1("SELECT MAX(wall) FROM metrics")[0] or 0
    fire: list[dict] = []

    def page(rule, msg, look):
        fire.append({"rule": rule, "message": msg, "look_at": look})

    # 1. the loop is blind: no new chunk for more than 2 ticks while the simulator clock moved
    lag = db.q1("SELECT value FROM metrics WHERE name='ingest_lag_minutes' ORDER BY id DESC LIMIT 1")
    hour = (now % 1440) // 60
    if lag and lag[0] > 30 and 9 <= hour < 21:   # at night no calls are made, so no chunks is normal
        page("ingest_stalled", f"no events ingested for {lag[0]:.0f} sim-minutes during dialling hours",
             "python -m outcomeloop status; controller log; GET /events/chunks")
    # 2. crash loop / error storm
    errs = db.q1("SELECT COUNT(*) FROM decisions WHERE kind='error' AND minute > ?", (now - 60,))[0]
    if errs > 5:
        page("error_rate", f"{errs} isolated decision errors in the last sim-hour",
             "python -m outcomeloop audit --kind error")
    # a workflow failing every hour is stuck even if the rate is low (isolation keeps the process alive, so a
    # persistent error is otherwise silent)
    for wf, n in db.q("SELECT wf, COUNT(*) FROM decisions WHERE kind='error' AND minute > ? GROUP BY wf", (now - 180,)):
        if n >= 3:
            page("workflow_stuck", f"workflow {wf}: {n} decision errors in the last 3 sim-hours",
                 f"python -m outcomeloop audit --kind error  (wf {wf})")
    restarts = db.q1("SELECT COUNT(*) FROM decisions WHERE kind='controller_restart' AND wall > ?",
                     (last_wall - 3600,))[0]
    if restarts > 3:
        page("crash_loop", f"{restarts} controller restarts in the last wall-clock hour",
             "controller log around each restart; python -m outcomeloop audit --kind controller_restart")
    # 3. credits near the incident reserve
    start = db.kv_get("credits_start")
    cr = db.q1("SELECT value FROM metrics WHERE name='credits_remaining' ORDER BY id DESC LIMIT 1")
    if start and cr and cr[0] <= start * 0.40 * 1.10:
        page("credits_low", f"{cr[0]:.0f} credits left of {start:.0f}; incident reserve is {start * 0.4:.0f}",
             "python -m outcomeloop audit --kind validation_run")
    # 4. approved but not applied for > 60 min (apply window is 2 h)
    for pid, wf, upd in db.q("SELECT proposal_id, wf, updated_minute FROM proposals WHERE state='APPROVED'"):
        if now - upd > 60:
            page("approval_not_applied", f"{pid} approved {now - upd} sim-minutes ago and not applied",
                 f"python -m outcomeloop audit --wf <wf {wf}>; GET /approvals/<id>")
    # 5. incident open > 4 h without a fix proposal
    for iid, wf, opened, state in db.q("SELECT incident_id, wf, opened_minute, state FROM incidents"
                                        " WHERE state IN ('open','fix_ready')"):
        if now - opened > 240:
            page("incident_stuck", f"{iid} open for {now - opened} sim-minutes in state {state}",
                 f"python -m outcomeloop audit --kind incident_no_fix; credits; approver hours")
    out = [f"# paging rules at {minute_to_label(now)}: {len(fire)} firing"]
    out += [f"PAGE {a['rule']}: {a['message']}  → look at: {a['look_at']}" for a in fire] or ["all clear"]
    return "\n".join(out), fire


# ------------------------------------------------------------------------------------------ read-only HTTP (C11)
def serve(db_path: str, port: int):
    """Tiny read-only HTTP front for the same views: /status, /alerts, /supervisor/<wf>, /why/<wf>?at=D3%2014:00,
    /customer/<person_id>. Standard library only; opens the store read-only per request."""
    import sqlite3
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import parse_qs, unquote, urlparse

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            u = urlparse(self.path)
            parts = [unquote(p) for p in u.path.strip("/").split("/") if p]
            q = parse_qs(u.query)
            db = DB.__new__(DB)
            db.conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            db._codes, db._rev, db._in_tx = {}, {}, False
            for kind, value, code in db.conn.execute("SELECT kind, value, code FROM codes"):
                db._codes[(kind, value)] = code
                db._rev[(kind, code)] = value
            try:
                if parts == ["status"]:
                    body = status(db)
                elif parts == ["alerts"]:
                    body = alerts(db)[0]
                elif len(parts) == 2 and parts[0] == "supervisor":
                    body = supervisor(db, parts[1])
                elif len(parts) == 2 and parts[0] == "why":
                    body = why(db, parts[1], q.get("at", ["D0 00:00"])[0])
                elif len(parts) == 2 and parts[0] == "decision" and parts[1].isdigit():
                    body = decision(db, int(parts[1]), 10_000 if "full" in q else 60)
                elif len(parts) == 2 and parts[0] == "customer":
                    body = customer(db, parts[1], int(q["day"][0]) if "day" in q else None)
                else:
                    body, code = "routes: /status /alerts /supervisor/<wf> /why/<wf>?at=D3%2014:00 /decision/<id> /customer/<person>", 404
                    self._send(code, body)
                    return
                self._send(200, body)
            except SystemExit as e:
                self._send(404, str(e))
            finally:
                db.conn.close()

        def _send(self, code, body):
            b = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def log_message(self, *a):
            pass

    print(f"OutcomeLoop views (read-only) on http://127.0.0.1:{port}/status")
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
