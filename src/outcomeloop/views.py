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
        out.append("Diff: " + _fmt_ev(json.dumps(body.get("diff"), default=str), 600))
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
        out.append(f"Live config v{cfg[0]} (by {cfg[1]}): prompt {c['prompt_version']}, default "
                   + ", ".join(f"{d}={c['allocations']['default'][d]}" for d in ("welcome_message", "voice", "caller_id")))
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
           f"events ingested: {ev[0]} in {ev[1] or 0:.1f}s ({(ev[0] or 0) / max(ev[1] or 1e-9, 1e-9):,.0f} events/s while ingesting)",
           f"ingest lag: {m('ingest_lag_minutes')} sim-minutes · credits remaining: {m('credits_remaining')} · "
           f"open proposals: {m('open_proposals')} · peak RSS: {m('rss_mb')} MB",
           "wall seconds per sim day: " + ", ".join(f"{json.loads(l)['day']}:{v:.0f}s" for l, v in days)]
    alerts = db.q("SELECT minute, wf, kind, summary FROM decisions WHERE kind IN ('alert','error','incident_opened',"
                  "'decay_detected','proposal_lapsed','proposal_failed') ORDER BY decision_id DESC LIMIT 15")
    out += ["", "## Recent alerts / incidents"] + [f"  {minute_to_label(mm)} wf{w} {k}: {s}" for mm, w, k, s in alerts]
    out += ["", "## Proposals by state"] + [f"  {st}: {n}" for st, n in
                                            db.q("SELECT state, COUNT(*) FROM proposals GROUP BY state")]
    out += ["", "## Decisions by kind"] + [f"  {k}: {n}" for k, n in
                                           db.q("SELECT kind, COUNT(*) FROM decisions GROUP BY kind ORDER BY 2 DESC")]
    return "\n".join(out)


def audit(db: DB, workflow_id: str | None, kind: str | None, limit: int) -> str:
    sql = "SELECT d.minute, w.workflow_id, d.kind, d.actor, d.summary, d.proposal_id FROM decisions d LEFT JOIN" \
          " workflows w ON w.wf=d.wf WHERE 1=1"
    args = []
    if workflow_id:
        sql += " AND w.workflow_id=?"
        args.append(workflow_id)
    if kind:
        sql += " AND d.kind=?"
        args.append(kind)
    sql += " ORDER BY d.decision_id DESC LIMIT ?"
    args.append(limit)
    rows = db.q(sql, args)
    return "\n".join(f"{minute_to_label(m)}  {w or '-':12s} {k:24s} {a:10s} {_fmt_ev(s, 130)}"
                     for m, w, k, a, s, p in reversed(rows))


def customer(db: DB, person_id: str, day: int | None) -> str:
    """IRDAI question: why did this customer hear what they heard on a given day?"""
    wid, p = person_id.rsplit(":p", 1)
    wf = _wf(db, wid)
    args = [wf, int(p)]
    sql = "SELECT minute, cfg_ver, cohort, wm, voice, did, prompt, conn, eng FROM calls WHERE wf=? AND person=?"
    if day is not None:
        sql += " AND minute>=? AND minute<?"
        args += [day * 1440, (day + 1) * 1440]
    out = [f"# calls to {person_id}" + (f" on D{day}" if day is not None else "")]
    for m, ver, coh, wm, vo, did, pr, conn, eng in db.q(sql + " ORDER BY minute", args):
        v = db.q1("SELECT actor, proposal_id, approval_id FROM config_versions WHERE wf=? AND version=?", (wf, ver))
        out.append(f"{minute_to_label(m)} cohort={db.decode('cohort', coh)} heard welcome={db.decode('welcome_message', wm)}"
                   f" voice={db.decode('voice', vo)} prompt={db.decode('prompt_version', pr)} from {db.decode('caller_id', did)}"
                   f" | connected={bool(conn)} engaged={bool(eng)} | config v{ver}"
                   + (f" set by {v[0]} (proposal {v[1]}, approval {v[2]})" if v else " (business default)"))
    out.append("Run `why <workflow> --at <time>` on any config version above for the reasoning and approver.")
    return "\n".join(out)
