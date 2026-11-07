"""The controller's changed_dims / max_shift must agree with the governance boundary's (sim.world) on any
normalised config. If they disagree the controller either sends auto-apply requests that the simulator rejects
(403s logged against us) or thinks a change is a no-op when it isn't. The controller must not import sim; the
test may, to check parity."""
import copy
import random

import pytest

from sim.scenario import FEATURES
from sim.world import changed_dims as sim_changed_dims
from sim.world import max_shift as sim_max_shift
from sim.world import normalise_config

from outcomeloop.controller import _fixpoint, canonical_config, changed_dims, max_shift

SPEC = {
    "options": {"welcome_message": ["W1", "W2", "W3"], "voice": ["V1", "V2", "V3", "V4"],
                "caller_id": ["D1", "D2", "D3"], "prompt_version": ["P1", "P3", "P4"]},
    "dialling_window": [9, 21],
}
DIMS = ("welcome_message", "voice", "caller_id")
EMPTY = {"allocations": {}}
COHORT_POOL = ["young", "senior", "hi_speakers", "tier1", "rich"]


def _rand_dist(rng, opts):
    k = rng.randint(1, len(opts))
    chosen = rng.sample(opts, k)
    # mix of "nice" weights (exact equality likely on re-draw) and arbitrary floats
    if rng.random() < 0.5:
        return {o: rng.choice([1, 1, 2, 0.5]) for o in chosen}
    return {o: round(rng.random() + 0.01, 3) for o in chosen}


def _rand_where(rng):
    where = {}
    for feat in rng.sample(list(FEATURES), rng.randint(0, 2)):
        where[feat] = rng.sample(FEATURES[feat], rng.randint(1, len(FEATURES[feat])))
    return where


def _rand_config(rng):
    ids = rng.sample(COHORT_POOL, rng.randint(0, 3))
    cfg = {"cohorts": [{"id": i, "where": _rand_where(rng)} for i in ids],
           "allocations": {"default": {d: _rand_dist(rng, SPEC["options"][d]) for d in DIMS}},
           "prompt_version": rng.choice(SPEC["options"]["prompt_version"]),
           "schedule": {"hour_weights": {}, "lead_preferred_hour": {}}}
    for i in ids:
        if rng.random() < 0.6:
            cfg["allocations"][i] = {d: _rand_dist(rng, SPEC["options"][d])
                                     for d in rng.sample(DIMS, rng.randint(1, 3))}
    for key in ["default"] + ids:
        if rng.random() < 0.3:
            cfg["schedule"]["hour_weights"][key] = {str(h): rng.choice([0.25, 1, 2, 4]) for h in range(9, 21)
                                                   if rng.random() < 0.8}
    return cfg


def _mutate(rng, cfg):
    new = copy.deepcopy(cfg)
    what = rng.choice(["nothing", "dist", "cohort_dist", "prompt", "schedule", "cohorts", "reweight_same", "several"])
    steps = [what] if what != "several" else rng.sample(["dist", "cohort_dist", "prompt", "schedule"], 2)
    for w in steps:
        if w == "dist":
            d = rng.choice(DIMS)
            new["allocations"]["default"][d] = _rand_dist(rng, SPEC["options"][d])
        elif w == "cohort_dist" and new["cohorts"]:
            cid = rng.choice(new["cohorts"])["id"]
            d = rng.choice(DIMS)
            new["allocations"].setdefault(cid, {})[d] = _rand_dist(rng, SPEC["options"][d])
        elif w == "prompt":
            new["prompt_version"] = rng.choice(SPEC["options"]["prompt_version"])
        elif w == "schedule":
            new["schedule"]["hour_weights"]["default"] = {str(h): rng.choice([1, 2]) for h in range(9, 21)}
        elif w == "cohorts":
            new["cohorts"] = list(reversed(new["cohorts"]))
        elif w == "reweight_same":
            # same distribution expressed with scaled weights: not a change after normalisation
            d = rng.choice(DIMS)
            new["allocations"]["default"][d] = {o: w * 3 for o, w in new["allocations"]["default"][d].items()}
    return new


@pytest.mark.parametrize("seed", range(4))
def test_changed_dims_and_max_shift_match_governance_boundary(seed):
    rng = random.Random(seed)
    checked = changed = 0
    for _ in range(400):
        # configs as the boundary stores them when the controller authored them (canonical dists)
        old = normalise_config(SPEC, canonical_config(EMPTY, _rand_config(rng)))
        cand = _mutate(rng, old) if rng.random() < 0.8 else _rand_config(rng)
        new = normalise_config(SPEC, canonical_config(old, cand))
        ours, theirs = changed_dims(old, new), sim_changed_dims(old, new)
        assert ours == theirs, (old, new)
        assert max_shift(old, new) == pytest.approx(sim_max_shift(old, new), abs=1e-12)
        checked += 1
        changed += bool(theirs)
    # the generator must exercise both "changed" and "unchanged" pairs to make this meaningful
    assert 0.2 * checked < changed < checked


def test_parity_on_identity_and_known_shift():
    cfg = normalise_config(SPEC, {"allocations": {"default": {"welcome_message": {"W1": 1}, "voice": {"V1": 1},
                                                              "caller_id": {"D1": 1, "D2": 1}}},
                                  "prompt_version": "P1"})
    assert changed_dims(cfg, cfg) == sim_changed_dims(cfg, cfg) == []
    assert max_shift(cfg, cfg) == 0
    new = copy.deepcopy(cfg)
    new["allocations"]["default"]["caller_id"] = {"D1": 0.2, "D2": 0.3, "D3": 0.5}
    new = normalise_config(SPEC, new)
    assert changed_dims(cfg, new) == sim_changed_dims(cfg, new) == ["caller_id"]
    assert max_shift(cfg, new) == pytest.approx(0.5) == pytest.approx(sim_max_shift(cfg, new))


def test_cohort_override_equal_to_default_is_not_a_change():
    base = {"cohorts": [{"id": "young", "where": {"age_band": ["18-30"]}}],
            "allocations": {"default": {"welcome_message": {"W1": 1}, "voice": {"V1": 1}, "caller_id": {"D1": 1}}},
            "prompt_version": "P1"}
    old = normalise_config(SPEC, base)
    b2 = copy.deepcopy(base)
    b2["allocations"]["young"] = {"voice": {"V1": 5}}   # same effective distribution for the cohort
    new = normalise_config(SPEC, b2)
    assert changed_dims(old, new) == sim_changed_dims(old, new) == []


def _snorm(d):
    """The boundary's normalisation formula (sim.world.normalise_config)."""
    s = float(sum(d.values()))
    return {o: float(w) / s for o, w in d.items() if w > 0}


def test_fixpoint_is_stable_under_boundary_normalisation():
    rng = random.Random(5)
    for _ in range(5000):
        k = rng.randint(1, 6)
        d = {f"o{i}": round(rng.random() + 1e-3, rng.choice([2, 4, 6, 12])) for i in range(k)}
        f = _fixpoint(d)
        assert _snorm(f) == f
        assert sum(f.values()) == pytest.approx(1.0, abs=1e-12)
        assert max(abs(f[o] - _snorm(d)[o]) for o in f) < 1e-12   # same distribution, only ulps differ


def test_regression_ulp_jitter_does_not_leak_into_unchanged_dims():
    """Bug found by the parity test: a controller-authored dist that is not a fixed point of the boundary's
    normalisation is stored as norm(d); copying it into a later proposal re-normalises it to a different float
    -> the boundary reports that dim as changed although nobody touched it. With canonical_config the stored
    value is a fixed point, so a schedule-only change stays schedule-only."""
    did = {"D1": 0.05, "D2": 0.3167, "D3": 0.3167, "D4": 0.3167}     # 5% probe + 3 healthy, rounded to 4dp
    spec = copy.deepcopy(SPEC)
    spec["options"]["caller_id"] = ["D1", "D2", "D3", "D4"]
    base = {"allocations": {"default": {"welcome_message": {"W1": 1}, "voice": {"V1": 1}, "caller_id": {"D1": 1}}},
            "prompt_version": "P1"}
    live = normalise_config(spec, base)

    def roundtrip(send_dist):
        step = copy.deepcopy(live)
        step["allocations"]["default"]["caller_id"] = send_dist
        stored = normalise_config(spec, step)          # what the boundary stores
        nxt = copy.deepcopy(stored)
        nxt["schedule"]["hour_weights"]["default"] = {str(h): 1 for h in range(9, 21)}
        return sim_changed_dims(stored, normalise_config(spec, nxt))

    assert roundtrip(did) == ["caller_id", "schedule"]                        # the hazard is real
    sent = canonical_config(live, {**live, "allocations": {"default": {**live["allocations"]["default"],
                                                                       "caller_id": did}}})
    assert roundtrip(sent["allocations"]["default"]["caller_id"]) == ["schedule"]  # fixed


def test_canonical_config_leaves_untouched_dists_byte_identical():
    live = {"allocations": {"default": {"voice": {"V1": 0.1, "V2": 0.2, "V3": 0.7000000000000001}}}}
    out = canonical_config(live, copy.deepcopy(live))
    assert out == live
