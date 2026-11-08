"""Controller-level logic with a FakeSim: governance routing (batching, hold, fatigue, auto-apply ramp),
caller-ID target allocation, and the audit 'why' view built from our own store."""
import copy

import pytest

from outcomeloop import views
from outcomeloop.config import Settings
from outcomeloop.controller import Controller, changed_dims, max_shift
from outcomeloop.db import dumps
from outcomeloop.experiments import ExperimentEngine
from outcomeloop.governance import Governance

from fakes import FakeSim

WID = "nw_renewal"
CFG = {"cohorts": [], "allocations": {"default": {"welcome_message": {"W1": 1.0}, "voice": {"V1": 1.0},
                                                  "caller_id": {"D1": 0.5, "D2": 0.5}}},
       "prompt_version": "P1", "schedule": {"hour_weights": {}, "lead_preferred_hour": {}}}


def make_spec(allowed=("schedule", "caller_id"), max_shift_=0.2, cap=3, tenant="northwind_life"):
    return {"workflow_id": WID, "tenant_id": tenant, "cadence": [2, 2], "mid_flight": "allowed",
            "daily_batch": {"size": 500, "at_hour": 8}, "dialling_window": [9, 21],
            "options": {"welcome_message": ["W1", "W2"], "voice": ["V1", "V2"], "caller_id": ["D1", "D2", "D3", "D4"],
                        "prompt_version": ["P1", "P3"]},
            "objective": {"primary": "engagement_rate", "guardrail": {"pickup_rate_max_drop": 0.02}},
            "governance": {"approver_hours": [10, 19], "approver_latency_minutes": [30, 120], "proposal_ttl_hours": 24,
                           "apply_window_hours": 2, "max_requests_per_24h": cap,
                           "auto_apply": {"enabled": True, "allowed_dims": list(allowed), "max_shift": max_shift_}}}


@pytest.fixture()
def ctl(db, settings):
    c = Controller.__new__(Controller)          # no network: wire the parts by hand
    c.s, c.db, c.sim = settings, db, FakeSim({WID: CFG})
    c.gov, c.exp = Governance(db, c.sim, settings), ExperimentEngine(db, settings)
    c.wf = db.code("wf", WID)
    c.specs = {c.wf: make_spec()}
    c.wf_by_id = {WID: c.wf}
    c.now = 11 * 60
    c.urgent = set()
    return c


def ctx(**kw):
    return {"locks": {}, "notes": [], "evidence": {}, "emergency": False, "kinds": [], "components": {}, **kw}


def _with(cfg, dim, dist):
    out = copy.deepcopy(cfg)
    out["allocations"]["default"][dim] = dist
    return out


def decisions(db, kind):
    return [r[0] for r in db.q("SELECT summary FROM decisions WHERE kind=? ORDER BY decision_id", (kind,))]


def voice_ctx():
    return ctx(components={"voice": {"summary": "voice: designed V1 60%, V2 40%", "status": "designed",
                                     "experiment_id": "e1", "evidence": {"design": {}}}})


# ------------------------------------------------------------------ routing
def test_customer_facing_change_goes_to_approval_even_if_policy_allows_auto(ctl):
    ctl.specs[ctl.wf] = spec = make_spec(allowed=("voice", "caller_id"), max_shift_=1.0)
    cur = ctl.sim.config(WID)
    ctl.route(ctl.wf, spec, cur, _with(CFG, "voice", {"V1": 0.6, "V2": 0.4}), voice_ctx())
    assert ctl.sim.calls["auto_apply"] == 0 and ctl.sim.calls["request_approval"] == 1
    st = ctl.db.q1("SELECT route, state FROM proposals")
    assert st == ("approval", "PENDING")


def test_outside_approver_hours_holds_once(ctl):
    ctl.now = 8 * 60
    spec = ctl.specs[ctl.wf]
    desired = _with(CFG, "voice", {"V1": 0.6, "V2": 0.4})
    for t in (8 * 60, 8 * 60 + 15, 8 * 60 + 30):
        ctl.now = t
        ctl.route(ctl.wf, spec, ctl.sim.config(WID), desired, voice_ctx())
    assert ctl.sim.calls["request_approval"] == 0
    holds = decisions(ctl.db, "hold")
    assert len(holds) == 1 and "approver hours" in holds[0]     # deduplicated: one audit row, not one per tick
    ctl.now = 10 * 60
    ctl.route(ctl.wf, spec, ctl.sim.config(WID), desired, voice_ctx())
    assert ctl.sim.calls["request_approval"] == 1
    assert ctl.db.kv_get(f"hold:{ctl.wf}") is None              # cleared on submit


def test_fatigue_holds_routine_change(ctl):
    spec = ctl.specs[ctl.wf]
    with ctl.db.tx():
        for i in range(2):   # cap 3, one slot reserved for incidents -> routine is out of budget
            ctl.db.x("INSERT INTO proposals (proposal_id, wf, route, state, kind, base_version, body, created_minute,"
                     " updated_minute) VALUES (?,?,?,?,?,?,?,?,?)",
                     (f"old{i}", ctl.wf, "approval", "APPLIED", "routine", 1, "{}", ctl.now - 60, ctl.now - 60))
    ctl.route(ctl.wf, spec, ctl.sim.config(WID), _with(CFG, "voice", {"V1": 0.6, "V2": 0.4}), voice_ctx())
    assert ctl.sim.calls["request_approval"] == 0
    assert "fatigue" in decisions(ctl.db, "hold")[0]


def test_one_open_proposal_batches_later_wants(ctl):
    spec = ctl.specs[ctl.wf]
    ctl.route(ctl.wf, spec, ctl.sim.config(WID), _with(CFG, "voice", {"V1": 0.6, "V2": 0.4}), voice_ctx())
    assert ctl.sim.calls["request_approval"] == 1
    ctl.now += 60
    wants = _with(_with(CFG, "voice", {"V1": 0.6, "V2": 0.4}), "welcome_message", {"W1": 0.6, "W2": 0.4})
    ctl.route(ctl.wf, spec, ctl.sim.config(WID), wants, voice_ctx())
    assert ctl.sim.calls["request_approval"] == 1                # waits for the open one


def test_auto_apply_not_sent_while_approval_pending(ctl):
    spec = ctl.specs[ctl.wf]
    ctl.route(ctl.wf, spec, ctl.sim.config(WID), _with(CFG, "voice", {"V1": 0.6, "V2": 0.4}), voice_ctx())
    ctl.now += 60
    ctl.route(ctl.wf, spec, ctl.sim.config(WID), _with(CFG, "caller_id", {"D1": 0.4, "D2": 0.4, "D3": 0.2}), ctx())
    assert ctl.sim.calls["auto_apply"] == 0      # would make the pending proposal stale


def test_auto_apply_ramps_within_max_shift(ctl):
    spec = ctl.specs[ctl.wf]                     # max_shift 0.2
    target = {"D3": 0.5, "D4": 0.5}              # TV 1.0 from the live {D1,D2}
    applied = []
    for step in range(12):
        ctl.now = 11 * 60 + step * 60
        before = ctl.sim.config(WID)["config"]
        ctl.route(ctl.wf, spec, ctl.sim.config(WID), _with(before, "caller_id", target), ctx())
        after = ctl.sim.config(WID)["config"]
        if after != before:
            applied.append(max_shift(before, after))
            assert changed_dims(before, after) == ["caller_id"]
    assert applied, "no ramp step was applied"
    assert all(s <= 0.2 + 1e-9 for s in applied)
    # cumulative daily cap: ramp_daily_shift_multiple x max_shift
    assert sum(applied) <= ctl.s.ramp_daily_shift_multiple * 0.2 + 1e-6
    assert "ramp budget" in " ".join(decisions(ctl.db, "hold"))


def test_ramp_steps_are_at_least_an_hour_apart(ctl):
    spec = ctl.specs[ctl.wf]
    target = {"D3": 0.5, "D4": 0.5}
    for t in (11 * 60, 11 * 60 + 15, 11 * 60 + 30):
        ctl.now = t
        ctl.route(ctl.wf, spec, ctl.sim.config(WID), _with(ctl.sim.config(WID)["config"], "caller_id", target), ctx())
    assert ctl.sim.calls["auto_apply"] == 1


def test_no_change_no_request(ctl):
    ctl.route(ctl.wf, ctl.specs[ctl.wf], ctl.sim.config(WID), copy.deepcopy(CFG), ctx())
    assert ctl.sim.calls["auto_apply"] == ctl.sim.calls["request_approval"] == 0


# ------------------------------------------------------------------ caller-ID target
OPTS = ["D1", "D2", "D3", "D4"]


def test_did_target_spreads_over_healthy_probes_unknown_drops_degraded(ctl):
    mem = {"D1": {"state": "healthy"}, "D2": {"state": "healthy"}, "D3": {"state": "degraded"}}
    t = ctl.did_target(OPTS, mem, {"D1": 0.5, "D2": 0.5})
    assert "D3" not in t
    assert t["D4"] == ctl.s.did_probe_share
    assert t["D1"] == t["D2"] == pytest.approx((1 - ctl.s.did_probe_share) / 2, abs=1e-4)
    assert sum(t.values()) == pytest.approx(1, abs=1e-3)


def test_did_target_reprobe_gets_smaller_share(ctl):
    mem = {"D1": {"state": "healthy"}, "D3": {"state": "probe"}, "D2": {"state": "degraded"},
           "D4": {"state": "degraded"}}
    t = ctl.did_target(OPTS, mem, {"D1": 1.0})
    assert t == {"D3": ctl.s.did_reprobe_share, "D1": round(1 - ctl.s.did_reprobe_share, 4)}


def test_did_target_without_measured_healthy_keeps_current_minus_degraded(ctl):
    mem = {"D2": {"state": "degraded"}}
    t = ctl.did_target(OPTS, mem, {"D1": 0.5, "D2": 0.5})
    assert "D2" not in t and t["D1"] > 0.8
    assert set(t) <= {"D1", "D3", "D4"}


def test_did_target_all_degraded_changes_nothing(ctl):
    mem = {d: {"state": "degraded"} for d in OPTS}
    cur = {"D1": 0.5, "D2": 0.5}
    assert ctl.did_target(OPTS, mem, cur) == cur         # never strand all capacity on no numbers


# ------------------------------------------------------------------ views.why
def _audit_db(db):
    wf = db.code("wf", WID)
    body = {"change_summary": "voice: promote V2", "impact_score": 0.4, "affected_leads": 321,
            "rationale": "V2 beat V1 on engagement", "diff": {"voice": {"default": {"after": {"V2": 0.85}}}}}
    with db.tx():
        db.x("INSERT INTO workflows VALUES (?,?,?,?)", (wf, WID, "northwind_life", "{}"))
        db.x("INSERT INTO proposals (proposal_id, wf, route, state, kind, base_version, body, approval_id, approval,"
             " applied_version, created_minute, updated_minute) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
             ("ol-p1", wf, "approval", "APPLIED", "routine", 3, dumps(body), "apr_00007",
              dumps({"approval_id": "apr_00007", "decided_at": "D3 13:40"}), 4, 3 * 1440 + 11 * 60, 3 * 1440 + 14 * 60))
        db.x("INSERT INTO config_versions (wf, version, actor, minute, changed_dims, proposal_id, approval_id) VALUES"
             " (?,?,?,?,?,?,?)", (wf, 4, "controller_approved", 3 * 1440 + 14 * 60, '["voice"]', "ol-p1", "apr_00007"))
        db.x("INSERT INTO config_versions (wf, version, actor, minute, changed_dims) VALUES (?,?,?,?,?)",
             (wf, 5, "supervisor", 5 * 1440 + 9 * 60, '["prompt_version"]'))
        db.decide(3 * 1440 + 10 * 60, wf, "experiment_winner", "voice: winner V2")
        db.decide(3 * 1440 + 11 * 60, wf, "proposal_submitted", "ol-p1 -> PENDING", proposal_id="ol-p1")
        db.decide(4 * 1440 + 10 * 60, wf, "decay_detected", "voice: winner stopped winning")
        db.decide(5 * 1440 + 9 * 60, wf, "supervisor_edit", "supervisor changed ['prompt_version']")


def test_why_explains_change_approver_and_aftermath(db):
    _audit_db(db)
    out = views.why(db, WID, "D3 14:00")
    assert "v4" in out and "controller_approved" in out
    assert "ol-p1" in out and "apr_00007" in out and "Approved by" in out
    assert "voice: promote V2" in out and "321" in out
    before, after = out.split("What happened next")
    assert "experiment_winner" in before and "decay_detected" in after


def test_why_supervisor_edit_and_nothing_on_record(db):
    _audit_db(db)
    sup = views.why(db, WID, "D5 10:00")
    assert "supervisor edit" in sup and "supervisor_edit" in sup
    none = views.why(db, WID, "D1 10:00")
    assert "No configuration change on record" in none


def test_did_target_degraded_number_always_loses_traffic_even_without_healthy(ctl):
    # the only measured number is flagged; the others are untested probes: move to them rather than keep 91%
    t = ctl.did_target(["D1", "D2", "D3"], {"D1": {"state": "degraded"}}, {"D1": 0.91, "D2": 0.045, "D3": 0.045})
    assert "D1" not in t and t["D2"] == pytest.approx(0.5) and t["D3"] == pytest.approx(0.5)


def test_did_target_freed_share_prefers_numbers_with_real_traffic(ctl):
    t = ctl.did_target(OPTS, {"D2": {"state": "degraded"}}, {"D1": 0.5, "D2": 0.5})
    assert t["D1"] == pytest.approx(0.9) and t["D3"] == pytest.approx(0.05) and "D2" not in t


def test_did_target_probe_budget_is_capped(ctl):
    opts = ["D1", "D2", "D3", "D4", "D5"]
    t = ctl.did_target(opts, {"D1": {"state": "healthy"}, "D2": {"state": "healthy"}}, {"D1": 0.5, "D2": 0.5})
    assert sum(t[d] for d in ("D3", "D4", "D5")) == pytest.approx(0.10, abs=1e-3)


def test_did_target_unknown_numbers_keep_their_share(ctl):
    t = ctl.did_target(["D1", "D2", "D3"], {"D1": {"state": "healthy"}}, {"D1": 0.34, "D2": 0.33, "D3": 0.33})
    assert t == {"D1": 0.34, "D2": 0.33, "D3": 0.33}


# ---------------------------------------------------------------- audit fix: events are never dropped on a hiccup
def test_supervisor_event_survives_a_transient_failure_and_holds_decisions(ctl, db, monkeypatch):
    import httpx
    from outcomeloop.ingest import INBOX_SQL
    from outcomeloop.db import dumps as _d
    db.x(INBOX_SQL)
    ctl.ing = type("Ing", (), {})()
    ctl.ing.inbox = lambda: db.q("SELECT event_id, type, wf, minute, payload FROM inbox WHERE done=0 ORDER BY event_id")
    ctl.ing.mark_done = lambda eid: db.x("UPDATE inbox SET done=1 WHERE event_id=?", (eid,))
    ev = {"type": "config_changed", "workflow_id": WID, "version": 2, "actor": "supervisor",
          "changed_dims": ["voice"], "proposal_id": None, "approval_id": None, "event_id": 7, "ts": "x"}
    with db.tx():
        db.x("INSERT INTO inbox (event_id, type, wf, minute, payload) VALUES (7,'config_changed',?,600,?)", (ctl.wf, _d(ev)))
    real = ctl.sim.config
    boom = {"n": 1}

    def flaky(wid):
        if boom["n"]:
            boom["n"] -= 1
            raise httpx.ConnectError("simulator briefly down")
        return real(wid)
    monkeypatch.setattr(ctl.sim, "config", flaky)
    ctl.handle_inbox()
    # not dropped: still pending, no lock lost, and the workflow is held (no decisions on a stale view)
    assert db.q1("SELECT done FROM inbox WHERE event_id=7")[0] == 0
    assert ctl.pending_events(ctl.wf) == 1
    ctl.handle_inbox()                                   # simulator back: processed, lock written
    assert db.q1("SELECT done FROM inbox WHERE event_id=7")[0] == 1
    assert "voice" in db.kv_get(f"locks:{ctl.wf}", {})
    assert db.kv_get(f"supervisor_dims:{ctl.wf}") == ["voice"]


def test_pending_cohort_level_promotion_does_not_crash_decisions(ctl, db):
    # regression: a promotion with only cohort-level winners has no "default" scope; the pending re-check used to
    # raise KeyError('default') every hour and block all decisions for the workflow
    from outcomeloop.experiments import Experiment
    e = Experiment(experiment_id="exp-c", wf=ctl.wf, dim="voice", arms=["V1", "V2"], incumbent="V1",
                   design={"V1": 0.6, "V2": 0.4}, status="promoting", start_minute=0, versions=[1])
    e.plan = {"default": {"V1": 1.0}, "age_60p": {"V2": 0.85, "V1": 0.15}}
    e.promo = {"age_60p": {"winner": "V2", "incumbent": "V1", "diff": 0.05, "se": 0.02}}
    e.winner = "age_60p:V2"
    with db.tx():
        e.save(db, 0)
    ctl.step_experiments(ctl.wf, ctl.specs[ctl.wf], CFG, 12 * 60, ctx())   # must not raise
    assert Experiment.load_active(db, ctl.wf)["voice"].status == "promoting"


def test_post_apply_verification_flags_a_guardrail_breach(ctl, db):
    # an applied change after which the guardrail KPI (pickup, for an engagement-primary workflow) collapses
    from helpers import add_calls
    from outcomeloop.db import dumps as _d
    t = 2 * 1440
    with db.tx():
        db.x("INSERT INTO config_versions (wf, version, actor, minute, changed_dims) VALUES (?,?,?,?,?)",
             (ctl.wf, 5, "controller_auto", t, _d(["schedule"])))
        db.x("INSERT INTO proposals (proposal_id, wf, route, state, kind, base_version, body, applied_version,"
             " created_minute, updated_minute) VALUES ('ol-x', ?, 'auto', 'APPLIED', 'operational', 4, '{}', 5, ?, ?)",
             (ctl.wf, t, t))
    add_calls(db, ctl.wf, 4000, 1200, 600, minute=t - 1440, spread=1440)     # before: pickup 0.30
    add_calls(db, ctl.wf, 4000, 800, 400, minute=t, spread=1440)             # after:  pickup 0.20
    spec = dict(ctl.specs[ctl.wf], objective={"primary": "engagement_rate", "guardrail": {"pickup_rate_max_drop": 0.02}})
    ctl.verify_applied(ctl.wf, spec, t + 1440)
    v = db.q("SELECT summary FROM decisions WHERE kind='post_apply_verification'")
    assert len(v) == 1 and "GUARDRAIL BREACH" in v[0][0]
    assert db.q1("SELECT COUNT(*) FROM decisions WHERE kind='alert'")[0] == 1
    ctl.verify_applied(ctl.wf, spec, t + 1500)                                 # verified once, not again
    assert db.q1("SELECT COUNT(*) FROM decisions WHERE kind='post_apply_verification'")[0] == 1


def test_fair_share_is_work_conserving_and_binds_only_under_contention():
    from outcomeloop.controller import fair_share_ok
    spent = {"t1": 6.0, "t2": 0.0}
    # no other tenant needs credits: t1 may keep spending past its share
    assert fair_share_ok(spent, "t1", 3, 12, 3, contenders={"t1"})
    # t2 has an open incident and t1 already used more than 12/3: t1 waits, t2 may spend
    assert not fair_share_ok(spent, "t1", 1, 12, 3, contenders={"t1", "t2"})
    assert fair_share_ok(spent, "t2", 3, 12, 3, contenders={"t1", "t2"})
    assert fair_share_ok({"t1": 50.0}, "t1", 3, 12, 1, contenders={"t1", "t2"})   # single tenant: never binds


def test_pickup_drop_after_a_voice_change_is_recorded_but_not_paged(ctl, db):
    # voice is heard only after the call connects: a pickup drop in the 24 h after a voice change is time-confounded
    from helpers import add_calls
    from outcomeloop.db import dumps as _d
    t = 2 * 1440
    with db.tx():
        db.x("INSERT INTO config_versions (wf, version, actor, minute, changed_dims) VALUES (?,?,?,?,?)",
             (ctl.wf, 5, "controller_approved", t, _d(["voice"])))
        db.x("INSERT INTO proposals (proposal_id, wf, route, state, kind, base_version, body, applied_version,"
             " created_minute, updated_minute) VALUES ('ol-v', ?, 'approval', 'APPLIED', 'routine', 4, '{}', 5, ?, ?)",
             (ctl.wf, t, t))
    add_calls(db, ctl.wf, 4000, 1200, 600, minute=t - 1440, spread=1440)     # before: pickup 0.30
    add_calls(db, ctl.wf, 4000, 800, 400, minute=t, spread=1440)             # after:  pickup 0.20
    spec = dict(ctl.specs[ctl.wf], objective={"primary": "engagement_rate", "guardrail": {"pickup_rate_max_drop": 0.02}})
    ctl.verify_applied(ctl.wf, spec, t + 1440)
    v = db.q1("SELECT summary, evidence FROM decisions WHERE kind='post_apply_verification'")
    assert "not attributable" in v[0] and "pickup_drop_not_attributable" in v[1]
    assert db.q1("SELECT COUNT(*) FROM decisions WHERE kind='alert'")[0] == 0


def test_step_experiments_skips_a_retest_of_a_supervisor_choice_with_nothing_to_learn(ctl, db):
    # public_02, wired end to end: the supervisor set voice=V2; our aborted test two days ago measured V1 and V2
    # within noise. The voice test is skipped (audited, cooldown); welcome (no prior evidence) is still designed.
    import json as _j
    from helpers import add_calls
    from outcomeloop.experiments import Experiment
    now = 5 * 1440 + 12 * 60
    cfg = _with(CFG, "voice", {"V2": 1.0})
    add_calls(db, ctl.wf, 6000, 2000, 1100, minute=now - 3 * 1440, spread=3 * 1440, voice="V2")
    look = {"incumbent": {"option": "V1", "connected": 2900, "engaged": 1595},
            "arms": {"V2": {"connected": 648, "engaged": 358}}}
    with db.tx():
        db.kv_set(f"supervisor_dims:{ctl.wf}", ["voice"])
        db.x("INSERT INTO experiments VALUES (?,?,?,?,?,?,?)", ("exp-prior-voice", ctl.wf, "voice", "aborted",
             _j.dumps({"looks": [look], "arms": ["V1", "V2"]}), now - 7 * 1440, now - 2 * 1440))
    ctl.step_experiments(ctl.wf, ctl.specs[ctl.wf], cfg, now, ctx())
    skipped = decisions(db, "experiment_skipped")
    assert len(skipped) == 1 and skipped[0].startswith("voice: no challenger worth testing against V2")
    assert db.kv_get(f"skip_until:{ctl.wf}:voice") > now
    active = Experiment.load_active(db, ctl.wf)
    assert "voice" not in active and "welcome_message" in active
    ev = _j.loads(db.q1("SELECT evidence FROM decisions WHERE kind='experiment_skipped'")[0])
    assert ev["strict"] is True and ev["challengers"]["V1"]["kept"] is False
    ctl.step_experiments(ctl.wf, ctl.specs[ctl.wf], cfg, now + 60, ctx())       # cooldown: not re-evaluated hourly
    assert len(decisions(db, "experiment_skipped")) == 1
