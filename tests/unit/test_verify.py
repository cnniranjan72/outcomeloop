"""The integrity verifier must catch what it claims to catch: each test injects one fault into a consistent store and
asserts the matching check turns INVALID or INCOMPLETE (a clean report is only meaningful if faults are visible).
Replay must recompute experiment statistics from raw rows and flag a stored summary that disagrees."""
import json

import pytest

from helpers import add_calls
from outcomeloop.verify import INCOMPLETE, INVALID, VALID, render_verify, replay, verify_store

WF = 0


def _store(db):
    """A small consistent store: 2 chunks, a business-default version, one approved controller change, one
    supervisor edit with its acknowledgement, one experiment with a winner."""
    db.x("INSERT INTO workflows (wf, workflow_id, tenant_id, spec) VALUES (0, 'wfA', 't1', '{}')")
    db.x("INSERT INTO chunks VALUES (0, 'history', 10, 1, 10, 0, 0, 0)")
    db.x("INSERT INTO chunks VALUES (1, 'events', 5, 11, 15, 60, 0, 0)")
    for v, actor, pid, aid, dims in ((1, "business_default", None, None, "[]"),
                                     (2, "controller_approved", "ol-1", "apr_1", '["voice"]'),
                                     (3, "supervisor", None, None, '["prompt_version"]')):
        db.x("INSERT INTO config_versions (wf, version, actor, minute, changed_dims, proposal_id, approval_id, event_id)"
             " VALUES (?,?,?,?,?,?,?,?)", (WF, v, actor, v * 100, dims, pid, aid, v))
    db.x("INSERT INTO proposals (proposal_id, wf, route, state, kind, base_version, body, approval_id, applied_version,"
         " created_minute, updated_minute) VALUES ('ol-1', 0, 'approval', 'APPLIED', 'routine', 1, '{}', 'apr_1', 2,"
         " 150, 200)")
    db.x("INSERT INTO experiments VALUES ('exp-0-voice-1', 0, 'voice', 'promoted', ?, 0, 200)",
         (json.dumps({"dim": "voice", "wf": 0, "arms": ["V1", "V2"], "versions": [2], "start_minute": 120}),))
    db.decide(100, WF, "experiment_designed", "voice: test", experiment_id="exp-0-voice-1")
    db.decide(190, WF, "experiment_winner", "voice: winner V2", experiment_id="exp-0-voice-1")
    db.decide(200, WF, "proposal_applied", "ol-1: applied", proposal_id="ol-1")
    db.decide(300, WF, "supervisor_edit", "supervisor changed prompt", config_version=3)


def status(db, name):
    return next(c for c in verify_store(db) if c.name == name).status


def test_consistent_store_verifies_valid(db):
    _store(db)
    checks = verify_store(db)
    assert all(c.status == VALID for c in checks), [(c.name, c.status, c.records) for c in checks]
    assert render_verify(checks)[1] == 0


@pytest.mark.parametrize("fault, check, expected", [
    ("DELETE FROM chunks WHERE chunk=0", "event sequence", INVALID),
    ("UPDATE chunks SET first_event_id=12 WHERE chunk=1", "event sequence", INVALID),
    ("INSERT INTO config_versions (wf, version, actor, minute, changed_dims) VALUES (0, 4, 'controller_auto', 400, '[]')",
     "every controller change = one applied proposal", INVALID),
    ("UPDATE proposals SET approval_id='apr_X'", "every controller change = one applied proposal", INVALID),
    ("INSERT INTO config_versions (wf, version, actor, minute, changed_dims) VALUES (0, 4, 'supervisor', 400, '[]')",
     "every supervisor edit acknowledged", INVALID),
    ("INSERT INTO proposals (proposal_id, wf, route, state, kind, base_version, body, created_minute, updated_minute)"
     " VALUES ('ol-2', 0, 'approval', 'APPLYING', 'routine', 3, '{}', 300, 300)", "proposal states", INCOMPLETE),
    ("UPDATE experiments SET status='rolled_back'", "experiment lifecycles complete", INVALID),
    ("INSERT INTO incidents VALUES ('inc-1', 0, 'hallucination', 'closed', 100, 200, '{}')",
     "incidents closed with a reason", INVALID),
    ("INSERT INTO config_versions (wf, version, actor, minute, changed_dims) VALUES (0, 6, 'business_default', 600, '[]')",
     "config history contiguous", INCOMPLETE),
    ("INSERT INTO credits_ledger (minute, wf, kind, purpose, state, cost) VALUES (10, 0, 'validation', 'probe', 'sent', 1)",
     "credits and events settled", INCOMPLETE),
    ("DROP TRIGGER decisions_append_only_d", "audit log append-only and ordered", INVALID),
])
def test_each_injected_fault_is_reported(db, fault, check, expected):
    _store(db)
    db.x(fault)
    assert status(db, check) == expected
    assert render_verify(verify_store(db))[1] == (1 if expected == INVALID else 2)


def test_orphan_decision_reference_is_invalid(db):
    _store(db)
    db.decide(500, WF, "proposal_applied", "ghost", proposal_id="ol-ghost")
    assert status(db, "decision references resolve") == INVALID


def _experiment_with_calls(db, stored_v2_engaged):
    db.x("INSERT INTO workflows (wf, workflow_id, tenant_id, spec) VALUES (0, 'wfA', 't1', '{}')")
    db.x("INSERT INTO experiments VALUES ('exp-0-voice-1', 0, 'voice', 'running', ?, 0, 700)",
         (json.dumps({"dim": "voice", "wf": 0, "arms": ["V1", "V2"], "versions": [2], "start_minute": 120}),))
    add_calls(db, 0, 3000, 1000, 400, minute=130, spread=500, voice="V1", cfg_ver=2)   # 0.40
    add_calls(db, 0, 1500, 500, 250, minute=130, spread=500, voice="V2", cfg_ver=2)    # 0.50
    add_calls(db, 0, 900, 300, 300, minute=130, spread=500, voice="V2", cfg_ver=1)     # other version: excluded
    ev = {"alpha_look": 0.02, "significant": ["V2"],
          "incumbent": {"option": "V1", "connected": 1000, "engaged": 400},
          "arms": {"V2": {"connected": 500, "engaged": stored_v2_engaged, "z": 3.68, "p": 0.000118}}}
    db.decide(700, 0, "experiment_winner", "voice: winner V2", evidence=ev, experiment_id="exp-0-voice-1")
    return db.q1("SELECT decision_id FROM decisions")[0]


def test_replay_recomputes_from_raw_calls_and_confirms(db):
    out = replay(db, _experiment_with_calls(db, 250))
    assert "VALID: incumbent V1 stored 1000/400" in out and "recounted 1000/400" in out
    assert "VALID: V2 stored n 500 z 3.68" in out and "VALID: Holm" in out and "\nINVALID:" not in out


def test_replay_flags_a_stored_summary_that_disagrees_with_the_raw_rows(db):
    out = replay(db, _experiment_with_calls(db, 260))         # stored engaged count tampered
    assert "INVALID: V2 stored" in out


def test_replay_is_read_only(db):
    did = _experiment_with_calls(db, 250)
    before = db.q1("SELECT COUNT(*) FROM decisions")[0], db.q1("SELECT total_changes()")[0]
    replay(db, did)
    assert db.q1("SELECT COUNT(*) FROM decisions")[0] == before[0]
    assert db.q1("SELECT total_changes()")[0] == before[1]


def test_replay_reruns_the_caller_id_detector_and_matches_or_flags(db):
    from outcomeloop.config import Settings
    from outcomeloop.detectors import did_health, did_own_past
    db.x("INSERT INTO workflows (wf, workflow_id, tenant_id, spec) VALUES (0, 'wfA', 't1', ?)",
         (json.dumps({"options": {"caller_id": ["D1", "D2"]}}),))
    now = 3 * 1440 + 12 * 60
    add_calls(db, 0, 2000, 600, 300, minute=now - 1440, spread=1440, did="D1")      # pickup 0.30
    add_calls(db, 0, 2000, 300, 150, minute=now - 1440, spread=1440, did="D2")      # pickup 0.15: degraded
    s = Settings()
    h = did_health(db, 0, ["D1", "D2"], now, s, None, None, did_own_past(db, 0, (now // 360) * 360, s))["D2"]
    assert h["state"] == "degraded"
    db.decide(now, 0, "did_health", "caller ID D2: healthy -> degraded", evidence=h)
    ok = replay(db, db.q1("SELECT MAX(decision_id) FROM decisions")[0])
    assert "VALID: slow window" in ok and "VALID: state stored degraded, recomputed degraded" in ok
    h["windows"]["slow"]["z"] = -9.99                                                    # tampered evidence
    db.decide(now, 0, "did_health", "caller ID D2: healthy -> degraded", evidence=h)
    assert "INVALID: slow window" in replay(db, db.q1("SELECT MAX(decision_id) FROM decisions")[0])
