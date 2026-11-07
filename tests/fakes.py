"""In-memory stand-in for `outcomeloop.simclient.SimClient`.

Implements exactly the methods the Ingestor and Governance use, with the simulator's governance semantics
(duplicate proposal ids, stale base version, lapse), plus fault injection so recovery paths are deterministic:

    fake.fail("request_approval", ApiError(409, "stale_base_version", {...}))   # raise instead of acting
    fake.fail("apply", Uncertain("timeout"), after_send=True)                    # act, THEN raise (lost response)
    fake.fail("request_approval", Uncertain("conn reset"), after_send=False)     # never reached the server

Every write is counted in `fake.calls[method]`, so tests can assert "never double-applied".
"""
from __future__ import annotations

import copy
from collections import Counter, defaultdict

from outcomeloop.simclient import ApiError, Uncertain
from outcomeloop.timeutil import minute_to_label

D0_ISO = "2027-01-04"


def fmt_ts(minute: int) -> str:
    import datetime as dt
    d = dt.date(2027, 1, 4) + dt.timedelta(days=minute // 1440)
    m = minute % 1440
    return f"{d.isoformat()}T{m // 60:02d}:{m % 60:02d}:00+05:30"


class FakeSim:
    def __init__(self, configs: dict[str, dict] | None = None):
        self.now = 0
        self.chunks: dict[int, dict] = {}          # n -> {"meta": {...}, "events": [...], "explode_after": int|None}
        self.versions: dict[str, list[dict]] = {}
        for wid, cfg in (configs or {}).items():
            self.versions[wid] = [{"version": 1, "config": copy.deepcopy(cfg), "actor": "business_default",
                                   "proposal_id": None, "approval_id": None, "changed_dims": []}]
        self.approvals_: dict[str, dict] = {}
        self.proposal_ids: set[str] = set()
        self.calls: Counter = Counter()
        self._faults: dict[str, list[tuple[Exception, bool]]] = defaultdict(list)

    # ------------------------------------------------------------------ fault injection
    def fail(self, method: str, exc: Exception, after_send: bool = False):
        """Queue a one-shot fault for the next call of `method`. after_send=True performs the operation first
        (the request reached the server) and then raises — the classic lost-response timeout."""
        self._faults[method].append((exc, after_send))

    def _fault(self, method: str):
        q = self._faults.get(method)
        return q.pop(0) if q else None

    def _run(self, method: str, op):
        self.calls[method] += 1
        f = self._fault(method)
        if f and not f[1]:
            raise f[0]
        out = op()
        if f:
            raise f[0]
        return out

    # ------------------------------------------------------------------ chunks (Ingestor)
    def add_chunk(self, events: list[dict], kind: str = "events", explode_after: int | None = None) -> dict:
        n = len(self.chunks)
        first = events[0]["event_id"] if events else None
        last = events[-1]["event_id"] if events else None
        meta = {"chunk": n, "kind": kind, "events": len(events), "first_event_id": first, "last_event_id": last,
                "until_minute": self.now}
        self.chunks[n] = {"meta": meta, "events": events, "explode_after": explode_after}
        return meta

    def list_chunks(self, kind: str, after: int = -1) -> list[dict]:
        return [dict(c["meta"]) for n, c in sorted(self.chunks.items()) if c["meta"]["kind"] == kind and n > after]

    def iter_chunk(self, n: int):
        self.calls["iter_chunk"] += 1
        c = self.chunks[n]
        for i, ev in enumerate(c["events"]):
            if c["explode_after"] is not None and i == c["explode_after"]:
                c["explode_after"] = None          # one-shot: the retry succeeds
                raise RuntimeError(f"injected failure in chunk {n} at event {i}")
            yield copy.deepcopy(ev)

    # ------------------------------------------------------------------ config
    def _cur(self, wid):
        return self.versions[wid][-1]

    def config(self, wid: str) -> dict:
        self.calls["config"] += 1
        v = self._cur(wid)
        return {"workflow_id": wid, "version": v["version"], "actor": v["actor"], "config": copy.deepcopy(v["config"])}

    def config_history(self, wid: str) -> list[dict]:
        self.calls["config_history"] += 1
        return [{k: v[k] for k in ("version", "actor", "changed_dims", "proposal_id", "approval_id")}
                for v in self.versions[wid]]

    def _new_version(self, wid, cfg, actor, pid=None, aid=None) -> int:
        v = len(self.versions[wid]) + 1
        self.versions[wid].append({"version": v, "config": copy.deepcopy(cfg), "actor": actor, "proposal_id": pid,
                                   "approval_id": aid, "changed_dims": ["?"]})
        return v

    def supervisor_edit(self, wid: str, cfg: dict) -> int:
        return self._new_version(wid, cfg, "supervisor")

    # ------------------------------------------------------------------ approvals
    def _public(self, a):
        return {k: a[k] for k in ("approval_id", "proposal_id", "workflow_id", "status", "base_version")} | (
            {"applied_version": a["applied_version"]} if "applied_version" in a else {})

    def request_approval(self, body: dict) -> dict:
        def op():
            pid = body["proposal_id"]
            if pid in self.proposal_ids:
                raise ApiError(409, "duplicate_proposal_id", pid)
            wid = body["workflow_id"]
            if body["base_version"] != self._cur(wid)["version"]:
                raise ApiError(409, "stale_base_version", {"current_version": self._cur(wid)["version"]})
            self.proposal_ids.add(pid)
            aid = f"apr_{len(self.approvals_) + 1:05d}"
            self.approvals_[aid] = {"approval_id": aid, "proposal_id": pid, "workflow_id": wid, "status": "pending",
                                    "base_version": body["base_version"], "config": body["proposed_config"]}
            return self._public(self.approvals_[aid])
        return self._run("request_approval", op)

    def decide(self, aid: str, status: str):
        """Test hook: the approver decides (approved / rejected / expired / lapsed)."""
        self.approvals_[aid]["status"] = status

    def approval(self, aid: str) -> dict:
        self.calls["approval"] += 1
        if aid not in self.approvals_:
            raise ApiError(404, "not_found", aid)
        return self._public(self.approvals_[aid])

    def approvals(self, workflow_id: str | None = None, status: str | None = None) -> list[dict]:
        self.calls["approvals"] += 1
        return [self._public(a) for a in self.approvals_.values()
                if (not workflow_id or a["workflow_id"] == workflow_id) and (not status or a["status"] == status)]

    def apply(self, wid: str, approval_id: str) -> dict:
        def op():
            a = self.approvals_[approval_id]
            if a["status"] == "lapsed":
                raise ApiError(410, "approval_lapsed", "not applied within the apply window")
            if a["status"] != "approved":
                raise ApiError(409, "not_approved", {"status": a["status"]})
            if a["base_version"] != self._cur(wid)["version"]:
                raise ApiError(409, "stale_base_version", {"current_version": self._cur(wid)["version"]})
            v = self._new_version(wid, a["config"], "controller_approved", a["proposal_id"], approval_id)
            a["status"], a["applied_version"] = "applied", v
            return {"workflow_id": wid, "version": v, "changed_dims": ["?"]}
        return self._run("apply", op)

    def auto_apply(self, wid: str, body: dict) -> dict:
        def op():
            pid = body["proposal_id"]
            if pid in self.proposal_ids:
                raise ApiError(409, "duplicate_proposal_id", pid)
            if body["base_version"] != self._cur(wid)["version"]:
                raise ApiError(409, "stale_base_version", {"current_version": self._cur(wid)["version"]})
            self.proposal_ids.add(pid)
            v = self._new_version(wid, body["proposed_config"], "controller_auto", pid)
            return {"workflow_id": wid, "version": v, "changed_dims": ["?"]}
        return self._run("auto_apply", op)

    # ------------------------------------------------------------------ misc
    def label(self) -> str:
        return minute_to_label(self.now)


# ---------------------------------------------------------------------------------------- event builders
class EventFactory:
    """Builds simulator-shaped NDJSON events with strictly increasing event ids."""

    def __init__(self, workflow_id: str = "wfA", tenant_id: str = "t1"):
        self.wid, self.tid = workflow_id, tenant_id
        self.eid = 0

    def _id(self):
        self.eid += 1
        return self.eid

    def lead(self, lead: int, person: int, minute: int, lang="hi", tier="1", age="31-45", value="mid") -> dict:
        return {"type": "lead", "ts": fmt_ts(minute), "workflow_id": self.wid, "campaign_id": f"{self.wid}:c0001",
                "lead_id": f"{self.wid}:l{lead:08d}", "person_id": f"{self.wid}:p{person:07d}",
                "features": {"lang": lang, "city_tier": tier, "age_band": age, "value_band": value},
                "event_id": self._id()}

    def call(self, lead: int, person: int, minute: int, connected=True, engaged=False, cohort="default", version=1,
             wm="W1", voice="V1", did="D1", prompt="P1", flag=False, attempt=1) -> dict:
        ev = {"type": "call", "ts": fmt_ts(minute), "tenant_id": self.tid, "workflow_id": self.wid,
              "campaign_id": f"{self.wid}:c0001", "lead_id": f"{self.wid}:l{lead:08d}",
              "person_id": f"{self.wid}:p{person:07d}", "attempt_no": attempt, "campaign_day_index": 0,
              "config_version": version, "cohort_id": cohort,
              "variant": {"welcome_message": wm, "voice": voice, "caller_id": did, "prompt_version": prompt},
              "connected": connected, "engaged": engaged and connected,
              "disposition": "concluded_interested" if engaged else "no_answer", "duration_s": 10, "turns": 2,
              "event_id": self._id()}
        if connected:
            ev["qa"] = {"hallucination_flag": flag, "flow_adherence": 0.9}
        return ev

    def campaign(self, minute: int, leads: int = 10, version: int = 1) -> dict:
        return {"type": "campaign_created", "ts": fmt_ts(minute), "tenant_id": self.tid, "workflow_id": self.wid,
                "campaign_id": f"{self.wid}:c0001", "leads": leads, "config_version_at_creation": version,
                "event_id": self._id()}

    def config_changed(self, minute: int, version: int, actor="supervisor", dims=("voice",), pid=None, aid=None):
        return {"type": "config_changed", "ts": fmt_ts(minute), "workflow_id": self.wid, "version": version,
                "actor": actor, "changed_dims": list(dims), "proposal_id": pid, "approval_id": aid,
                "event_id": self._id()}

    def approval_decided(self, minute: int, aid="apr_00001", status="approved"):
        return {"type": "approval_decided", "ts": fmt_ts(minute), "approval_id": aid, "workflow_id": self.wid,
                "status": status, "reasons": [], "event_id": self._id()}
