import sqlite3

import pytest

from outcomeloop.db import DB


def test_decisions_are_append_only(db):
    with db.tx():
        did = db.decide(10, 1, "test", "first", evidence={"a": 1}, proposal_id="p1")
        db.decide(11, 1, "test", "second")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.x("UPDATE decisions SET summary='rewritten' WHERE decision_id=?", (did,))
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.x("DELETE FROM decisions WHERE decision_id=?", (did,))
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.x("DELETE FROM decisions")
    assert db.q("SELECT summary FROM decisions ORDER BY decision_id") == [("first",), ("second",)]


def test_append_only_survives_reopen(tmp_path):
    p = tmp_path / "a.db"
    d = DB(p)
    with d.tx():
        d.decide(0, None, "k", "s")
    d.close()
    d = DB(p)        # schema script re-run must not drop/replace the triggers
    with pytest.raises(sqlite3.IntegrityError):
        d.x("UPDATE decisions SET kind='x'")
    d.close()


def test_failed_transaction_rolls_back_decisions_too(db):
    with pytest.raises(RuntimeError):
        with db.tx():
            db.decide(0, 1, "k", "lost")
            raise RuntimeError("boom")
    assert db.q1("SELECT COUNT(*) FROM decisions")[0] == 0


def test_nested_tx_commits_once_at_outer(db):
    with pytest.raises(RuntimeError):
        with db.tx():
            with db.tx():
                db.kv_set("x", 1)
            raise RuntimeError("outer fails after inner 'commits'")
    assert db.kv_get("x") is None


def test_codes_stable_and_rollback_does_not_leak_into_cache(db, tmp_path):
    a = db.code("voice", "V1")
    assert db.code("voice", "V1") == a and db.decode("voice", a) == "V1"
    assert db.code("voice", None) == -1
    with pytest.raises(RuntimeError):
        with db.tx():
            db.code("voice", "V9")
            raise RuntimeError
    # V9 was never persisted: the next use must persist it, and no two values may share a code
    with db.tx():
        c9 = db.code("voice", "V9")
        c2 = db.code("voice", "V2")
    assert c9 != c2
    fresh = DB(db.path)
    assert fresh.decode("voice", c9) == "V9" and fresh.decode("voice", c2) == "V2"
    assert fresh.code("voice", "V1") == a
    fresh.close()


def test_kv_and_meta_round_trip(db):
    db.kv_set("k", {"a": [1, 2]})
    db.kv_set("k", {"a": [3]})
    assert db.kv_get("k") == {"a": [3]}
    assert db.kv_get("missing", 5) == 5
    db.meta_set("scenario", "x")
    assert db.meta_get("scenario") == "x" and db.meta_get("nope") is None
