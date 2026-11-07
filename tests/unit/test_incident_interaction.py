"""Incident x variant interaction: randomised difference-in-differences across variant options."""
from outcomeloop.detectors import incident_interaction

from helpers import add_calls

WF, DAY = 0, 1440
T0 = 3 * DAY          # bad prompt P2 ships here; fix at T1
T1 = T0 + DAY


def _before(db, **kw):
    for v in ("V1", "V2"):
        add_calls(db, WF, 1500, 600, 300, minute=T0 - DAY, spread=DAY, voice=v, prompt="P1", flags=6, **kw)


def test_option_hit_harder_by_the_bad_prompt_is_detected(db):
    _before(db)
    add_calls(db, WF, 1500, 600, 270, minute=T0, spread=DAY, voice="V1", prompt="P2", flags=30)    # 1% -> 5%
    add_calls(db, WF, 1500, 600, 210, minute=T0, spread=DAY, voice="V2", prompt="P2", flags=90)    # 1% -> 15%
    out = incident_interaction(db, WF, "P2", T1)
    assert out["checked"] and out["tests"] > 0
    hit = {(x["dim"], x["option"], x["metric"]) for x in out["interactions"]}
    assert ("voice", "V2", "flag") in hit and all(m == "flag" for _, _, m in hit)


def test_uniform_damage_is_not_an_interaction(db):
    # the bad prompt multiplies flags 5x on every voice, and time-of-day moves everyone alike: no interaction
    _before(db)
    for v in ("V1", "V2"):
        add_calls(db, WF, 1500, 600, 250, minute=T0, spread=DAY, voice=v, prompt="P2", flags=30)
    out = incident_interaction(db, WF, "P2", T1)
    assert out["tests"] > 0 and out["interactions"] == []


def test_thin_incident_is_reported_as_untestable_not_as_no_interaction(db):
    _before(db)
    for v in ("V1", "V2"):
        add_calls(db, WF, 100, 40, 20, minute=T0, spread=120, voice=v, prompt="P2", flags=4)        # 2-hour incident
    out = incident_interaction(db, WF, "P2", T0 + 120)
    assert out["tests"] == 0 and out["dims"]["voice"]["V1"]["insufficient"]


def test_no_calls_on_the_prompt(db):
    assert incident_interaction(db, WF, "P9", T1)["checked"] is False


def test_comparison_group_must_be_the_same_options_in_both_windows(db):
    # W3 only before, W2 only during (a promotion inside the window): W1 must not be compared with W3-then-W2
    for wm, flags in (("W1", 6), ("W3", 6)):
        add_calls(db, WF, 1500, 600, 300, minute=T0 - DAY, spread=DAY, wm=wm, prompt="P1", flags=flags)
    add_calls(db, WF, 1500, 600, 300, minute=T0, spread=DAY, wm="W1", prompt="P2", flags=60)
    add_calls(db, WF, 1500, 600, 300, minute=T0, spread=DAY, wm="W2", prompt="P2", flags=20)
    out = incident_interaction(db, WF, "P2", T1)
    w = out["dims"]["welcome_message"]
    assert w["W1"]["insufficient"] and w["W1"]["reason"] == "no comparison option"
    assert w["W2"]["insufficient"] and w["W3"]["insufficient"]
    assert not [x for x in out["interactions"] if x["dim"] == "welcome_message"]


def test_engagement_change_of_one_option_is_reported_but_never_flagged(db):
    # V2's engagement falls during the window (a decaying winner), flags unchanged: not an incident interaction
    _before(db)
    add_calls(db, WF, 1500, 600, 300, minute=T0, spread=DAY, voice="V1", prompt="P2", flags=30)
    add_calls(db, WF, 1500, 600, 150, minute=T0, spread=DAY, voice="V2", prompt="P2", flags=30)
    out = incident_interaction(db, WF, "P2", T1)
    assert out["dims"]["voice"]["V2"]["engagement"]["z"] < -4
    assert out["dims"]["voice"]["V2"]["engagement"]["descriptive_only"] and out["interactions"] == []
