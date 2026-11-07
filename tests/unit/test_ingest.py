import json

import pytest

from outcomeloop.db import DB
from outcomeloop.ingest import Ingestor

from fakes import EventFactory, FakeSim
from helpers import count

TABLES = ("calls", "leads", "persons", "campaigns", "config_versions", "inbox", "chunks")


def _counts(db):
    return {t: count(db, t) for t in TABLES}


def _world(sim: FakeSim, f: EventFactory):
    """History chunk with leads + calls, then an events chunk with more calls and governance events."""
    hist = [f.campaign(-600, leads=3)]
    hist += [f.lead(1, 101, -600, lang="ta", tier="2", age="60+", value="high"),
             f.lead(2, 102, -600, lang="hi", tier="1", age="18-30", value="low")]
    hist += [f.call(1, 101, -500, connected=True, engaged=False),
             f.call(2, 102, -480, connected=False)]
    sim.add_chunk(hist, kind="history")
    ev = [f.lead(3, 101, 480, lang="ta", tier="2", age="60+", value="high"),   # returning person, new lead
          f.call(1, 101, 540, connected=True, engaged=True, wm="W2", voice="V3", did="D2", prompt="P3", flag=True),
          f.call(3, 101, 560, connected=False),
          f.config_changed(600, 2, actor="supervisor", dims=["voice"]),
          f.approval_decided(610, "apr_00001", "approved")]
    sim.add_chunk(ev, kind="events")


def test_ingest_all_and_idempotent_replay(db):
    sim, f = FakeSim(), EventFactory()
    _world(sim, f)
    ing = Ingestor(db, sim)
    assert ing.ingest_all() == 10
    first = _counts(db)
    assert first == {"calls": 4, "leads": 3, "persons": 2, "campaigns": 1, "config_versions": 1, "inbox": 2,
                     "chunks": 2}
    # same chunk again via the checkpoint: no-op
    assert ing.ingest_chunk(sim.list_chunks("events")[0]) == 0
    assert ing.ingest_all() == 0
    assert _counts(db) == first
    # defence in depth: even with the checkpoint row gone, INSERT OR IGNORE keeps the store identical
    with db.tx():
        db.x("DELETE FROM chunks")
    assert ing.ingest_all() == 10
    assert _counts(db) == first


def test_features_joined_onto_calls_and_variant_encoded(db):
    sim, f = FakeSim(), EventFactory()
    _world(sim, f)
    Ingestor(db, sim).ingest_all()
    row = db.q1("SELECT lang, tier, age, val, wm, voice, did, prompt, conn, eng, flag, cfg_ver FROM calls"
                " WHERE minute=540")
    assert row[:4] == (db.code("lang", "ta"), db.code("city_tier", "2"), db.code("age_band", "60+"),
                       db.code("value_band", "high"))
    assert row[4:8] == (db.code("welcome_message", "W2"), db.code("voice", "V3"), db.code("caller_id", "D2"),
                        db.code("prompt_version", "P3"))
    assert row[8:] == (1, 1, 1, 1)
    # the call in the history chunk got features from a lead event in the same chunk
    assert db.q1("SELECT age FROM calls WHERE minute=-480")[0] == db.code("age_band", "18-30")
    # no call row is ever left without features
    assert db.q1("SELECT COUNT(*) FROM calls WHERE lang<0 OR tier<0 OR age<0 OR val<0")[0] == 0


def test_engaged_call_concludes_lead_once(db):
    sim, f = FakeSim(), EventFactory()
    _world(sim, f)
    sim.add_chunk([f.call(1, 101, 900, connected=True, engaged=True)])   # a later (impossible) re-engagement
    Ingestor(db, sim).ingest_all()
    assert db.q1("SELECT concluded_minute FROM leads WHERE lead=1")[0] == 540   # first conclusion kept
    assert db.q1("SELECT concluded_minute FROM leads WHERE lead=2")[0] is None
    assert db.q1("SELECT concluded_minute FROM leads WHERE lead=3")[0] is None   # connected=False


def test_governance_events_land_in_inbox(db):
    sim, f = FakeSim(), EventFactory()
    _world(sim, f)
    ing = Ingestor(db, sim)
    ing.ingest_all()
    inbox = ing.inbox()
    assert [r[1] for r in inbox] == ["config_changed", "approval_decided"]
    assert json.loads(inbox[0][4])["actor"] == "supervisor"
    assert inbox[0][3] == 600
    assert db.q1("SELECT version, actor, minute FROM config_versions")[:3] == (2, "supervisor", 600)
    ing.mark_done(inbox[0][0])
    assert [r[1] for r in ing.inbox()] == ["approval_decided"]
    # replay does not resurrect a handled event
    with db.tx():
        db.x("DELETE FROM chunks")
    ing.ingest_all()
    assert [r[1] for r in ing.inbox()] == ["approval_decided"]


def test_mid_chunk_failure_is_atomic_and_retry_succeeds(db):
    sim, f = FakeSim(), EventFactory()
    _world(sim, f)
    ing = Ingestor(db, sim)
    ing.ingest_chunk(sim.list_chunks("history")[0])
    before = _counts(db)
    # new values (lang 'kn', voice V4) first seen inside the failing chunk
    bad = [f.lead(9, 109, 700, lang="kn", tier="3", age="46-60", value="mid"),
           f.call(9, 109, 710, connected=True, engaged=True, voice="V4"),
           f.config_changed(720, 3),
           f.call(9, 109, 730, connected=False)]
    meta = sim.add_chunk(bad, explode_after=3)
    with pytest.raises(RuntimeError):
        ing.ingest_chunk(meta)
    assert _counts(db) == before                       # no rows and no checkpoint from the failed chunk
    assert ing.last_chunk() == 0
    # retry in the same process
    assert ing.ingest_chunk(meta) == 4
    assert db.q1("SELECT COUNT(*) FROM persons WHERE person=109")[0] == 1   # person row persisted on retry
    assert db.q1("SELECT lang FROM calls WHERE minute=710")[0] == db.code("lang", "kn")
    assert db.q1("SELECT concluded_minute FROM leads WHERE lead=9")[0] == 710
    # string<->code mapping survived the rollback: a fresh process decodes the same values
    db2 = DB(db.path)
    assert db2.decode("lang", db.code("lang", "kn")) == "kn"
    assert db2.decode("voice", db.code("voice", "V4")) == "V4"
    # and a fresh Ingestor (restart) still knows person 109's features
    assert Ingestor(db2, sim).features.get(db2.code("wf", "wfA"), 109)[0] == db2.code("lang", "kn")
    db2.close()


def test_restart_resumes_from_checkpoint(db):
    sim, f = FakeSim(), EventFactory()
    _world(sim, f)
    Ingestor(db, sim).ingest_chunk(sim.list_chunks("history")[0])
    n_iter = sim.calls["iter_chunk"]
    ing2 = Ingestor(db, sim)               # "restarted" process
    assert [c["chunk"] for c in ing2.pending_chunks()] == [1]
    ing2.ingest_all()
    assert sim.calls["iter_chunk"] == n_iter + 1          # history chunk not re-read
    # feature store rebuilt from the DB: the returning person's new-lead call still gets features
    assert db.q1("SELECT lang FROM calls WHERE minute=560")[0] == db.code("lang", "ta")


def _rollups(db):
    return (db.q("SELECT * FROM did_hour ORDER BY 1, 2, 3"), db.q("SELECT * FROM arm_hour ORDER BY 1, 2, 3, 4, 5, 6, 7, 8, 9"))


def test_rollups_equal_raw_aggregation_and_survive_replay(db):
    sim, f = FakeSim(), EventFactory()
    _world(sim, f)
    ing = Ingestor(db, sim)
    ing.ingest_all()
    did, arm = _rollups(db)
    raw_did = db.q("SELECT wf, (minute - ((minute % 60) + 60) % 60) / 60, did, COUNT(*), SUM(conn) FROM calls"
                   " GROUP BY 1, 2, 3 ORDER BY 1, 2, 3")
    assert did == raw_did and sum(r[9] for r in arm) == count(db, "calls")
    # replay with the checkpoint gone: rows are kept by INSERT OR IGNORE and rollups are recomputed, not added
    with db.tx():
        db.x("DELETE FROM chunks")
    ing.ingest_all()
    assert _rollups(db) == (did, arm)


def test_backfill_rebuilds_the_same_rollups(db):
    sim, f = FakeSim(), EventFactory()
    _world(sim, f)
    Ingestor(db, sim).ingest_all()
    before = _rollups(db)
    with db.tx():
        db.x("DELETE FROM did_hour")
        db.x("DELETE FROM arm_hour")
    Ingestor(db, sim)                      # startup on an old store: backfill from the call rows
    assert _rollups(db) == before
