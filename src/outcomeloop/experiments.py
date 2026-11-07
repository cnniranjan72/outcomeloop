"""Variant experimentation (C6), winner promotion, decay detection and rollback (C7).

One experiment per (workflow, dimension) for welcome_message and voice. The simulator samples each dimension
independently per dial, so the two experiments run concurrently as a factorial design and each is analysed on
all traffic (marginal over the other dimension).

Lifecycle (status):
  designed ──(config live)──▶ running ──look: winner──▶ promoting ──(live)──▶ promoted ──decay──▶ rolling_back ──▶ rolled_back
                                 │  └──look: horizon, no winner──▶ concluding ──(live)──▶ no_winner
                                 └──supervisor edits the dimension──▶ aborted
Every transition writes an audit decision. Statistics come only from calls that actually ran (event variant).
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field

from .cohorts import Cohort, membership_sql
from .config import Settings
from .db import DB, dumps
from .stats import Prop, achieved_mde, compare, holm, look_alpha, obf_spent, sample_size_per_arm, z_of
from .timeutil import minute_to_label

log = logging.getLogger("outcomeloop.exp")

EXP_DIMS = ("welcome_message", "voice")
ACTIVE = ("designed", "running", "promoting", "promoted", "rolling_back", "concluding")


@dataclass
class Experiment:
    experiment_id: str
    wf: int
    dim: str
    arms: list[str]
    incumbent: str
    design: dict[str, float]
    status: str = "designed"
    created_minute: int = 0
    start_minute: int | None = None
    start_version: int | None = None
    versions: list[int] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    p_base: float = 0.0
    n_plan: int = 0
    achieved_mde: float = 0.0
    t_prev: float = 0.0
    alpha_spent: float = 0.0
    horizon_days: float = 5.0
    extended: bool = False
    looks: list[dict] = field(default_factory=list)
    winner: str | None = None
    plan: dict = field(default_factory=dict)          # target allocations: {"default": {...}, cohort: {...}}
    promo: dict = field(default_factory=dict)         # scope -> {"winner","incumbent","diff","se"}
    promoted_minute: int | None = None
    result: dict = field(default_factory=dict)

    def save(self, db: DB, minute: int):
        db.x("INSERT INTO experiments VALUES (?,?,?,?,?,?,?) ON CONFLICT(experiment_id) DO UPDATE SET"
             " status=excluded.status, data=excluded.data, updated_minute=excluded.updated_minute",
             (self.experiment_id, self.wf, self.dim, self.status, dumps(asdict(self)), self.created_minute, minute))

    @staticmethod
    def load_active(db: DB, wf: int) -> dict[str, "Experiment"]:
        out = {}
        for (data,) in db.q(f"SELECT data FROM experiments WHERE wf=? AND status IN ({','.join('?' * len(ACTIVE))})",
                            (wf, *ACTIVE)):
            e = Experiment(**json.loads(data))
            out[e.dim] = e
        return out


def _alloc_default(cfg: dict, dim: str) -> dict[str, float]:
    return dict(cfg["allocations"]["default"][dim])


def _close(a: dict, b: dict, tol: float = 0.02) -> bool:
    keys = set(a) | set(b)
    return all(abs(a.get(k, 0) - b.get(k, 0)) <= tol for k in keys)


class ExperimentEngine:
    def __init__(self, db: DB, s: Settings):
        self.db = db
        self.s = s

    # ------------------------------------------------------------------ data
    def arm_counts(self, e: Experiment, since: int | None = None, cohorts: list[Cohort] | None = None,
                   until: int | None = None) -> dict:
        """{scope: {option: (dials, connected, engaged)}} for calls that ran under the experiment's versions."""
        db = self.db
        col = "wm" if e.dim == "welcome_message" else "voice"
        case = membership_sql(db, cohorts or [])
        vs = e.versions or [-1]
        sql = (f"SELECT {case} AS c, {col}, COUNT(*), SUM(conn), SUM(eng) FROM calls WHERE wf=? AND minute>=?"
               f" AND minute<? AND cfg_ver IN ({','.join('?' * len(vs))}) GROUP BY 1, 2")
        rows = db.q(sql, (e.wf, since if since is not None else (e.start_minute or 0), until or 10 ** 9, *vs))
        out: dict[str, dict[str, tuple]] = {"ALL": {}}
        for c, o, n, k, g in rows:
            opt = db.decode(e.dim, o)
            out.setdefault(c, {})[opt] = (n, k, g)
            a = out["ALL"].get(opt, (0, 0, 0))
            out["ALL"][opt] = (a[0] + n, a[1] + k, a[2] + g)
        return out

    # ------------------------------------------------------------------ design
    def design(self, wf: int, dim: str, cfg: dict, options: list[str], blacklist: dict[str, int], now: int,
               p_base: float, connected_per_day: float) -> Experiment | None:
        cur = _alloc_default(cfg, dim)
        incumbent = max(sorted(cur), key=lambda o: cur[o])
        arms = [o for o in options if o == incumbent or blacklist.get(o, -1) < now]
        if len(arms) < 2 or p_base <= 0:
            return None
        k = len(arms) - 1
        s = self.s
        design = {incumbent: 1 - s.challenger_share}
        for o in arms:
            if o != incumbent:
                design[o] = s.challenger_share / k
        ratio = (1 - s.challenger_share) / (s.challenger_share / k)
        a_each = s.alpha / k
        n_mde = sample_size_per_arm(p_base, s.mde_rel, a_each, s.power, ratio)
        n_horizon = int(connected_per_day * s.challenger_share / k * s.max_experiment_days)
        n_plan = max(min(n_mde, n_horizon), s.min_arm_connected_for_look)
        e = Experiment(experiment_id=f"exp-{wf}-{dim}-{now}", wf=wf, dim=dim, arms=arms, incumbent=incumbent,
                       design={o: round(w, 4) for o, w in design.items()}, created_minute=now, p_base=round(p_base, 4),
                       n_plan=n_plan, achieved_mde=round(achieved_mde(p_base, n_plan, a_each, s.power, ratio), 4))
        e.plan = {"default": e.design}
        e.horizon_days = s.max_experiment_days
        return e

    # ------------------------------------------------------------------ config sync
    def on_config(self, e: Experiment, cfg: dict, version: int, actor: str, changed: list[str], minute: int) -> str | None:
        """Update experiment state from a newly observed config version. Returns a transition name or None."""
        dist = _alloc_default(cfg, e.dim)
        if actor == "supervisor" and e.dim in changed and e.status in ("running", "designed", "promoting", "promoted",
                                                                     "rolling_back", "concluding"):
            e.status = "aborted"
            e.result["aborted"] = {"minute": minute, "version": version, "reason": "supervisor edited this dimension"}
            return "aborted"
        if e.status == "designed" and _close(dist, e.design):
            e.status, e.start_minute, e.start_version, e.versions = "running", minute, version, [version]
            return "started"
        appended = False
        if e.status in ("running", "promoting", "concluding", "rolling_back", "promoted"):
            if version not in e.versions:
                e.versions.append(version)
                appended = True
        if e.status == "promoting" and self._plan_live(e, cfg):
            e.status, e.promoted_minute = "promoted", minute
            e.versions = [version]
            return "promoted"
        if e.status == "concluding" and self._plan_live(e, cfg):
            e.status = "no_winner"
            return "closed"
        if e.status == "rolling_back" and self._plan_live(e, cfg):
            e.status = "rolled_back"
            return "rolled_back"
        return "versions" if appended else None

    def _plan_live(self, e: Experiment, cfg: dict) -> bool:
        for scope, want in e.plan.items():
            got = (cfg["allocations"].get(scope) or {}).get(e.dim) or cfg["allocations"]["default"][e.dim]
            if not _close(got, want):
                return False
        return True

    # ------------------------------------------------------------------ looks
    def look(self, e: Experiment, now: int, cohorts: list[Cohort], guardrail: dict, final_due: bool) -> dict:
        """One sequential look. Returns a decision dict with 'action' in
        {none, drop, promote, no_winner} plus full evidence."""
        s = self.s
        counts = self.arm_counts(e, cohorts=cohorts, until=now)
        allc = counts["ALL"]
        inc = allc.get(e.incumbent, (0, 0, 0))
        challengers = [o for o in e.arms if o != e.incumbent and o not in e.dropped]
        res = {"minute": now, "label": minute_to_label(now), "arms": {}, "action": "none"}
        if not challengers:
            res["action"] = "no_winner"
            return res
        cmps, guard = {}, {}
        for o in challengers:
            n, k, g = allc.get(o, (0, 0, 0))
            c = compare(Prop(inc[2], inc[1]), Prop(g, k))          # engagement: engaged / connected
            p = compare(Prop(inc[1], inc[0]), Prop(k, n))          # pickup guardrail: connected / dials
            cmps[o], guard[o] = c, p
            res["arms"][o] = {"dials": n, "connected": k, "engaged": g, "eng_rate": round(g / k, 4) if k else None,
                              "lift_rel": round(c.rel, 4), "z": round(c.z, 2), "p": float(f"{c.p_one_sided:.3g}"),
                              "pickup_diff": round(p.diff, 4), "pickup_z": round(p.z, 2)}
        res["incumbent"] = {"option": e.incumbent, "dials": inc[0], "connected": inc[1], "engaged": inc[2],
                            "eng_rate": round(inc[2] / inc[1], 4) if inc[1] else None}
        # harm stopping: lenient threshold, only ever moves traffic back to the incumbent
        harmful = [o for o in challengers if allc.get(o, (0, 0, 0))[1] >= s.harm_min_connected
                   and cmps[o].z < -s.harm_z]
        n_chal = [allc.get(o, (0, 0, 0))[1] for o in challengers]
        t_now = min(1.0, (sum(n_chal) / len(n_chal)) / max(e.n_plan, 1))
        enough = min(n_chal) >= s.min_arm_connected_for_look and inc[1] >= s.min_arm_connected_for_look
        horizon = final_due or t_now >= 1.0
        res.update({"t": round(t_now, 3), "n_plan": e.n_plan, "horizon": horizon})
        if not enough and not horizon:
            if harmful:
                res["action"], res["drop"] = "drop", harmful
            return res
        remaining = max(s.alpha - e.alpha_spent, 0.0)
        if horizon:
            # first horizon keeps half of what is left in reserve for a possible extension's final look
            a_look = remaining if e.extended else remaining / 2
        else:
            a_look = min(look_alpha(e.t_prev, t_now, s.alpha), remaining)
        res["alpha_look"] = float(f"{a_look:.3g}")
        e.t_prev = t_now
        e.alpha_spent += a_look
        winners = holm({o: cmps[o].p_one_sided for o in challengers}, a_look)
        # guardrail: block when the point drop exceeds the margin, or a significant drop exceeds half of it
        margin = guardrail.get("margin", 0.02)
        blocked = {o for o in winners if (-guard[o].diff > margin) or (guard[o].z < -1.645 and -guard[o].diff > margin / 2)}
        winners -= blocked
        res["significant"], res["guardrail_blocked"] = sorted(winners), sorted(blocked)
        if winners:
            # stability: an effect that has faded in the last 24h is not a winner (non-stationary arms, e.g. novelty)
            unstable = self._unstable(e, now, sorted(winners), cmps, cohorts)
            res["stability"] = unstable
            winners -= {o for o, v in unstable.items() if v.get("unstable")}
        if winners:
            # deterministic pick: highest 80% lower confidence bound on the lift, ties by option order
            w = max(sorted(winners), key=lambda o: cmps[o].lcb(0.8))
            res["action"], res["winner"] = "promote", w
            res["cohort_check"] = self._cohort_plan(e, w, counts, cohorts)
            return res
        # no pooled winner: cohort-level winners (Bonferroni over cohorts) — catches effects that only exist in a cohort
        cw = self._cohort_winners(e, counts, cohorts, a_look, challengers, margin)
        if cw:
            res["action"], res["cohort_winners"] = "promote_cohorts", cw
            return res
        if horizon:
            best = max(challengers, key=lambda o: cmps[o].diff)
            if not e.extended and cmps[best].diff > 0 and allc.get(best, (0, 0, 0))[1] >= s.min_arm_connected_for_look:
                # pre-registered single extension; the final look of the extension spends what alpha is left
                e.extended = True
                e.n_plan *= 2
                e.horizon_days *= 2
                e.t_prev = t_now / 2
                res["action"], res["extend_best"] = "extend", best
                return res
            res["action"] = "no_winner"
        elif harmful:
            res["action"], res["drop"] = "drop", harmful
        return res

    def _unstable(self, e: Experiment, now: int, opts: list[str], cmps: dict, cohorts) -> dict:
        """Recent-window check: the last 24h lift must not be significantly below the whole-window lift, and must
        not itself be negative. Guards against promoting a variant whose effect is already wearing off."""
        s = self.s
        recent = self.arm_counts(e, since=max(e.start_minute or 0, now - s.decay_window_minutes), until=now)["ALL"]
        i = recent.get(e.incumbent, (0, 0, 0))
        out = {}
        for o in opts:
            w = recent.get(o, (0, 0, 0))
            rec = {"recent_inc_conn": i[1], "recent_conn": w[1]}
            if min(i[1], w[1]) >= s.decay_min_connected:
                rc = compare(Prop(i[2], i[1]), Prop(w[2], w[1]))
                zd = (rc.diff - cmps[o].diff) / ((rc.se ** 2 + cmps[o].se ** 2) ** 0.5)
                rec.update({"recent_lift": round(rc.diff, 4), "z_vs_overall": round(zd, 2)})
                rec["unstable"] = zd < -s.harm_z or rc.diff <= 0
            out[o] = rec
        return out

    def _cohort_plan(self, e: Experiment, winner: str, counts: dict, cohorts: list[Cohort]) -> dict:
        """Before promoting a pooled winner, check every cohort: where the winner is significantly worse than the
        incumbent, that cohort keeps the incumbent."""
        s = self.s
        out = {}
        for c in cohorts:
            cc = counts.get(c.cohort_id, {})
            i, w = cc.get(e.incumbent, (0, 0, 0)), cc.get(winner, (0, 0, 0))
            cmp_ = compare(Prop(i[2], i[1]), Prop(w[2], w[1]))
            harmed = min(i[1], w[1]) >= s.harm_min_connected // 2 and cmp_.z < -s.harm_z
            out[c.cohort_id] = {"inc_conn": i[1], "win_conn": w[1], "lift_rel": round(cmp_.rel, 4),
                                "z": round(cmp_.z, 2), "keeps_incumbent": harmed}
        return out

    def _cohort_winners(self, e, counts, cohorts, a_look, challengers, margin) -> dict:
        s = self.s
        out = {}
        if not cohorts:
            return out
        a_c = a_look / len(cohorts)
        for c in cohorts:
            cc = counts.get(c.cohort_id, {})
            i = cc.get(e.incumbent, (0, 0, 0))
            if i[1] < s.min_arm_connected_for_look:
                continue
            ps, cm = {}, {}
            for o in challengers:
                w = cc.get(o, (0, 0, 0))
                if w[1] < s.min_arm_connected_for_look:
                    continue
                cm[o] = compare(Prop(i[2], i[1]), Prop(w[2], w[1]))
                pk = compare(Prop(i[1], i[0]), Prop(w[1], w[0]))
                if -pk.diff > margin:
                    continue
                ps[o] = cm[o].p_one_sided
            win = holm(ps, a_c)
            if win:
                o = max(sorted(win), key=lambda x: cm[x].lcb(0.8))
                out[c.cohort_id] = {"winner": o, "lift_rel": round(cm[o].rel, 4), "z": round(cm[o].z, 2),
                                    "diff": cm[o].diff, "se": cm[o].se}
        return out

    # ------------------------------------------------------------------ plans
    def plan_promotion(self, e: Experiment, res: dict) -> None:
        h = self.s.holdout_share
        e.plan, e.promo = {}, {}
        if res["action"] == "promote":
            w = res["winner"]
            e.winner = w
            e.plan["default"] = {w: round(1 - h, 4), e.incumbent: round(h, 4)}
            a = res["arms"][w]
            inc = res["incumbent"]
            cmp_ = compare(Prop(inc["engaged"], inc["connected"]), Prop(a["engaged"], a["connected"]))
            e.promo["default"] = {"winner": w, "incumbent": e.incumbent, "diff": cmp_.diff, "se": cmp_.se}
            for cid, chk in res.get("cohort_check", {}).items():
                if chk["keeps_incumbent"]:
                    e.plan[cid] = {e.incumbent: 1.0}
        else:
            e.plan["default"] = {e.incumbent: 1.0}
            for cid, cw in res["cohort_winners"].items():
                e.plan[cid] = {cw["winner"]: round(1 - h, 4), e.incumbent: round(h, 4)}
                e.promo[cid] = {"winner": cw["winner"], "incumbent": e.incumbent, "diff": cw["diff"], "se": cw["se"]}
            e.winner = ",".join(f"{c}:{v['winner']}" for c, v in res["cohort_winners"].items())
        e.status = "promoting"

    def plan_drop(self, e: Experiment, arms: list[str]) -> None:
        e.dropped = sorted(set(e.dropped) | set(arms))
        live = {o: w for o, w in e.design.items() if o not in e.dropped}
        z = sum(live.values())
        e.design = {o: round(w / z, 4) for o, w in live.items()}
        e.plan = {"default": e.design}

    def plan_no_winner(self, e: Experiment) -> None:
        e.plan = {"default": {e.incumbent: 1.0}}
        e.status = "concluding"

    # ------------------------------------------------------------------ decay
    def decay_check(self, e: Experiment, now: int, cohorts: list[Cohort]) -> dict:
        """Winner vs holdout over the recent window, compared with the lift measured at promotion."""
        s = self.s
        since = max(e.promoted_minute or now, now - s.decay_window_minutes)
        counts = self.arm_counts(e, since=since, cohorts=cohorts, until=now)
        out = {"window_start": since, "scopes": {}, "decayed": []}
        for scope, pr in e.promo.items():
            cc = counts.get("ALL" if scope == "default" else scope, {})
            if scope == "default":
                # pooled scope excludes cohorts that have their own override
                cc = {}
                for c, v in counts.items():
                    if c == "ALL" or c in e.plan:
                        continue
                    for o, t in v.items():
                        a = cc.get(o, (0, 0, 0))
                        cc[o] = (a[0] + t[0], a[1] + t[1], a[2] + t[2])
            i, w = cc.get(pr["incumbent"], (0, 0, 0)), cc.get(pr["winner"], (0, 0, 0))
            rec = {"holdout_connected": i[1], "winner_connected": w[1]}
            if i[1] >= s.decay_min_connected and w[1] >= s.decay_min_connected:
                now_c = compare(Prop(i[2], i[1]), Prop(w[2], w[1]))
                # winner's curse: a lift measured at the moment it first crossed a significance boundary is biased
                # upward, so compare against its 80% lower confidence bound, not its point estimate
                promo_ref = pr["diff"] - z_of(0.2) * pr["se"]
                zd = (now_c.diff - promo_ref) / ((now_c.se ** 2 + pr["se"] ** 2) ** 0.5)
                rec.update({"lift_now": round(now_c.diff, 4), "z_now": round(now_c.z, 2),
                            "lift_at_promotion": round(pr["diff"], 4), "promotion_lcb80": round(promo_ref, 4),
                            "z_vs_promotion": round(zd, 2)})
                if zd < -s.decay_z or (now_c.diff < 0 and now_c.z < -s.harm_z):
                    out["decayed"].append(scope)
            out["scopes"][scope] = rec
        return out

    def plan_rollback(self, e: Experiment, scopes: list[str], now: int) -> list[str]:
        """Move decayed scopes back to the incumbent; returns options to blacklist."""
        black = []
        for sc in scopes:
            pr = e.promo.get(sc)
            if not pr:
                continue
            e.plan[sc] = {pr["incumbent"]: 1.0}
            black.append(pr["winner"])
        e.status = "rolling_back"
        e.result["rollback"] = {"minute": now, "scopes": scopes}
        return black
