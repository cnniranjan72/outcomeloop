import random

import numpy as np
import pytest

from sim.scenario import FEATURES
from sim.world import WorkflowState

from outcomeloop.cohorts import (FEATURE_COLS, Cohort, bootstrap_cohorts, cohort_id_for, load_cohorts,
                                 membership_sql, save_cohorts)
from outcomeloop.config import Settings

from helpers import add_calls

FEATS = ["lang", "city_tier", "age_band", "value_band"]


class _SimPeople:
    """Just enough of sim.world.WorkflowState to call its own cohort_of / where_mask on our rows."""
    where_mask = WorkflowState.where_mask
    cohort_of = WorkflowState.cohort_of

    def __init__(self, rows):
        self.persons = {f: np.array([FEATURES[f].index(r[f]) for r in rows], dtype=np.int8) for f in FEATS}


def _rand_cohorts(rng):
    out = []
    for i in range(rng.randint(0, 5)):
        where = {}
        for f in rng.sample(FEATS, rng.randint(0, 3)):
            where[f] = rng.sample(FEATURES[f], rng.randint(1, len(FEATURES[f]) - 1 or 1))
        out.append(Cohort(f"c{i}", where))
    return out


@pytest.mark.parametrize("seed", range(5))
def test_membership_sql_matches_simulator_first_match(db, seed):
    rng = random.Random(seed)
    rows = [{f: rng.choice(FEATURES[f]) for f in FEATS} for _ in range(600)]
    with db.tx():
        for i, r in enumerate(rows):
            add_calls(db, 1, 1, 0, minute=i, lang=r["lang"], tier=r["city_tier"], age=r["age_band"],
                      val=r["value_band"])
    people = _SimPeople(rows)
    for _ in range(8):
        cohorts = _rand_cohorts(rng)
        case = membership_sql(db, cohorts)
        ours = [c for (c,) in db.q(f"SELECT {case} FROM calls WHERE wf=1 ORDER BY minute")]
        cfg = {"cohorts": [c.to_config() for c in cohorts]}
        idx = people.cohort_of(cfg, np.arange(len(rows)))
        theirs = ["default" if k == 0 else cohorts[k - 1].cohort_id for k in idx]
        assert ours == theirs


def test_membership_first_match_wins_and_empty_where_matches_all(db):
    add_calls(db, 1, 1, 0, minute=0, lang="ta", age="60+")
    add_calls(db, 1, 1, 0, minute=1, lang="hi", age="60+")
    add_calls(db, 1, 1, 0, minute=2, lang="hi", age="18-30")
    cs = [Cohort("senior_ta", {"age_band": ["60+"], "lang": ["ta"]}), Cohort("senior", {"age_band": ["60+"]})]
    case = membership_sql(db, cs)
    assert [c for (c,) in db.q(f"SELECT {case} FROM calls ORDER BY minute")] == ["senior_ta", "senior", "default"]
    case = membership_sql(db, [Cohort("all", {})] + cs)
    assert {c for (c,) in db.q(f"SELECT {case} FROM calls")} == {"all"}
    assert membership_sql(db, []) == "'default'"


@pytest.mark.parametrize("feat,vals,expected", [
    ("age_band", ["60+"], "age_60p"),
    ("age_band", ["18-30"], "age_18_30"),
    ("age_band", ["46-60", "60+"], "age_46_60_60p"),
    ("lang", ["hi", "en"], "lang_hi_en"),
    ("city_tier", ["1"], "tier_1"),
    ("value_band", ["low"], "value_low"),
])
def test_cohort_id_for(feat, vals, expected):
    cid = cohort_id_for(feat, vals)
    assert cid == expected
    # safe both as a config id and as an SQL string literal inside membership_sql
    assert cid.replace("_", "").isalnum() and cid != "default"


def test_cohort_ids_are_unique_across_features_and_values():
    ids = {cohort_id_for(f, [v]) for f in FEATS for v in FEATURES[f]}
    assert len(ids) == sum(len(FEATURES[f]) for f in FEATS)


def test_save_and_load_cohorts_preserves_order_and_retires_old(db):
    a = [Cohort("b", {"lang": ["hi"]}), Cohort("a", {"lang": ["en"]})]
    with db.tx():
        save_cohorts(db, 1, a, 0, "r1")
    assert [c.cohort_id for c in load_cohorts(db, 1)] == ["b", "a"]
    with db.tx():
        save_cohorts(db, 1, [Cohort("z", {"age_band": ["60+"]})], 10, "r2")
    assert [c.cohort_id for c in load_cohorts(db, 1)] == ["z"]
    assert {r[0] for r in db.q("SELECT status FROM cohorts WHERE cohort_id IN ('a','b')")} == {"retired"}


# ------------------------------------------------------------------ bootstrap (C3)
HOURS = range(9, 21)
AGES = ["18-30", "31-45", "46-60", "60+"]


def _populate(db, rng, pick, *, age_share=None, dials=160):
    """pick(age, lang, hour) -> pickup prob; other features are uniform noise."""
    with db.tx():
        _populate_rows(db, rng, pick, age_share, dials)


def _populate_rows(db, rng, pick, age_share, dials):
    for h in HOURS:
        for a_i, age in enumerate(AGES):
            for lang in ("hi", "en"):
                n = int(dials * (age_share[a_i] * 4 if age_share else 1))
                if n == 0:
                    continue
                k = sum(rng.random() < pick(age, lang, h) for _ in range(n))
                add_calls(db, 1, n, k, minute=-1440 + h * 60, lang=lang, age=age, tier=rng.choice("123"),
                          val=rng.choice(["low", "mid", "high"]))


def _age_profile(age, lang, h):
    # young pick up in the evening, seniors in the morning; language has a main effect only (no hour interaction)
    base = 0.30 if lang == "hi" else 0.20
    if age == "18-30":
        return base * (1.8 if h >= 17 else 0.6)
    if age == "60+":
        return base * (1.8 if h < 12 else 0.6)
    return base


def test_bootstrap_picks_feature_with_different_hour_profile(db):
    _populate(db, random.Random(1), _age_profile)
    cohorts, ev = bootstrap_cohorts(db, 1, Settings(), -10_000, 0)
    assert ev["chosen"] == "age_band"
    assert [c.cohort_id for c in cohorts] == ["age_18_30", "age_31_45", "age_46_60", "age_60p"]
    assert all(set(c.where) == {"age_band"} for c in cohorts)
    # language has a strong main effect but no hour interaction: much weaker per-df evidence than age
    assert ev["features"]["lang"]["g2_per_df"] < ev["features"]["age_band"]["g2_per_df"] / 5


def test_bootstrap_returns_nothing_on_pure_noise(db):
    _populate(db, random.Random(2), lambda age, lang, h: 0.3)
    cohorts, ev = bootstrap_cohorts(db, 1, Settings(), -10_000, 0)
    assert cohorts == [] and ev["chosen"] is None
    assert all(f["p_value"] > 1e-3 for f in ev["features"].values())


def test_bootstrap_merges_small_groups_to_min_share(db):
    s = Settings()
    _populate(db, random.Random(3), _age_profile, age_share=[0.3, 0.3, 0.36, 0.04])  # 60+ is only 4% of dials
    cohorts, ev = bootstrap_cohorts(db, 1, s, -10_000, 0)
    assert ev["chosen"] == "age_band"
    shares = ev["cohorts"]
    assert all(v >= s.min_cohort_share for v in shares.values()), shares
    covered = [v for c in cohorts for v in c.where["age_band"]]
    assert sorted(covered) == sorted(AGES)                     # every value still belongs to exactly one cohort
    assert len(cohorts) == 3
    # 60+ merged with its natural-order neighbour
    assert any(c.where["age_band"] == ["46-60", "60+"] for c in cohorts)


def test_bootstrap_respects_max_cohorts(db):
    s = Settings(max_cohorts=2)
    _populate(db, random.Random(4), _age_profile)
    cohorts, _ = bootstrap_cohorts(db, 1, s, -10_000, 0)
    assert len(cohorts) == 2
    assert sorted(v for c in cohorts for v in c.where["age_band"]) == sorted(AGES)


def test_bootstrap_is_deterministic(db):
    _populate(db, random.Random(1), _age_profile)
    a = bootstrap_cohorts(db, 1, Settings(), -10_000, 0)
    b = bootstrap_cohorts(db, 1, Settings(), -10_000, 0)
    assert a == b


def test_feature_cols_cover_all_features():
    assert set(FEATURE_COLS) == set(FEATURES)
