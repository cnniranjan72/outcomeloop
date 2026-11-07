"""Paging rules (views.alerts): each fires on its condition and stays quiet otherwise."""
from outcomeloop import views


def _chunk(db, until):
    db.x("INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?)", (until, "events", 1, 1, 1, until, 0.0, 0.0))


def test_all_clear_on_healthy_store(db):
    _chunk(db, 600)
    text, firing = views.alerts(db)
    assert firing == [] and "all clear" in text


def test_approved_but_unapplied_pages(db):
    _chunk(db, 900)
    db.x("INSERT INTO proposals (proposal_id, wf, route, state, kind, base_version, body, created_minute,"
         " updated_minute) VALUES ('p1', 1, 'approval', 'APPROVED', 'routine', 1, '{}', 700, 800)")
    _, firing = views.alerts(db)
    assert [a["rule"] for a in firing] == ["approval_not_applied"]


def test_stuck_incident_and_low_credits_page(db):
    _chunk(db, 1000)
    db.x("INSERT INTO incidents VALUES ('i1', 1, 'hallucination', 'open', 600, NULL, '{}')")
    db.kv_set("credits_start", 200)
    db.metric(1000, "credits_remaining", 85)
    rules = {a["rule"] for a in views.alerts(db)[1]}
    assert rules == {"incident_stuck", "credits_low"}


def test_ingest_lag_pages_only_during_dialling_hours(db):
    _chunk(db, 3 * 60)                       # 03:00: no calls at night, lag is normal
    db.metric(3 * 60, "ingest_lag_minutes", 300)
    assert views.alerts(db)[1] == []
    _chunk(db, 13 * 60)                      # 13:00: lag means the loop is blind
    db.metric(13 * 60, "ingest_lag_minutes", 120)
    assert [a["rule"] for a in views.alerts(db)[1]] == ["ingest_stalled"]
