"""Deterministic statistics. No RNG anywhere: same counts in → same decision out.

All tests are on proportions (pickup = connected/dials, engagement = engaged/connected) with normal
approximations, which are accurate at the sample sizes we require before any decision (n ≥ 150 per arm,
expected successes well above 10).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist

_N = NormalDist()


def phi(z: float) -> float:
    return _N.cdf(z)


def z_of(p: float) -> float:
    """Upper-tail critical value: P(Z > z) = p."""
    p = min(max(p, 1e-15), 1 - 1e-15)
    return _N.inv_cdf(1 - p)


@dataclass(frozen=True)
class Prop:
    s: int   # successes
    n: int   # trials

    @property
    def p(self) -> float:
        return self.s / self.n if self.n else float("nan")

    def var(self) -> float:
        # Agresti-Caffo style +1/+2 stabilisation keeps the variance positive at p in {0, 1}
        pp = (self.s + 1) / (self.n + 2)
        return pp * (1 - pp) / max(self.n, 1)


@dataclass(frozen=True)
class Comparison:
    diff: float        # p_b - p_a (absolute)
    rel: float         # p_b / p_a - 1
    se: float
    z: float           # diff / se ; positive = b better
    p_one_sided: float  # P(Z >= z) under H0: b <= a

    def lcb(self, conf: float = 0.8) -> float:
        return self.diff - z_of(1 - conf) * self.se

    def ucb(self, conf: float = 0.8) -> float:
        return self.diff + z_of(1 - conf) * self.se


def compare(a: Prop, b: Prop) -> Comparison:
    """Two-proportion comparison, b vs a (unpooled SE, Wald)."""
    if a.n == 0 or b.n == 0:
        return Comparison(0.0, 0.0, float("inf"), 0.0, 1.0)
    se = math.sqrt(a.var() + b.var())
    diff = b.p - a.p
    z = diff / se if se > 0 else 0.0
    rel = (b.p / a.p - 1) if a.p > 0 else 0.0
    return Comparison(diff, rel, se, z, 1 - phi(z))


def sample_size_per_arm(p: float, mde_rel: float, alpha: float, power: float, ratio: float = 1.0) -> int:
    """Per-arm n (for the *smaller* arm) to detect p -> p(1+mde) one-sided at alpha with given power.
    ratio = n_large / n_small (allocation imbalance)."""
    d = p * mde_rel
    if d <= 0 or not 0 < p < 1:
        return 10 ** 9
    p2 = min(p * (1 + mde_rel), 0.999)
    za, zb = z_of(alpha), z_of(1 - power)
    var = p * (1 - p) / ratio + p2 * (1 - p2)
    return int(math.ceil((za + zb) ** 2 * var / d ** 2))


def achieved_mde(p: float, n_small: int, alpha: float, power: float, ratio: float = 1.0) -> float:
    """Relative MDE achievable with n_small (inverse of sample_size_per_arm, approx at p)."""
    if n_small <= 0 or not 0 < p < 1:
        return float("inf")
    za, zb = z_of(alpha), z_of(1 - power)
    se = math.sqrt(p * (1 - p) / (n_small * ratio) + p * (1 - p) / n_small)
    return (za + zb) * se / p


def obf_spent(t: float, alpha: float) -> float:
    """Lan-DeMets O'Brien-Fleming-type alpha spending, one-sided level alpha."""
    if t <= 0:
        return 0.0
    t = min(t, 1.0)
    return 2.0 * (1.0 - phi(z_of(alpha / 2) / math.sqrt(t)))


def look_alpha(t_prev: float, t_now: float, alpha: float) -> float:
    """Nominal level for this look = alpha spent since the last look (Bonferroni over looks: conservative)."""
    return max(obf_spent(t_now, alpha) - obf_spent(t_prev, alpha), 0.0)


def holm(pvalues: dict[str, float], alpha: float) -> set[str]:
    """Holm step-down: returns the keys whose null is rejected at family-wise level alpha."""
    items = sorted(pvalues.items(), key=lambda kv: (kv[1], kv[0]))
    m = len(items)
    out = set()
    for i, (k, p) in enumerate(items):
        if p <= alpha / (m - i):
            out.add(k)
        else:
            break
    return out


def binom_excess(s: int, n: int, p0: float) -> float:
    """z for observed rate s/n exceeding a reference p0 (one-sided, normal approx)."""
    if n == 0 or not 0 < p0 < 1:
        return 0.0
    return (s / n - p0) / math.sqrt(p0 * (1 - p0) / n)


def tv_distance(a: dict[str, float], b: dict[str, float]) -> float:
    sa, sb = sum(a.values()) or 1.0, sum(b.values()) or 1.0
    keys = set(a) | set(b)
    return 0.5 * sum(abs(a.get(k, 0) / sa - b.get(k, 0) / sb) for k in keys)
