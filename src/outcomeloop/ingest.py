"""Event ingestion (C1): exactly-once, restartable, backlog-safe.

* Chunks are processed in order. A chunk's rows + the `chunks` checkpoint row commit in ONE transaction.
* `INSERT OR IGNORE` on natural keys makes a replayed chunk a no-op (defence in depth).
* Events needing side effects (config_changed, approval_decided) go to the `inbox` table in the same
  transaction; handlers mark them done in their own transactions, so a crash between the two re-runs the
  (idempotent) handler instead of losing the event.
* Lead features are joined onto every call row at ingest (lead events always precede that lead's calls).
"""
from __future__ import annotations

import logging
import time

import numpy as np

from .db import DB, dumps
from .simclient import SimClient
from .timeutil import ts_to_minute

log = logging.getLogger("outcomeloop.ingest")

FEATS = ("lang", "city_tier", "age_band", "value_band")

INBOX_SQL = """CREATE TABLE IF NOT EXISTS inbox (event_id INTEGER PRIMARY KEY, type TEXT, wf INTEGER,
  minute INTEGER, payload TEXT, done INTEGER DEFAULT 0)"""


def _suffix_int(s: str, marker: str) -> int:
    return int(s[s.rindex(marker) + len(marker):])


def apply_rollups(db: DB, calls: list[tuple]) -> None:
    """Refresh the hourly rollups (did_hour, arm_hour) for every workflow-hour these call rows touch, recomputed from
    the `calls` table itself. A rollup is therefore a pure function of the stored rows: replaying a chunk (even with
    its checkpoint gone) cannot double-count, by construction. Each refresh reads one hour of one workflow through
    the (wf, minute) primary key. The single implementation used by ingestion (inside the chunk's transaction) and
    by tests."""
    touched = {(row[0], row[1] // 60) for row in calls}
    for wf, hb in sorted(touched):
        lo, hi = hb * 60, hb * 60 + 60
        db.x("DELETE FROM did_hour WHERE wf=? AND hb=?", (wf, hb))
        db.x("DELETE FROM arm_hour WHERE wf=? AND hb=?", (wf, hb))
        db.x("INSERT INTO did_hour SELECT wf, ?, did, COUNT(*), SUM(conn) FROM calls WHERE wf=? AND minute>=?"
             " AND minute<? GROUP BY did", (hb, wf, lo, hi))
        db.x("INSERT INTO arm_hour SELECT wf, ?, cfg_ver, wm, voice, lang, tier, age, val, COUNT(*), SUM(conn),"
             " SUM(eng) FROM calls WHERE wf=? AND minute>=? AND minute<? GROUP BY cfg_ver, wm, voice, lang, tier,"
             " age, val", (hb, wf, lo, hi))


class FeatureStore:
    """person index -> packed features, per workflow. Person ids are dense per workflow, so numpy arrays."""

    def __init__(self, db: DB):
        self.db = db
        self.arr: dict[int, np.ndarray] = {}
        for wf, person, lang, tier, age, val in db.q("SELECT wf, person, lang, tier, age, val FROM persons"):
            self._set(wf, person, lang, tier, age, val)

    def _set(self, wf, person, lang, tier, age, val):
        a = self.arr.get(wf)
        if a is None or person >= len(a):
            n = max(1024, (person + 1) * 2 if a is None else max(len(a) * 2, person + 1))
            b = np.full(n, -1, dtype=np.int32)
            if a is not None:
                b[: len(a)] = a
            a = self.arr[wf] = b
        a[person] = (lang << 12) | (tier << 8) | (age << 4) | val

    def get(self, wf: int, person: int) -> tuple[int, int, int, int]:
        a = self.arr.get(wf)
        if a is None or person >= len(a) or a[person] < 0:
            return (-1, -1, -1, -1)
        p = int(a[person])
        return (p >> 12, (p >> 8) & 15, (p >> 4) & 15, p & 15)

    def has(self, wf: int, person: int) -> bool:
        a = self.arr.get(wf)
        return a is not None and person < len(a) and a[person] >= 0


class Ingestor:
    def __init__(self, db: DB, sim: SimClient):
        self.db = db
        self.sim = sim
        db.x(INBOX_SQL)
        db.x("CREATE INDEX IF NOT EXISTS inbox_pending ON inbox (wf, event_id) WHERE done=0")
        self.features = FeatureStore(db)
        self._backfill_rollups()
        self.events_total = 0
        self.seconds_total = 0.0

    def _backfill_rollups(self):
        """A store created before the rollups existed (or restored from a backup) gets them rebuilt from the call
        rows once, so an upgraded controller restarting on an old DB stays consistent."""
        db = self.db
        if db.q1("SELECT 1 FROM calls LIMIT 1") and not db.q1("SELECT 1 FROM did_hour LIMIT 1"):
            with db.tx():
                db.x("INSERT INTO did_hour SELECT wf, (minute - ((minute % 60) + 60) % 60) / 60, did, COUNT(*),"
                     " SUM(conn) FROM calls GROUP BY 1, 2, 3")
                db.x("INSERT INTO arm_hour SELECT wf, (minute - ((minute % 60) + 60) % 60) / 60, cfg_ver, wm, voice,"
                     " lang, tier, age, val, COUNT(*), SUM(conn), SUM(eng) FROM calls GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9")

    def last_chunk(self) -> int:
        r = self.db.q1("SELECT MAX(chunk) FROM chunks")
        return -1 if r[0] is None else r[0]

    def pending_chunks(self) -> list[dict]:
        after = self.last_chunk()
        out = self.sim.list_chunks("history", after) + self.sim.list_chunks("events", after)
        return sorted(out, key=lambda c: c["chunk"])

    def ingest_all(self) -> int:
        n = 0
        for ch in self.pending_chunks():
            n += self.ingest_chunk(ch)
        return n

    def ingest_chunk(self, meta: dict) -> int:
        try:
            return self._ingest_chunk(meta)
        except BaseException:
            # the transaction rolled back: persons first seen in this chunk were not persisted, so the in-memory
            # feature store must forget them too (else a retry would skip their `persons` rows)
            self.features = FeatureStore(self.db)
            raise

    def _ingest_chunk(self, meta: dict) -> int:
        t0 = time.perf_counter()
        db = self.db
        code = db.code
        fs = self.features
        calls, persons, leads, concl, camps, inbox, cfgv = [], [], [], [], [], [], []
        wf_codes: dict[str, int] = {}
        n = 0
        with db.tx():
            if db.q1("SELECT 1 FROM chunks WHERE chunk=?", (meta["chunk"],)):
                return 0  # already ingested (crash after commit, before caller noticed)
            for ev in self.sim.iter_chunk(meta["chunk"]):
                n += 1
                t = ev["type"]
                wid = ev.get("workflow_id")
                wf = wf_codes.get(wid)
                if wf is None and wid is not None:
                    wf = wf_codes[wid] = code("wf", wid)
                if t == "call":
                    person = _suffix_int(ev["person_id"], ":p")
                    lang, tier, age, val = fs.get(wf, person)
                    v = ev["variant"]
                    qa = ev.get("qa") or {}
                    minute = ts_to_minute(ev["ts"])
                    calls.append((wf, minute, ev["event_id"], person, _suffix_int(ev["lead_id"], ":l"),
                                  ev["attempt_no"], ev["config_version"], code("cohort", ev.get("cohort_id")),
                                  code("welcome_message", v["welcome_message"]), code("voice", v["voice"]),
                                  code("caller_id", v["caller_id"]), code("prompt_version", v["prompt_version"]),
                                  int(ev["connected"]), int(ev["engaged"]), int(bool(qa.get("hallucination_flag"))),
                                  lang, tier, age, val))
                    if ev["engaged"]:
                        concl.append((minute, wf, _suffix_int(ev["lead_id"], ":l")))
                elif t == "lead":
                    person = _suffix_int(ev["person_id"], ":p")
                    f = ev["features"]
                    c = (code("lang", f["lang"]), code("city_tier", f["city_tier"]),
                         code("age_band", f["age_band"]), code("value_band", f["value_band"]))
                    if not fs.has(wf, person):
                        fs._set(wf, person, *c)
                        persons.append((wf, person, *c))
                    leads.append((wf, _suffix_int(ev["lead_id"], ":l"), person, ts_to_minute(ev["ts"]) // 1440))
                elif t == "campaign_created":
                    camps.append((wf, ev["campaign_id"], ts_to_minute(ev["ts"]) // 1440, ev["leads"],
                                  ev["config_version_at_creation"]))
                elif t in ("config_changed", "approval_decided"):
                    inbox.append((ev["event_id"], t, wf, ts_to_minute(ev["ts"]), dumps(ev)))
                    if t == "config_changed":
                        cfgv.append((wf, ev["version"], ev["actor"], ts_to_minute(ev["ts"]),
                                     dumps(ev.get("changed_dims")), ev.get("proposal_id"), ev.get("approval_id"),
                                     ev["event_id"]))
            if persons:
                db.conn.executemany("INSERT OR IGNORE INTO persons VALUES (?,?,?,?,?,?)", persons)
            if leads:
                db.conn.executemany("INSERT OR IGNORE INTO leads (wf, lead, person, campaign_day) VALUES (?,?,?,?)",
                                    leads)
            if camps:
                db.conn.executemany("INSERT OR IGNORE INTO campaigns VALUES (?,?,?,?,?)", camps)
            if calls:
                db.conn.executemany("INSERT OR IGNORE INTO calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", calls)
                # exactly-once by the same argument as the rows: the chunk's transaction commits with its checkpoint
                apply_rollups(db, calls)
            if concl:
                db.conn.executemany("UPDATE leads SET concluded_minute=? WHERE wf=? AND lead=? AND concluded_minute IS NULL",
                                    concl)
            if cfgv:
                db.conn.executemany(
                    "INSERT OR IGNORE INTO config_versions (wf, version, actor, minute, changed_dims, proposal_id,"
                    " approval_id, event_id) VALUES (?,?,?,?,?,?,?,?)", cfgv)
            if inbox:
                db.conn.executemany("INSERT OR IGNORE INTO inbox (event_id, type, wf, minute, payload) VALUES (?,?,?,?,?)",
                                    inbox)
            dt = time.perf_counter() - t0
            db.x("INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?)",
                 (meta["chunk"], meta["kind"], n, meta.get("first_event_id"), meta.get("last_event_id"),
                  meta.get("until_minute"), time.time(), dt))
        self.events_total += n
        self.seconds_total += dt
        log.debug("chunk %s: %d events in %.2fs", meta["chunk"], n, dt)
        return n

    def inbox(self) -> list[tuple]:
        return self.db.q("SELECT event_id, type, wf, minute, payload FROM inbox WHERE done=0 ORDER BY event_id")

    def mark_done(self, event_id: int):
        self.db.x("UPDATE inbox SET done=1 WHERE event_id=?", (event_id,))
