import math
import random

import pytest

from outcomeloop.stats import (Prop, achieved_mde, binom_excess, compare, holm, look_alpha, obf_spent,
                               sample_size_per_arm, tv_distance, z_of)


# ------------------------------------------------------------------ compare()
def test_compare_sign_is_b_minus_a():
    a, b = Prop(300, 1000), Prop(400, 1000)
    c = compare(a, b)
    assert c.diff == pytest.approx(0.10)
    assert c.rel == pytest.approx(400 / 300 - 1)
    assert c.z > 0 and c.p_one_sided < 0.001
    r = compare(b, a)
    assert r.diff == pytest.approx(-0.10) and r.z == pytest.approx(-c.z)
    assert r.p_one_sided == pytest.approx(1 - c.p_one_sided)


def test_compare_identical_is_null():
    c = compare(Prop(250, 1000), Prop(250, 1000))
    assert c.diff == 0 and c.z == 0 and c.p_one_sided == pytest.approx(0.5)


def test_compare_empty_arm_never_significant():
    for a, b in ((Prop(0, 0), Prop(50, 100)), (Prop(50, 100), Prop(0, 0))):
        c = compare(a, b)
        assert c.p_one_sided == 1.0 and c.z == 0.0 and math.isinf(c.se)


def test_compare_degenerate_rates_have_finite_se():
    # p in {0,1}: the +1/+2 stabilised variance keeps se > 0 so z is finite
    c = compare(Prop(0, 500), Prop(500, 500))
    assert c.se > 0 and math.isfinite(c.z) and c.z > 10


def test_confidence_bounds_bracket_diff():
    c = compare(Prop(200, 1000), Prop(260, 1000))
    assert c.lcb(0.8) < c.diff < c.ucb(0.8)
    assert c.lcb(0.95) < c.lcb(0.8)  # higher confidence -> wider


# ------------------------------------------------------------------ holm()
def test_holm_textbook_example():
    # Holm (1979)-style example: m=4, alpha=0.05, thresholds .0125, .0167, .025, .05
    p = {"a": 0.010, "b": 0.040, "c": 0.030, "d": 0.005}
    # sorted: d .005<=.0125 ok, a .010<=.0167 ok, c .030>.025 stop -> b not tested
    assert holm(p, 0.05) == {"d", "a"}


def test_holm_step_down_stops_at_first_failure():
    # b would pass its own threshold (.05/1) but Holm stops at c
    assert holm({"a": 0.001, "c": 0.04, "b": 0.045}, 0.05) == {"a"}


def test_holm_all_and_none():
    assert holm({"a": 0.001, "b": 0.002}, 0.05) == {"a", "b"}
    assert holm({"a": 0.2, "b": 0.3}, 0.05) == set()
    assert holm({}, 0.05) == set()


def test_holm_is_never_less_powerful_than_bonferroni():
    rng = random.Random(7)
    for _ in range(300):
        p = {f"k{i}": rng.random() * 0.06 for i in range(rng.randint(1, 5))}
        bonf = {k for k, v in p.items() if v <= 0.05 / len(p)}
        assert bonf <= holm(p, 0.05)


def test_holm_ties_deterministic():
    p = {"b": 0.01, "a": 0.01, "c": 0.5}
    assert holm(p, 0.05) == holm(dict(reversed(list(p.items()))), 0.05) == {"a", "b"}


# ------------------------------------------------------------------ alpha spending
@pytest.mark.parametrize("alpha", [0.01, 0.05, 0.1])
def test_obf_spent_monotone_and_full_at_one(alpha):
    ts = [i / 50 for i in range(51)]
    vals = [obf_spent(t, alpha) for t in ts]
    assert vals[0] == 0.0
    assert all(b >= a for a, b in zip(vals, vals[1:]))
    assert vals[-1] == pytest.approx(alpha, rel=1e-9)
    assert obf_spent(1.7, alpha) == pytest.approx(alpha)  # capped at t=1
    # O'Brien-Fleming is very conservative early
    assert obf_spent(0.25, alpha) < alpha / 10


def test_look_alpha_never_exceeds_total_over_any_sequence():
    rng = random.Random(11)
    for _ in range(500):
        k = rng.randint(1, 12)
        ts = sorted(rng.random() for _ in range(k))
        if rng.random() < 0.5:
            ts.append(1.0)
        prev, total = 0.0, 0.0
        for t in ts:
            a = look_alpha(prev, t, 0.05)
            assert a >= 0
            total += a
            prev = t
        assert total <= 0.05 + 1e-12


def test_look_alpha_non_increasing_info_spends_nothing():
    assert look_alpha(0.6, 0.6, 0.05) == 0
    assert look_alpha(0.6, 0.4, 0.05) == 0


# ------------------------------------------------------------------ sample size / MDE
@pytest.mark.parametrize("p,mde,ratio", [(0.5, 0.1, 1.0), (0.3, 0.1, 1.5), (0.55, 0.05, 4.0), (0.2, 0.2, 1.0)])
def test_sample_size_and_mde_round_trip(p, mde, ratio):
    n = sample_size_per_arm(p, mde, 0.05, 0.8, ratio)
    back = achieved_mde(p, n, 0.05, 0.8, ratio)
    # achieved_mde uses the null variance at both arms; agrees within ~ the p->p(1+mde) variance change
    assert back == pytest.approx(mde, rel=0.15)
    # more data -> smaller detectable effect; fewer -> larger
    assert achieved_mde(p, 4 * n, 0.05, 0.8, ratio) < back < achieved_mde(p, n // 4, 0.05, 0.8, ratio)


def test_sample_size_textbook_value():
    # p=0.5 -> 0.55, alpha=.05 one-sided, power .8: (1.645+0.8416)^2 (0.25+0.2475)/0.05^2 ~ 1230
    n = sample_size_per_arm(0.5, 0.1, 0.05, 0.8)
    assert 1200 <= n <= 1260


def test_sample_size_degenerate_inputs():
    assert sample_size_per_arm(0.0, 0.1, 0.05, 0.8) >= 10 ** 9
    assert sample_size_per_arm(0.4, 0.0, 0.05, 0.8) >= 10 ** 9
    assert achieved_mde(0.4, 0, 0.05, 0.8) == float("inf")


def test_sample_size_grows_with_stricter_alpha_and_smaller_mde():
    base = sample_size_per_arm(0.4, 0.1, 0.05, 0.8)
    assert sample_size_per_arm(0.4, 0.1, 0.025, 0.8) > base
    assert sample_size_per_arm(0.4, 0.05, 0.05, 0.8) > 3 * base


# ------------------------------------------------------------------ misc
def test_binom_excess_and_tv():
    assert binom_excess(40, 1000, 0.01) > 9
    assert binom_excess(10, 1000, 0.01) == pytest.approx(0)
    assert binom_excess(5, 0, 0.01) == 0
    assert tv_distance({"a": 1}, {"a": 2}) == 0           # normalised
    assert tv_distance({"a": 1}, {"b": 1}) == pytest.approx(1)
    assert tv_distance({"a": 0.5, "b": 0.5}, {"a": 0.7, "b": 0.3}) == pytest.approx(0.2)


def test_z_of_inverse():
    assert z_of(0.05) == pytest.approx(1.6449, abs=1e-4)
    assert z_of(0.5) == pytest.approx(0, abs=1e-12)


def test_determinism():
    args = [(Prop(301, 1000), Prop(355, 1010)), (Prop(0, 10), Prop(3, 10))]
    first = [compare(a, b) for a, b in args] + [holm({"x": 0.01, "y": 0.02}, 0.05),
                                                 sample_size_per_arm(0.37, 0.1, 0.025, 0.8, 3.0),
                                                 obf_spent(0.37, 0.05)]
    for _ in range(3):
        again = [compare(a, b) for a, b in args] + [holm({"x": 0.01, "y": 0.02}, 0.05),
                                                     sample_size_per_arm(0.37, 0.1, 0.025, 0.8, 3.0),
                                                     obf_spent(0.37, 0.05)]
        assert again == first
