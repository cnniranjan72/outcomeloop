"""Independent verification of the audit store (read-only).

* `verify_store(db)` — integrity checks over the persisted records. Each check is VALID, INVALID, INCOMPLETE (the
  run was interrupted or records are missing) or NOT_VERIFIABLE (the evidence needed is not retained), with the
  offending records. A clean result means every check ran and passed, not that nothing raised.
* `replay(db, decision_id)` — reconstructs one decision as of its own timestamp from persisted evidence and, where
  the raw rows allow it, *recomputes* its statistics independently of the stored summary (experiment looks from the
  raw `calls` rows, not the rollups the controller used; validation results against the credits ledger;
  applications against config versions). Never writes, never calls the simulator or the LLM.

Hash chain: not added. The decisions table is append-only by triggers; a hash chain only helps against someone who
can also drop triggers, and then they can rewrite the chain too unless the head is anchored outside the store —
infrastructure this deployment does not have. The cross-record checks below catch the realistic failures (lost,
duplicated or orphaned records, invalid transitions).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from .db import DB
from .stats import Prop, compare, phi
from .timeutil import minute_to_label

VALID, INVALID, INCOMPLETE, NOT_VERIFIABLE = "VALID", "INVALID", "INCOMPLETE", "NOT VERIFIABLE"
PROPOSAL_STATES = {"SUBMITTING", "PENDING", "APPROVED", "APPLYING", "APPLIED", "REJECTED", "EXPIRED", "LAPSED", "STALE",
                   "WITHDRAWN", "SUBMIT_FAILED", "AUTO_APPLYING", "AUTO_DENIED", "AUTO_FAILED"}
UNCERTAIN = {"SUBMITTING", "APPLYING", "AUTO_APPLYING"}
INCIDENT_CLOSERS = ("incident_verified", "incident_not_confirmed", "incident_closed_unverified", "incident_superseded")


@dataclass
class Check:
    name: str
    status: str
    detail: str
    records: list = field(default_factory=list)


def _wf_names(db):
    return {wf: wid for wf, wid in db.q("SELECT wf, workflow_id FROM workflows")}


def verify_store(db: DB) -> list[Check]:
    out: list[Check] = []
    names = _wf_names(db)

    # 1. event sequence: chunks contiguous, event ids contiguous across chunks, no duplicates
    chunks = db.q("SELECT chunk, events, first_event_id, last_event_id FROM chunks ORDER BY chunk")
    bad = []
    prev_last = None
    for i, (c, n, fe, le) in enumerate(chunks):
        if c != i:
            bad.append(f"chunk {c} at position {i} (gap or duplicate in chunk numbers)")
        if fe is not None and le is not None:
            if le - fe + 1 != n:
                bad.append(f"chunk {c}: {n} events stored but ids {fe}..{le}")
            if prev_last is not None and fe != prev_last + 1:
                bad.append(f"chunk {c}: first event {fe} does not follow {prev_last}")
            prev_last = le
    if not chunks:
        out.append(Check("event sequence", INCOMPLETE, "no chunks ingested"))
    else:
        total = sum(n for _, n, _, _ in chunks)
        out.append(Check("event sequence", INVALID if bad else VALID,
                         f"{len(chunks)} chunks, {total:,} events, ids 1..{prev_last}" if not bad else
                         f"{len(bad)} problems", bad[:20]))

    # 2. calls: one row per call event
    n, d = db.q1("SELECT COUNT(*), COUNT(DISTINCT event_id) FROM calls")
    out.append(Check("calls unique per event", VALID if n == d else INVALID, f"{n:,} rows, {d:,} distinct event ids"))

    # 3. audit log: append-only triggers present, wall clock monotone in id order
    trig = {r[0] for r in db.q("SELECT name FROM sqlite_master WHERE type='trigger'")}
    need = {"decisions_append_only_u", "decisions_append_only_d"}
    regress = db.q("SELECT a.decision_id FROM decisions a JOIN decisions b ON b.decision_id = a.decision_id + 1"
                   " WHERE b.wall < a.wall - 1e-6 LIMIT 20")
    ok = need <= trig and not regress
    out.append(Check("audit log append-only and ordered", VALID if ok else INVALID,
                     ("triggers present; wall clock monotone in id order" if ok else
                      f"missing triggers {sorted(need - trig)}; wall-clock regressions after ids {[r[0] for r in regress]}"),
                     [r[0] for r in regress]))

    # 4. governance boundary: every controller config version is exactly one APPLIED proposal (approval id matches)
    vers = db.q("SELECT wf, version, actor, proposal_id, approval_id FROM config_versions WHERE actor LIKE 'controller%'")
    bad = []
    for wf, v, actor, pid, aid in vers:
        rows = db.q("SELECT proposal_id, route, approval_id, state FROM proposals WHERE wf=? AND applied_version=?",
                    (wf, v))
        applied = [r for r in rows if r[3] == "APPLIED"]
        if len(applied) != 1:
            bad.append(f"{names.get(wf)} v{v} ({actor}): {len(applied)} APPLIED proposals")
        elif pid and applied[0][0] != pid:
            bad.append(f"{names.get(wf)} v{v}: config history says {pid}, store says {applied[0][0]}")
        elif actor == "controller_approved" and applied[0][2] != aid:
            bad.append(f"{names.get(wf)} v{v}: approval {aid} in config history, {applied[0][2]} on the proposal")
    out.append(Check("every controller change = one applied proposal", INVALID if bad else VALID,
                     f"{len(vers)} controller config versions checked" if not bad else f"{len(bad)} mismatches", bad[:20]))

    # 5. proposals: known states, APPLIED has a version that exists, nothing left uncertain
    bad, unsure = [], []
    for pid, wf, st, av in db.q("SELECT proposal_id, wf, state, applied_version FROM proposals"):
        if st not in PROPOSAL_STATES:
            bad.append(f"{pid}: unknown state {st}")
        if st == "APPLIED" and (av is None or not db.q1("SELECT 1 FROM config_versions WHERE wf=? AND version=?",
                                                       (wf, av))):
            bad.append(f"{pid}: APPLIED without a matching config version (v{av})")
        if st in UNCERTAIN:
            unsure.append(f"{pid}: {st}")
    st = INVALID if bad else (INCOMPLETE if unsure else VALID)
    out.append(Check("proposal states", st, "all proposals in known, settled states" if st == VALID else
                     f"{len(bad)} invalid, {len(unsure)} still uncertain (run interrupted?)", (bad + unsure)[:20]))

    # 6. references from decisions resolve
    bad = []
    for col, table, key in (("proposal_id", "proposals", "proposal_id"), ("experiment_id", "experiments",
                                                                          "experiment_id"),
                            ("incident_id", "incidents", "incident_id")):
        for (ref,) in db.q(f"SELECT DISTINCT d.{col} FROM decisions d LEFT JOIN {table} t ON t.{key}=d.{col}"
                           f" WHERE d.{col} IS NOT NULL AND t.{key} IS NULL"):
            bad.append(f"decision references missing {table[:-1]} {ref}")
    out.append(Check("decision references resolve", INVALID if bad else VALID,
                     "every proposal / experiment / incident a decision names exists" if not bad else
                     f"{len(bad)} orphan references", bad[:20]))

    # 7. supervisor edits were seen and handled (a missed one is how an edit gets overwritten)
    bad = []
    for wf, v, minute in db.q("SELECT wf, version, minute FROM config_versions WHERE actor='supervisor'"):
        if not db.q1("SELECT 1 FROM decisions WHERE wf=? AND kind='supervisor_edit' AND config_version=?", (wf, v)):
            bad.append(f"{names.get(wf)} v{v} at {minute_to_label(minute)}: no supervisor_edit decision")
    out.append(Check("every supervisor edit acknowledged", INVALID if bad else VALID,
                     "each supervisor config version has its supervisor_edit decision (lock + re-plan)" if not bad
                     else f"{len(bad)} unacknowledged", bad))

    # 8. experiment lifecycles are complete
    bad = []
    for eid, st in db.q("SELECT experiment_id, status FROM experiments"):
        kinds = {k for (k,) in db.q("SELECT DISTINCT kind FROM decisions WHERE experiment_id=?", (eid,))}
        if "experiment_designed" not in kinds:
            bad.append(f"{eid}: no experiment_designed decision")
        if st in ("promoted", "promoting", "rolling_back", "rolled_back") and not kinds & {"experiment_winner"}:
            bad.append(f"{eid}: status {st} without an experiment_winner decision")
        if st == "rolled_back" and "decay_detected" not in kinds and "experiment_rolled_back" not in kinds:
            bad.append(f"{eid}: rolled back without decay_detected")
    out.append(Check("experiment lifecycles complete", INVALID if bad else VALID,
                     f"{db.q1('SELECT COUNT(*) FROM experiments')[0]} experiments" if not bad else
                     f"{len(bad)} incomplete", bad[:20]))

    # 9. incidents closed with a reason
    bad = []
    for iid, st in db.q("SELECT incident_id, state FROM incidents"):
        if st == "closed" and not db.q1(f"SELECT 1 FROM decisions WHERE incident_id=? AND kind IN"
                                        f" ({','.join('?' * len(INCIDENT_CLOSERS))})", (iid, *INCIDENT_CLOSERS)):
            bad.append(f"{iid}: closed without a closing decision")
    out.append(Check("incidents closed with a reason", INVALID if bad else VALID,
                     f"{db.q1('SELECT COUNT(*) FROM incidents')[0]} incidents" if not bad else f"{len(bad)} silent",
                     bad))

    # 10. config history contiguous per workflow (a gap = a config_changed event never ingested)
    bad = []
    for wf, lo, hi, n in db.q("SELECT wf, MIN(version), MAX(version), COUNT(*) FROM config_versions GROUP BY wf"):
        if hi - lo + 1 != n:
            bad.append(f"{names.get(wf)}: versions {lo}..{hi} but {n} recorded")
    out.append(Check("config history contiguous", INCOMPLETE if bad else VALID,
                     "no missing config versions" if not bad else f"{len(bad)} workflows with gaps", bad))

    # 11. credits and inbox settled
    sent = db.q("SELECT id, purpose FROM credits_ledger WHERE state='sent'")
    has_inbox = db.q1("SELECT 1 FROM sqlite_master WHERE type='table' AND name='inbox'")
    pend = db.q1("SELECT COUNT(*) FROM inbox WHERE done=0")[0] if has_inbox else 0
    st = INCOMPLETE if (sent or pend) else VALID
    out.append(Check("credits and events settled", st,
                     "no paid call with unknown outcome; no unprocessed event" if st == VALID else
                     f"{len(sent)} paid calls with unknown outcome, {pend} unprocessed events",
                     [f"ledger {i}: {p}" for i, p in sent][:20]))
    return out


def render_verify(checks: list[Check]) -> tuple[str, int]:
    w = max(len(c.name) for c in checks)
    lines = ["# Audit store verification", ""]
    for c in checks:
        lines.append(f"{c.status:15s} {c.name:{w}s}  {c.detail}")
        for r in c.records[:8]:
            lines.append(f"{'':15s} {'':{w}s}    · {r}")
    worst = (INVALID if any(c.status == INVALID for c in checks) else
             INCOMPLETE if any(c.status == INCOMPLETE for c in checks) else VALID)
    lines += ["", f"overall: {worst} ({sum(c.status == VALID for c in checks)}/{len(checks)} checks VALID)"]
    return "\n".join(lines), {VALID: 0, INCOMPLETE: 2, INVALID: 1}[worst]


# ------------------------------------------------------------------ replay
def _recompute_look(db: DB, d: dict, minute: int, eid: str) -> list[str]:
    """Recount the arms of an experiment look from raw `calls` (not the rollups) as of the look, and recompute the
    statistics with the same formulas. Compares with what the decision stored."""
    e = db.q1("SELECT data FROM experiments WHERE experiment_id=?", (eid,))
    if not e:
        return [f"{NOT_VERIFIABLE}: experiment {eid} not in the store"]
    x = json.loads(e[0])
    col = "wm" if x["dim"] == "welcome_message" else "voice"
    vs = x.get("versions") or []
    start = x.get("start_minute")
    if start is None or not vs:
        return [f"{NOT_VERIFIABLE}: experiment start / versions not retained"]
    lo, hi = (start // 60) * 60, -(-minute // 60) * 60
    rows = db.q(f"SELECT {col}, COUNT(*), SUM(conn), SUM(eng) FROM calls WHERE wf=? AND minute>=? AND minute<? AND"
                f" cfg_ver IN ({','.join('?' * len(vs))}) GROUP BY 1", (x["wf"], lo, hi, *vs))
    raw = {db.decode(x["dim"], o): (n, k or 0, g or 0) for o, n, k, g in rows}
    out = [f"recount from raw calls: {x['dim']}, config versions {vs}, {minute_to_label(lo)} → {minute_to_label(hi)}"]
    inc = d.get("incumbent") or {}
    io = inc.get("option")
    ri = raw.get(io, (0, 0, 0))
    same = (ri[1], ri[2]) == (inc.get("connected"), inc.get("engaged"))
    out.append(f"{VALID if same else INVALID}: incumbent {io} stored {inc.get('connected')}/{inc.get('engaged')}"
               f" connected/engaged, recounted {ri[1]}/{ri[2]}")
    ps = {}
    for o, a in sorted((d.get("arms") or {}).items()):
        r = raw.get(o, (0, 0, 0))
        c = compare(Prop(ri[2], ri[1]), Prop(r[2], r[1]))
        ps[o] = 1 - phi(c.z) if r[1] and ri[1] else None
        ok = (r[1], r[2]) == (a.get("connected"), a.get("engaged")) and abs(round(c.z, 2) - (a.get("z") or 0)) < 0.011
        out.append(f"{VALID if ok else INVALID}: {o} stored n {a.get('connected')} z {a.get('z')} p {a.get('p')};"
                   f" recomputed n {r[1]} z {c.z:.2f} p {ps[o]:.3g} lift {c.rel:+.1%}")
    al = d.get("alpha_look")
    if al and all(v is not None for v in ps.values()) and ps:
        srt = sorted((p, o) for o, p in ps.items())
        win, okk = [], True
        for i, (p, o) in enumerate(srt):
            thr = 0.8 * al / (len(srt) - i)
            okk = okk and p <= thr
            if okk:
                win.append(o)
        stored = d.get("significant")
        if stored is None:
            out.append(f"recomputed Holm at 80% of alpha_look {al}: significant {sorted(win)} (none stored to compare)")
        else:
            out.append(f"{VALID if sorted(win) == sorted(stored) else INVALID}: Holm at 80% of alpha_look {al} →"
                       f" significant {sorted(win)}; stored {sorted(stored)}")
    return out


def _recompute_did(db: DB, wf: int, minute: int, summ: str, stored: dict) -> list[str]:
    """Re-run the caller-ID detector on the persisted rows as of the decision (same inputs: its own-past baseline is
    computed at the start of each 6 h bucket) and compare the fast and slow windows that decide 'degraded'."""
    import re
    from .config import Settings
    from .detectors import did_health, did_own_past
    m = re.search(r"caller ID (\S+):", summ)
    spec = db.q1("SELECT spec FROM workflows WHERE wf=?", (wf,))
    if not m or not spec:
        return [f"{NOT_VERIFIABLE}: caller ID or workflow options not retained"]
    did = m.group(1)
    opts = (json.loads(spec[0]).get("options") or {}).get("caller_id") or [did]
    s = Settings()
    own = did_own_past(db, wf, (minute // 360) * 360, s)
    now_h = did_health(db, wf, opts, minute, s, None, None, own).get(did, {})
    out = [f"re-run of the caller-ID detector for {did} at {minute_to_label(minute)} (default settings)"]
    for w in ("fast", "slow"):
        a, b = (stored.get("windows") or {}).get(w), (now_h.get("windows") or {}).get(w)
        if not a or not b:
            out.append(f"{NOT_VERIFIABLE}: {w} window not in the stored evidence")
            continue
        same = all(a.get(k) == b.get(k) for k in ("dials", "connected", "pickup", "z"))
        out.append(f"{VALID if same else INVALID}: {w} window stored {a.get('dials')} dials, pickup {a.get('pickup')},"
                   f" z {a.get('z')}; recomputed {b.get('dials')} dials, pickup {b.get('pickup')}, z {b.get('z')}")
    out.append(f"{VALID if now_h.get('state') == stored.get('state') else INVALID}: state stored {stored.get('state')},"
               f" recomputed {now_h.get('state')}")
    return out


def replay(db: DB, decision_id: int) -> str:
    r = db.q1("SELECT d.decision_id, d.minute, d.wf, w.workflow_id, d.kind, d.actor, d.summary, d.reasoning, d.evidence,"
              " d.proposal_id, d.approval_id, d.config_version, d.experiment_id, d.incident_id FROM decisions d LEFT JOIN"
              " workflows w ON w.wf=d.wf WHERE d.decision_id=?", (decision_id,))
    if not r:
        return f"no decision #{decision_id}"
    did, m, wf, wid, kind, actor, summ, reason, ev, pid, aid, ver, eid, iid = r
    evd = json.loads(ev) if ev else {}
    out = [f"# replay of decision #{did} — {kind} · {wid or 'controller'} · as of {minute_to_label(m)}", "",
           "Read-only reconstruction from persisted evidence; recomputed where raw rows allow (VALID / INVALID),",
           "NOT VERIFIABLE where the evidence needed was never retained.", "", f"What was decided:  {summ}"]
    if reason:
        out.append(f"Stated reason:     {reason}")
    if wf is not None:
        # what the controller could see at that moment (only rows before the decision time)
        v = db.q1("SELECT version, actor, minute FROM config_versions WHERE wf=? AND minute<=? ORDER BY version DESC"
                  " LIMIT 1", (wf, m))
        k = db.q1("SELECT COUNT(*), SUM(conn), SUM(eng) FROM calls WHERE wf=? AND minute>=? AND minute<?",
                  (wf, m - 1440, m))
        out += ["", "## Observable at decision time (rows with minute < decision)"]
        if v:
            out.append(f"live config: v{v[0]} by {v[1]} since {minute_to_label(v[2])}")
        if k and k[0]:
            out.append(f"last 24 h: {k[0]:,} dials, pickup {k[1] / k[0]:.3f}, engagement "
                       f"{(k[2] / k[1]) if k[1] else 0:.3f} on {k[1]:,} connected")
        act = db.q("SELECT DISTINCT experiment_id FROM decisions WHERE wf=? AND minute<=? AND kind='experiment_started'",
                   (wf, m))
        if act:
            out.append("experiments started before it: " + ", ".join(x[0] for x in act))
        inc = db.q1("SELECT incident_id, state FROM incidents WHERE wf=? AND opened_minute<=? AND (closed_minute IS NULL"
                    " OR closed_minute>=?) LIMIT 1", (wf, m, m))
        if inc:
            out.append(f"incident open at the time: {inc[0]}")
    out += ["", "## Independent check of the evidence"]
    checks = []
    if kind in ("experiment_look", "experiment_winner", "experiment_no_winner", "experiment_extended",
                "experiment_drop_arm") and eid:
        checks += _recompute_look(db, evd, m, eid)
    if kind == "did_health" and wf is not None and evd.get("windows"):
        checks += _recompute_did(db, wf, m, summ, evd)
    if kind == "validation_run" or (kind in ("incident_opened", "incident_fix_selected") and evd.get("validation")):
        vr = (evd.get("validation") or evd).get("validation_run_id")
        row = db.q1("SELECT response FROM credits_ledger WHERE response LIKE ?", (f'%"{vr}"%',)) if vr else None
        if row:
            resp = json.loads(row[0])
            src = evd.get("validation") or evd
            ok = (resp.get("failures"), resp.get("n")) == (src.get("failures"), src.get("n"))
            checks.append(f"{VALID if ok else INVALID}: validation {vr} in the credits ledger: {resp.get('failures')}"
                          f" failures in {resp.get('n')}; decision says {src.get('failures')} in {src.get('n')}")
        else:
            checks.append(f"{NOT_VERIFIABLE}: validation result not found in the credits ledger")
    if pid:
        p = db.q1("SELECT route, state, applied_version, approval_id FROM proposals WHERE proposal_id=?", (pid,))
        if p:
            line = f"proposal {pid}: {p[0]} route, {p[1]}"
            if p[1] == "APPLIED":
                cv = db.q1("SELECT actor, proposal_id, approval_id FROM config_versions WHERE wf=? AND version=?",
                           (wf, p[2]))
                ok = bool(cv) and cv[1] in (pid, None) and (p[0] != "approval" or cv[2] == p[3])
                line = (f"{VALID if ok else INVALID}: {line} → config v{p[2]} by {cv[0] if cv else '?'}"
                        + (f", approval {p[3]}" if p[3] else ""))
            checks.append(line)
        else:
            checks.append(f"{INVALID}: proposal {pid} referenced but not in the store")
    if not checks:
        checks.append(f"{NOT_VERIFIABLE}: this decision kind carries no recomputable statistics; its evidence is shown"
                      f" by `decision {did}`")
    out += checks
    if wf is not None:
        nxt = db.q("SELECT decision_id, minute, kind, summary FROM decisions WHERE wf=? AND decision_id>? AND kind IN"
                   " ('proposal_applied','experiment_promoted','experiment_rolled_back','decay_detected',"
                   "'post_apply_verification','incident_verified','incident_fix_harmful','proposal_rejected',"
                   "'proposal_stale','experiment_aborted') ORDER BY decision_id LIMIT 6", (wf, did))
        if nxt:
            out += ["", "## What followed"] + [f"#{x[0]:<5} {minute_to_label(x[1])}  {x[2]:24s} {x[3][:110]}" for x in nxt]
    return "\n".join(out)
