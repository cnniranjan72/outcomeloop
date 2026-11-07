"""Governance client against a deterministic FakeSim: lifecycle, timing, fatigue and crash/uncertainty recovery."""
import copy

import pytest

from outcomeloop.governance import Governance
from outcomeloop.simclient import ApiError, Uncertain

from fakes import FakeSim

WID = "nw_renewal"
WF = 1
CFG = {"cohorts": [], "allocations": {"default": {"welcome_message": {"W1": 1.0}, "voice": {"V1": 1.0},
                                                  "caller_id": {"D1": 0.5, "D2": 0.5}}},
       "prompt_version": "P1", "schedule": {"hour_weights": {}, "lead_preferred_hour": {}}}


def spec(tenant="northwind_life", cap=3, hours=(10, 19), latency=(30, 240), ttl=24):
    return {"workflow_id": WID, "tenant_id": tenant,
            "governance": {"approver_hours": list(hours), "approver_latency_minutes": list(latency),
                           "proposal_ttl_hours": ttl, "apply_window_hours": 2, "max_requests_per_24h": cap,
                           "auto_apply": {"enabled": True, "allowed_dims": ["caller_id"], "max_shift": 0.5}}}


@pytest.fixture()
def sim():
    return FakeSim({WID: CFG})


@pytest.fixture()
def gov(db, sim, settings):
    return Governance(db, sim, settings)


class Audit:
    def __init__(self):
        self.events = []

    def __call__(self, kind, wf, pid, info):
        self.events.append((kind, pid))

    def kinds(self):
        return [k for k, _ in self.events]


def body(gov, sim, now=600, base=None, pid=None):
    cfg = copy.deepcopy(CFG)
    cfg["allocations"]["default"]["voice"] = {"V1": 0.6, "V2": 0.4}
    return {"proposal_id": pid or gov.new_id(WID, now), "workflow_id": WID,
            "base_version": sim.config(WID)["version"] if base is None else base, "proposed_config": cfg,
            "change_summary": "s", "diff": {"voice": 1}, "affected_leads": 1, "dry_run": {"x": 1},
            "impact_score": 0.2, "rationale": "r"}


def state(db, pid):
    return db.q1("SELECT state, approval_id, applied_version FROM proposals WHERE proposal_id=?", (pid,))


# ------------------------------------------------------------------ one open proposal
def test_one_open_proposal_per_workflow(gov, sim, db):
    assert gov.open_proposal(WF) is None
    b = body(gov, sim)
    st, resp = gov.submit(WF, WID, "routine", b, 600)
    assert st == "PENDING" and resp["approval_id"] == "apr_00001"
    op = gov.open_proposal(WF)
    assert op[0] == b["proposal_id"] and op[1] == "PENDING"
    assert gov.open_proposal(2) is None                       # per workflow
    sim.decide("apr_00001", "rejected")
    gov.tick(700, {WF: spec()}, Audit())
    assert gov.open_proposal(WF) is None
    assert state(db, b["proposal_id"])[0] == "REJECTED"


def test_auto_route_does_not_count_as_open_proposal(gov, sim):
    b = body(gov, sim)
    del b["workflow_id"]
    st, _ = gov.auto_apply(WF, WID, "operational", b, 600)
    assert st == "APPLIED" and gov.open_proposal(WF) is None


def test_proposal_ids_are_unique(gov, sim):
    ids = set()
    for i in range(5):
        b = body(gov, sim)
        ids.add(b["proposal_id"])
        gov.submit(WF, WID, "routine", b, 600)
        sim.decide(f"apr_{i + 1:05d}", "rejected")
    assert len(ids) == 5


# ------------------------------------------------------------------ fatigue
def _insert(db, pid, state="PENDING", minute=600, route="approval"):
    with db.tx():
        db.x("INSERT INTO proposals (proposal_id, wf, route, state, kind, base_version, body, created_minute,"
             " updated_minute) VALUES (?,?,?,?,?,?,?,?,?)", (pid, WF, route, state, "routine", 1, "{}", minute, minute))


def test_fatigue_keeps_last_slot_for_incidents(gov, db):
    sp = spec(cap=3)
    assert gov.can_request(WF, sp, 700, emergency=False)[0]
    _insert(db, "a", "EXPIRED")              # expired and rejected still count: the approver saw them
    _insert(db, "b", "APPLIED")
    ok, why = gov.can_request(WF, sp, 700, emergency=False)
    assert not ok and "reserved" in why
    assert gov.can_request(WF, sp, 700, emergency=True)[0]
    _insert(db, "c", "PENDING")
    assert not gov.can_request(WF, sp, 700, emergency=True)[0]
    # trailing window: 24h later the slots are back
    assert gov.can_request(WF, sp, 600 + 1440, emergency=False)[0]


def test_fatigue_ignores_failed_submits_and_auto_route(gov, db):
    sp = spec(cap=2)
    _insert(db, "a", "SUBMIT_FAILED")
    _insert(db, "b", "APPLIED", route="auto")
    assert gov.can_request(WF, sp, 700, emergency=False)[0]


def test_tenant_preference_overrides_policy_cap(gov, db):
    kestrel = spec(tenant="kestrel_finance", cap=4)
    assert gov.fatigue_cap(kestrel) == 2                        # stricter preference wins
    assert gov.fatigue_cap(spec(tenant="northwind_life", cap=4)) == 4
    assert gov.fatigue_cap(spec(tenant="unknown_tenant", cap=4)) == 4
    _insert(db, "a", "PENDING")
    assert not gov.can_request(WF, kestrel, 700, emergency=False)[0]   # 1 of 2: last slot reserved
    assert gov.can_request(WF, kestrel, 700, emergency=True)[0]
    _insert(db, "b", "PENDING")
    assert not gov.can_request(WF, kestrel, 700, emergency=True)[0]


def test_preference_never_loosens_policy(gov):
    gov.s.tenant_preferences["lenient"] = {"max_requests_per_24h": 10}
    assert gov.fatigue_cap(spec(tenant="lenient", cap=3)) == 3


def test_cap_of_one_has_no_reserve(gov, db):
    sp = spec(cap=1)
    assert gov.can_request(WF, sp, 700, emergency=False)[0]
    _insert(db, "a")
    assert not gov.can_request(WF, sp, 700, emergency=True)[0]


def test_rejection_cooldown_blocks_routine_only(gov, db):
    _insert(db, "r", "REJECTED", minute=600)
    ok, why = gov.can_request(WF, spec(cap=4), 700, emergency=False)
    assert not ok and "cool-down" in why
    assert gov.can_request(WF, spec(cap=4), 700, emergency=True)[0]
    assert gov.can_request(WF, spec(cap=4), 600 + 5 * 60, emergency=False)[0]


# ------------------------------------------------------------------ submit window
@pytest.mark.parametrize("minute,ok", [(9 * 60 + 59, False), (10 * 60, True), (18 * 60 + 45, True), (19 * 60, False),
                                       (1440 + 10 * 60 + 30, True), (23 * 60, False)])
def test_submit_window_approver_hours(gov, minute, ok):
    assert gov.submit_window(spec(), minute)[0] is ok


def test_submit_window_tenant_not_before_hour(gov):
    k = spec(tenant="kestrel_finance")
    assert not gov.submit_window(k, 10 * 60 + 30)[0]
    assert gov.submit_window(k, 11 * 60)[0]


def test_submit_window_worst_case_latency_past_expiry(gov):
    short = spec(ttl=12, latency=(30, 240))
    # 18:00 + 240min = 22:00 -> next approver morning 10:00 = 16h later > 12h TTL: would expire unanswered
    ok, why = gov.submit_window(short, 18 * 60)
    assert not ok and "expiry" in why
    assert gov.submit_window(short, 14 * 60)[0]                 # 18:00 worst case, well inside 12h
    assert gov.submit_window(spec(ttl=24), 18 * 60)[0]          # 16h < 24h TTL


# ------------------------------------------------------------------ apply path
def _approved(gov, sim, db):
    b = body(gov, sim)
    gov.submit(WF, WID, "routine", b, 600)
    sim.decide("apr_00001", "approved")
    return b["proposal_id"]


def test_approved_is_applied_once(gov, sim, db):
    pid = _approved(gov, sim, db)
    a = Audit()
    gov.tick(700, {WF: spec()}, a)
    assert state(db, pid) == ("APPLIED", "apr_00001", 2)
    assert a.kinds() == ["approved", "applied"]
    gov.tick(715, {WF: spec()}, a)
    gov.tick(730, {WF: spec()}, a)
    assert sim.calls["apply"] == 1


def test_stale_at_apply_never_calls_apply(gov, sim, db):
    pid = _approved(gov, sim, db)
    sup = copy.deepcopy(CFG)
    sup["prompt_version"] = "P3"
    sim.supervisor_edit(WID, sup)
    a = Audit()
    gov.tick(700, {WF: spec()}, a)
    assert state(db, pid)[0] == "STALE"
    assert sim.calls["apply"] == 0
    assert "stale" in a.kinds()
    assert sim.config(WID)["config"]["prompt_version"] == "P3"      # supervisor's edit untouched
    gov.tick(715, {WF: spec()}, a)
    assert sim.calls["apply"] == 0 and gov.open_proposal(WF) is None


def test_stale_reported_by_apply_endpoint(gov, sim, db):
    pid = _approved(gov, sim, db)
    sim.fail("apply", ApiError(409, "stale_base_version", {"current_version": 9}))
    gov.tick(700, {WF: spec()}, Audit())
    assert state(db, pid)[0] == "STALE"


def test_lapsed_410_becomes_lapsed(gov, sim, db):
    pid = _approved(gov, sim, db)
    sim.fail("apply", ApiError(410, "approval_lapsed", "too late"))
    a = Audit()
    gov.tick(900, {WF: spec()}, a)
    assert state(db, pid)[0] == "LAPSED" and "lapsed" in a.kinds()
    assert gov.open_proposal(WF) is None


def test_remote_lapsed_status_becomes_lapsed(gov, sim, db):
    pid = _approved(gov, sim, db)
    sim.decide("apr_00001", "lapsed")
    gov.tick(900, {WF: spec()}, Audit())
    assert state(db, pid)[0] == "LAPSED" and sim.calls["apply"] == 0


def test_expired_is_terminal(gov, sim, db):
    b = body(gov, sim)
    gov.submit(WF, WID, "routine", b, 600)
    sim.decide("apr_00001", "expired")
    gov.tick(2100, {WF: spec()}, Audit())
    assert state(db, b["proposal_id"])[0] == "EXPIRED" and gov.open_proposal(WF) is None


# ------------------------------------------------------------------ submit errors / uncertainty
def test_stale_at_submit(gov, sim, db):
    b = body(gov, sim, base=0)
    st, resp = gov.submit(WF, WID, "routine", b, 600)
    assert st == "STALE" and resp is None
    assert db.q1("SELECT kind FROM decisions WHERE proposal_id=?", (b["proposal_id"],))[0] == "proposal_failed"


def test_uncertain_submit_that_landed_reconciles_to_pending(gov, sim, db):
    b = body(gov, sim)
    sim.fail("request_approval", Uncertain("read timeout"), after_send=True)
    st, _ = gov.submit(WF, WID, "routine", b, 600)
    assert st == "PENDING"
    assert state(db, b["proposal_id"])[1] == "apr_00001"
    assert len(sim.approvals_) == 1 and sim.calls["request_approval"] == 1   # not re-sent


def test_uncertain_submit_that_never_landed_is_submit_failed(gov, sim, db):
    b = body(gov, sim)
    sim.fail("request_approval", Uncertain("connection reset"), after_send=False)
    st, _ = gov.submit(WF, WID, "routine", b, 600)
    assert st == "SUBMIT_FAILED" and not sim.approvals_
    assert gov.open_proposal(WF) is None
    assert gov.can_request(WF, spec(cap=2), 600, emergency=False)[0]          # didn't burn a fatigue slot


def test_duplicate_proposal_id_on_retry_is_reconciled_not_failed(gov, sim, db):
    b = body(gov, sim)
    sim.request_approval(copy.deepcopy(b))           # an earlier attempt landed but we never saw the response
    sim.decide("apr_00001", "approved")
    st, _ = gov.submit(WF, WID, "routine", b, 600)
    assert st == "APPROVED"
    assert state(db, b["proposal_id"])[:2] == ("APPROVED", "apr_00001")
    assert len(sim.approvals_) == 1
    gov.tick(700, {WF: spec()}, Audit())
    assert state(db, b["proposal_id"])[0] == "APPLIED" and sim.calls["apply"] == 1


def test_uncertain_apply_reconciles_to_applied_without_double_apply(gov, sim, db):
    pid = _approved(gov, sim, db)
    sim.fail("apply", Uncertain("read timeout"), after_send=True)
    a = Audit()
    gov.tick(700, {WF: spec()}, a)
    st, aid, ver = state(db, pid)
    assert st == "APPLIED" and ver == 2               # version recovered from config history
    assert sim.versions[WID][-1]["approval_id"] == aid
    for t in (715, 730, 745):
        gov.tick(t, {WF: spec()}, a)
    assert sim.calls["apply"] == 1
    assert len(sim.versions[WID]) == 2
    assert a.kinds().count("applied") == 1


def test_uncertain_apply_that_did_not_land_is_retried_once(gov, sim, db):
    pid = _approved(gov, sim, db)
    sim.fail("apply", Uncertain("connect"), after_send=False)
    gov.tick(700, {WF: spec()}, Audit())
    assert state(db, pid)[0] == "APPROVED"            # remote still 'approved': safe to retry
    gov.tick(715, {WF: spec()}, Audit())
    assert state(db, pid)[0] == "APPLIED"
    assert sim.calls["apply"] == 2 and len(sim.versions[WID]) == 2


def test_crash_mid_apply_recovered_by_reconcile_all(gov, sim, db):
    """Process died after the apply landed but before the DB update: row is APPLYING on restart."""
    pid = _approved(gov, sim, db)
    gov.tick(650, {WF: spec()}, Audit())               # applied normally...
    with db.tx():                                      # ...then pretend we crashed before recording it
        db.x("UPDATE proposals SET state='APPLYING', applied_version=NULL WHERE proposal_id=?", (pid,))
    applies = sim.calls["apply"]
    notes = gov.reconcile_all({WF: spec()}, 700, Audit())
    assert state(db, pid)[0] == "APPLIED" and state(db, pid)[2] == 2
    assert sim.calls["apply"] == applies
    assert any(pid in n for n in notes)
    assert db.q1("SELECT COUNT(*) FROM decisions WHERE kind='recovery_reconcile'")[0] == 1


def test_crash_mid_submit_recovered_by_reconcile_all(gov, sim, db):
    b = body(gov, sim)
    _insert(db, b["proposal_id"], "SUBMITTING")
    sim.request_approval(copy.deepcopy(b))
    gov.reconcile_all({WF: spec()}, 700, Audit())
    assert state(db, b["proposal_id"])[:2] == ("PENDING", "apr_00001")


# ------------------------------------------------------------------ auto-apply
def _auto_body(gov, sim):
    b = body(gov, sim)
    b["proposed_config"]["allocations"]["default"]["caller_id"] = {"D1": 0.4, "D2": 0.4, "D3": 0.2}
    return b


def test_auto_apply_uncertain_landed_reconciled_via_history(gov, sim, db):
    b = _auto_body(gov, sim)
    sim.fail("auto_apply", Uncertain("timeout"), after_send=True)
    st, _ = gov.auto_apply(WF, WID, "operational", b, 600)
    assert st == "APPLIED"
    assert state(db, b["proposal_id"])[2] == 2
    assert sim.calls["auto_apply"] == 1


def test_auto_apply_uncertain_lost_is_auto_failed(gov, sim, db):
    b = _auto_body(gov, sim)
    sim.fail("auto_apply", Uncertain("connect"), after_send=False)
    st, _ = gov.auto_apply(WF, WID, "operational", b, 600)
    assert st == "AUTO_FAILED" and len(sim.versions[WID]) == 1


def test_auto_apply_403_is_denied(gov, sim, db):
    b = _auto_body(gov, sim)
    sim.fail("auto_apply", ApiError(403, "auto_apply_not_permitted", ["dims not permitted"]))
    st, info = gov.auto_apply(WF, WID, "operational", b, 600)
    assert st == "AUTO_DENIED" and info["error"] == "auto_apply_not_permitted"
