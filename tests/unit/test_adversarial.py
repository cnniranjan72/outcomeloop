"""Adversarial tests: each one attacks a failure mode with a test double or a real process (never by modifying the
simulator). See docs/ADVERSARIAL_TESTING.md for what each found and how it was resolved."""
import copy
import os
import subprocess
import sys

import httpx
import pytest

from outcomeloop.governance import Governance
from outcomeloop.instancelock import AlreadyRunning, InstanceLock
from outcomeloop.simclient import SimClient, Uncertain

from fakes import FakeSim
from test_governance import CFG, WF, WID, Audit, body, spec, state

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src"))


# ------------------------------------------------------------------ the apply-boundary crash matrix
# Boundaries between "approval received" and "application persisted". A "crash" = we abandon the in-memory flow at
# that point and run restart recovery (reconcile_all, then governance ticks) on the same store.
@pytest.fixture()
def gov(db, settings):
    return Governance(db, FakeSim({WID: CFG}), settings)


def _approved(gov, db):
    b = body(gov, gov.sim)
    gov.submit(WF, WID, "routine", b, 600)
    gov.sim.decide("apr_00001", "approved")
    return b["proposal_id"]


def _recover(gov):
    a = Audit()
    gov.reconcile_all({WF: spec()}, 700, a)
    gov.tick(715, {WF: spec()}, a)
    gov.tick(730, {WF: spec()}, a)
    return a


def test_crash_after_approval_seen_before_any_local_write(gov, db):
    pid = _approved(gov, db)                       # our row still PENDING, remote approved
    _recover(gov)
    assert state(db, pid)[0] == "APPLIED" and gov.sim.calls["apply"] == 1


def test_crash_after_applying_intent_committed_before_http(gov, db):
    pid = _approved(gov, db)
    with db.tx():
        db.x("UPDATE proposals SET state='APPLYING' WHERE proposal_id=?", (pid,))   # intent persisted, never sent
    _recover(gov)
    assert state(db, pid)[0] == "APPLIED" and gov.sim.calls["apply"] == 1       # sent exactly once, on recovery


def test_crash_after_remote_apply_before_local_commit(gov, db):
    pid = _approved(gov, db)
    gov.sim.apply(WID, "apr_00001")                # the simulator applied it...
    with db.tx():                                  # ...but our process died before recording the result
        db.x("UPDATE proposals SET state='APPLYING' WHERE proposal_id=?", (pid,))
    calls_before = gov.sim.calls["apply"]
    _recover(gov)
    st = state(db, pid)
    assert st[0] == "APPLIED" and st[2] == gov.sim.config(WID)["version"]       # version recovered from history
    assert gov.sim.calls["apply"] == calls_before                                # never applied twice


def test_lost_response_on_apply_reconciles_without_resending(gov, db):
    pid = _approved(gov, db)
    gov.sim.fail("apply", Uncertain("lost"), after_send=True)                    # applied remotely, reply lost
    gov.tick(700, {WF: spec()}, Audit())
    gov.tick(715, {WF: spec()}, Audit())
    assert state(db, pid)[0] == "APPLIED" and gov.sim.calls["apply"] == 1


def test_supervisor_edit_between_approval_and_apply_is_never_overwritten(gov, db):
    pid = _approved(gov, db)
    sup = copy.deepcopy(CFG)
    sup["prompt_version"] = "P3"
    gov.sim.supervisor_edit(WID, sup)
    _recover(gov)
    assert state(db, pid)[0] == "STALE" and gov.sim.calls["apply"] == 0
    assert gov.sim.config(WID)["config"]["prompt_version"] == "P3"


def test_repeated_restarts_are_idempotent(gov, db):
    pid = _approved(gov, db)
    for _ in range(5):
        _recover(gov)
    assert state(db, pid)[0] == "APPLIED" and gov.sim.calls["apply"] == 1


def test_orphan_approval_without_local_context_is_never_applied(gov, db):
    b = body(gov, gov.sim)
    gov.sim.request_approval(b)                   # landed remotely; our store has no row (lost / rebuilt state)
    gov.sim.decide("apr_00001", "approved")
    notes = gov.reconcile_all({WF: spec()}, 700, Audit())
    gov.tick(715, {WF: spec()}, Audit())
    assert any("WITHDRAWN" in n for n in notes)
    assert state(db, b["proposal_id"])[0] == "WITHDRAWN" and gov.sim.calls["apply"] == 0
    assert gov.requests_last_24h(WF, 715) == 1    # still counts toward the approver's budget


# ------------------------------------------------------------------ HTTP faults
def _client(handler, retries=3):
    c = SimClient("http://sim", retries=retries)
    c.http = httpx.Client(base_url="http://sim", transport=httpx.MockTransport(handler))
    return c


def test_429_on_read_is_retried_and_honours_retry_after(monkeypatch):
    slept = []
    monkeypatch.setattr("outcomeloop.simclient.time.sleep", lambda s: slept.append(s))
    n = {"i": 0}

    def h(req):
        n["i"] += 1
        return httpx.Response(429, headers={"retry-after": "2"}) if n["i"] == 1 else httpx.Response(200, json={"ok": 1})
    assert _client(h).state() == {"ok": 1} and slept == [2.0]


def test_429_on_write_is_retried_because_it_was_not_processed(monkeypatch):
    monkeypatch.setattr("outcomeloop.simclient.time.sleep", lambda s: None)
    n = {"i": 0}

    def h(req):
        n["i"] += 1
        return httpx.Response(429) if n["i"] == 1 else httpx.Response(200, json={"approval_id": "apr_1"})
    assert _client(h).request_approval({"proposal_id": "p"})["approval_id"] == "apr_1" and n["i"] == 2


def test_backoff_has_jitter_and_a_cap():
    vals = {round(SimClient._backoff(3), 6) for _ in range(50)}
    assert len(vals) > 10 and max(vals) <= 4.0 and min(vals) >= 0
    assert max(SimClient._backoff(20) for _ in range(50)) <= 10.0


def test_truncated_chunk_is_refetched_whole_never_half_ingested(monkeypatch):
    monkeypatch.setattr("outcomeloop.simclient.time.sleep", lambda s: None)
    n = {"i": 0}

    def h(req):
        n["i"] += 1
        if n["i"] == 1:
            content = b'{"type":"lead","event_id":1}\n{"type":"call","eve'
        else:
            content = b'{"type":"lead","event_id":1}\n{"type":"call","event_id":2}\n'
        return httpx.Response(200, content=content)
    events = list(_client(h).iter_chunk(0))
    assert [e["event_id"] for e in events] == [1, 2] and n["i"] == 2


def test_unexpected_503_on_write_is_uncertain_not_failure():
    with pytest.raises(Uncertain):
        _client(lambda r: httpx.Response(503)).auto_apply("wf", {"proposal_id": "p"})


# ------------------------------------------------------------------ concurrency: one controller per state file
def test_second_controller_process_is_refused_and_lock_survives_sigkill(tmp_path):
    db = tmp_path / "state.db"
    code = ("import sys, time; sys.path.insert(0, %r)\n"
            "from outcomeloop.instancelock import InstanceLock\n"
            "lock = InstanceLock(%r).acquire(); print('held', flush=True); time.sleep(60)\n") % (SRC, str(db))
    holder = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "held"
        with pytest.raises(AlreadyRunning):
            InstanceLock(str(db)).acquire()
    finally:
        holder.kill()                                  # SIGKILL / TerminateProcess: no cleanup code runs
        holder.wait()
    InstanceLock(str(db)).acquire().release()          # the OS released it: restart recovery is not blocked


# ------------------------------------------------------------------ corrupted local state
def test_corrupted_state_file_is_archived_and_rebuilt(tmp_path, settings):
    from outcomeloop.controller import Controller
    db = tmp_path / "state.db"
    db.write_bytes(b"this is not a sqlite database" * 100)
    c = Controller.__new__(Controller)
    c.s = settings
    c.s.db_path = str(db)
    c.sim = FakeSim({WID: CFG})
    c.sim.state = lambda: {"scenario": "x", "sim_minute": 0}
    c._prepare_db()
    assert not db.exists() and list(tmp_path.glob("state.*.corrupt"))
    assert c._rebuilt_from_corrupt
