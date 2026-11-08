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


def test_persistent_low_rate_error_on_one_workflow_pages(db):
    _chunk(db, 600)
    for m in (450, 500, 560):
        db.decide(m, 3, "error", "decision step failed: KeyError")
    assert "workflow_stuck" in {a["rule"] for a in views.alerts(db)[1]}


def test_audit_kind_prefix_wildcard_matches_a_lifecycle_and_escapes_underscore(db):
    for k in ("experiment_designed", "experiment_winner", "experimentXwinner", "did_health"):
        db.decide(60, None, k, f"row {k}")
    out = views.audit(db, None, "experiment_*", 50)
    assert "experiment_designed" in out and "experiment_winner" in out
    assert "experimentXwinner" not in out and "did_health" not in out       # '_' is literal, not a LIKE wildcard
    assert views.audit(db, None, "did_health", 50).count("did_health") == 2  # exact kind unchanged (kind + summary)


def test_customer_view_names_what_was_heard_and_who_set_it(db):
    from helpers import add_calls
    db.x("INSERT INTO workflows (wf, workflow_id) VALUES (0, 'wfA')") if not db.q1("SELECT 1 FROM workflows WHERE workflow_id='wfA'") else None
    wf = db.q1("SELECT wf FROM workflows WHERE workflow_id='wfA'")[0]
    db.x("INSERT INTO config_versions (wf, version, actor, minute, changed_dims, proposal_id, approval_id, event_id)"
         " VALUES (?,1,'controller_approved',0,'[]','ol-1','apr_1',1)", (wf,))
    add_calls(db, wf, 1, 1, 1, minute=600, voice="V3")
    person = db.q1("SELECT person FROM calls")[0]
    out = views.customer(db, f"wfA:p{person}", None)
    assert "variant W1 V3 P1 from D1" in out and "engaged" in out and "by controller_approved · ol-1 · apr_1" in out


def test_customer_view_labels_a_supervisor_edit_as_outside_governance(db):
    from helpers import add_calls
    db.x("INSERT INTO workflows (wf, workflow_id) VALUES (5, 'wfS')")
    db.x("INSERT INTO config_versions (wf, version, actor, minute, changed_dims, proposal_id, approval_id, event_id)"
         " VALUES (5,2,'supervisor',0,'[\"prompt_version\"]',NULL,NULL,9)")
    add_calls(db, 5, 1, 1, 0, minute=600, prompt="P2", cfg_ver=2)
    person = db.q1("SELECT person FROM calls WHERE wf=5")[0]
    out = views.customer(db, f"wfS:p{person}", None)
    assert "by supervisor (direct edit, outside governance)" in out and "None" not in out


def test_decision_view_shows_reasoning_evidence_links_and_neighbours(db):
    db.x("INSERT INTO workflows (wf, workflow_id) VALUES (7, 'wfD')")
    db.x("INSERT INTO incidents VALUES ('inc-1', 7, 'hallucination', 'closed', 600, 900, '{}')")
    db.decide(500, 7, "supervisor_edit", "supervisor changed prompt")
    db.decide(600, 7, "incident_opened", "hallucination incident on prompt P2", evidence={"trigger": "validation_probe",
              "failure_ucb95": 0.09}, incident_id="inc-1", reasoning="population evidence")
    db.decide(700, 7, "incident_fix_selected", "fix = P1")
    did = db.q1("SELECT decision_id FROM decisions WHERE kind='incident_opened'")[0]
    out = views.decision(db, did)
    assert "incident_opened" in out and "Why:   population evidence" in out
    assert '"failure_ucb95": 0.09' in out and "incident inc-1: hallucination, closed" in out
    assert "supervisor_edit" in out.split("After:")[0] and "incident_fix_selected" in out.split("After:")[1]
    assert views.decision(db, 99999) == "no decision #99999"
    assert f"#{did}" in views.audit(db, "wfD", "incident_*", 10)


def test_lifecycle_links_experiment_decisions_and_the_proposals_that_carried_it(db):
    import json as _j
    db.x("INSERT INTO workflows (wf, workflow_id) VALUES (8, 'wfL')")
    db.x("INSERT INTO experiments VALUES ('exp-8-voice-0', 8, 'voice', 'promoted', ?, 0, 900)",
         (_j.dumps({"dim": "voice", "arms": ["V1", "V2"], "incumbent": "V1", "winner": "V2", "alpha_spent": 0.02}),))
    db.decide(0, 8, "experiment_designed", "voice: test", experiment_id="exp-8-voice-0",
              evidence={"design": {"V1": 0.6, "V2": 0.4}, "n_plan_per_arm": 900, "p_base": 0.5, "achieved_mde_rel": 0.1})
    db.decide(600, 8, "experiment_winner", "voice: winner V2", experiment_id="exp-8-voice-0",
              evidence={"t": 0.8, "alpha_look": 0.02, "winner": "V2", "significant": ["V2"], "guardrail_blocked": [],
                        "incumbent": {"option": "V1", "eng_rate": 0.5, "connected": 2000},
                        "arms": {"V2": {"lift_rel": 0.12, "z": 3.1, "p": 0.001, "connected": 900}}})
    db.x("INSERT INTO proposals (proposal_id, wf, route, state, kind, base_version, body, created_minute, updated_minute)"
         " VALUES ('ol-8-1', 8, 'approval', 'APPLIED', 'routine', 3, ?, 600, 700)",
         (_j.dumps({"evidence": {"experiments": {"exp-8-voice-0": {}}}}),))
    db.decide(700, 8, "proposal_applied", "ol-8-1: applied", proposal_id="ol-8-1", evidence={"version": 4})
    out = views.lifecycle(db, "exp-8-voice-0")
    assert "planned n 900" in out and "V2: +12.0% engagement (z 3.1" in out and "significant after Holm: ['V2']" in out
    assert "live as config v4" in out and "ol-8-1" in out
    assert views.lifecycle(db, "exp-nope").startswith("no experiment")
