"""Per-person call time is a randomised experiment: deterministic arms, decisions only on enough evidence."""
import pytest

from outcomeloop.config import Settings
from outcomeloop.persontime import PersonTime, arm_of

from helpers import add_calls

WF, WID, DAY = 1, "wfA", 1440


def test_arms_are_deterministic_and_balanced():
    arms = [arm_of(WID, p, 0.5) for p in range(4000)]
    assert arms == [arm_of(WID, p, 0.5) for p in range(4000)]          # reproducible
    assert 0.46 < arms.count("treatment") / 4000 < 0.54
    assert sum(arm_of(WID, p, 0.9) == "treatment" for p in range(4000)) / 4000 > 0.86


def _setup(db, start=0):
    pt = PersonTime(db, Settings())
    db.kv_set(f"ptime:{WF}", {"status": "testing", "start_minute": start, "treat_share": 0.5, "looks": []})
    with db.tx():
        db.conn.executemany("INSERT INTO ptime_members VALUES (?,?,?,?,?)",
                            [(WF, 1, "treatment", 10, start), (WF, 2, "control", 10, start)])
    return pt


def _dials(db, person, n, conn, start):
    from outcomeloop.db import DB  # noqa
    from helpers import _EID
    rows = []
    for i in range(n):
        _EID[0] += 1
        rows.append((WF, start + i % (2 * DAY), _EID[0], person, person, 1, 1, 0, 0, 0, 0, 0,
                     1 if i < conn else 0, 0, 0, 0, 0, 0, 0))
    with db.tx():
        db.conn.executemany("INSERT INTO calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)


def test_clear_pickup_lift_expands(db):
    pt = _setup(db)
    _dials(db, 1, 1000, 400, 0)       # treatment 40 %
    _dials(db, 2, 1000, 300, 0)       # control 30 %
    res = pt.look(WF, 2 * DAY)
    assert res["action"] == "expand" and pt.state(WF)["treat_share"] == 0.9


def test_clear_pickup_loss_stops(db):
    pt = _setup(db)
    _dials(db, 1, 1000, 250, 0)
    _dials(db, 2, 1000, 330, 0)
    assert pt.look(WF, 2 * DAY)["action"] == "stop_harm" and pt.state(WF)["status"] == "stopped"


def test_insufficient_evidence_never_decides_and_horizon_stops(db):
    pt = _setup(db)
    _dials(db, 1, 300, 120, 0)        # < 400 dials per arm
    _dials(db, 2, 300, 90, 0)
    assert pt.look(WF, 2 * DAY)["action"] == "continue"
    assert pt.look(WF, 5 * DAY)["action"] == "stop_no_evidence"


def test_only_policy_permitted_auto_apply_workflows_are_eligible():
    pt = PersonTime.__new__(PersonTime)
    ok = {"governance": {"auto_apply": {"enabled": True, "allowed_dims": ["schedule", "caller_id"]}}}
    no = {"governance": {"auto_apply": {"enabled": False, "allowed_dims": []}}}
    assert pt.eligible(ok, set()) and not pt.eligible(no, set())
    assert not pt.eligible(ok, {"schedule"})                     # a supervisor set the schedule: hands off
