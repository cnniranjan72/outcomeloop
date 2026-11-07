"""SQLite persistence: schema, small repository helpers, append-only audit log.

Durability: WAL + synchronous=FULL. Every logical step (one chunk ingested, one proposal state change, one
decision) is one transaction, so a SIGKILL at any instant leaves a consistent store.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS codes (kind TEXT, value TEXT, code INTEGER, PRIMARY KEY (kind, value));
CREATE TABLE IF NOT EXISTS chunks (
  chunk INTEGER PRIMARY KEY, kind TEXT, events INTEGER, first_event_id INTEGER, last_event_id INTEGER,
  until_minute INTEGER, ingested_at REAL, ingest_seconds REAL);
CREATE TABLE IF NOT EXISTS workflows (wf INTEGER PRIMARY KEY, workflow_id TEXT UNIQUE, tenant_id TEXT, spec TEXT);
CREATE TABLE IF NOT EXISTS persons (wf INTEGER, person INTEGER, lang INTEGER, tier INTEGER, age INTEGER, val INTEGER,
  PRIMARY KEY (wf, person)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS leads (wf INTEGER, lead INTEGER, person INTEGER, campaign_day INTEGER,
  concluded_minute INTEGER, PRIMARY KEY (wf, lead)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS campaigns (wf INTEGER, campaign_id TEXT, day INTEGER, leads INTEGER,
  config_version INTEGER, PRIMARY KEY (wf, campaign_id)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS calls (
  wf INTEGER NOT NULL, minute INTEGER NOT NULL, event_id INTEGER NOT NULL,
  person INTEGER, lead INTEGER, attempt INTEGER, cfg_ver INTEGER, cohort INTEGER,
  wm INTEGER, voice INTEGER, did INTEGER, prompt INTEGER,
  conn INTEGER, eng INTEGER, flag INTEGER,
  lang INTEGER, tier INTEGER, age INTEGER, val INTEGER,
  PRIMARY KEY (wf, minute, event_id)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS config_versions (
  wf INTEGER, version INTEGER, actor TEXT, minute INTEGER, changed_dims TEXT, proposal_id TEXT, approval_id TEXT,
  config TEXT, event_id INTEGER, PRIMARY KEY (wf, version));
CREATE TABLE IF NOT EXISTS cohorts (
  wf INTEGER, cohort_id TEXT, position INTEGER, where_json TEXT, status TEXT, created_minute INTEGER,
  rationale TEXT, PRIMARY KEY (wf, cohort_id));
CREATE TABLE IF NOT EXISTS experiments (
  experiment_id TEXT PRIMARY KEY, wf INTEGER, dim TEXT, status TEXT, data TEXT, created_minute INTEGER,
  updated_minute INTEGER);
CREATE TABLE IF NOT EXISTS proposals (
  proposal_id TEXT PRIMARY KEY, wf INTEGER, route TEXT, state TEXT, kind TEXT, base_version INTEGER,
  body TEXT, approval_id TEXT, approval TEXT, applied_version INTEGER, created_minute INTEGER,
  updated_minute INTEGER, notes TEXT);
CREATE INDEX IF NOT EXISTS proposals_wf_state ON proposals (wf, state);
CREATE TABLE IF NOT EXISTS incidents (
  incident_id TEXT PRIMARY KEY, wf INTEGER, type TEXT, state TEXT, opened_minute INTEGER, closed_minute INTEGER,
  data TEXT);
CREATE TABLE IF NOT EXISTS credits_ledger (
  id INTEGER PRIMARY KEY AUTOINCREMENT, minute INTEGER, wf INTEGER, kind TEXT, purpose TEXT, state TEXT,
  cost REAL, request TEXT, response TEXT);
CREATE TABLE IF NOT EXISTS decisions (
  decision_id INTEGER PRIMARY KEY AUTOINCREMENT, minute INTEGER, wall REAL, wf INTEGER, kind TEXT, actor TEXT,
  summary TEXT, reasoning TEXT, evidence TEXT, outcome TEXT,
  proposal_id TEXT, approval_id TEXT, config_version INTEGER, experiment_id TEXT, incident_id TEXT);
CREATE INDEX IF NOT EXISTS decisions_wf_minute ON decisions (wf, minute);
CREATE INDEX IF NOT EXISTS decisions_minute ON decisions (minute);
CREATE INDEX IF NOT EXISTS leads_wf_day ON leads (wf, campaign_day);
CREATE TABLE IF NOT EXISTS metrics (
  id INTEGER PRIMARY KEY AUTOINCREMENT, minute INTEGER, wall REAL, name TEXT, value REAL, labels TEXT);
CREATE INDEX IF NOT EXISTS metrics_name ON metrics (name, minute);
CREATE TRIGGER IF NOT EXISTS decisions_append_only_u BEFORE UPDATE ON decisions
  BEGIN SELECT RAISE(ABORT, 'decisions is append-only'); END;
CREATE TRIGGER IF NOT EXISTS decisions_append_only_d BEFORE DELETE ON decisions
  BEGIN SELECT RAISE(ABORT, 'decisions is append-only'); END;
"""


def dumps(o: Any) -> str:
    return json.dumps(o, separators=(",", ":"), sort_keys=True, default=str)


class DB:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), isolation_level=None, timeout=30)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=FULL")
        self.conn.execute("PRAGMA temp_store=MEMORY")
        self.conn.execute("PRAGMA cache_size=-200000")  # ~200 MB page cache
        self.conn.executescript(SCHEMA)
        self._load_codes()
        self._in_tx = False

    def _load_codes(self):
        self._codes: dict[tuple[str, str], int] = {}
        self._rev: dict[tuple[str, int], str] = {}
        for kind, value, code in self.conn.execute("SELECT kind, value, code FROM codes"):
            self._codes[(kind, value)] = code
            self._rev[(kind, code)] = value

    # ------------------------------------------------------------------ transactions
    def begin(self):
        self.conn.execute("BEGIN IMMEDIATE")
        self._in_tx = True

    def commit(self):
        self.conn.execute("COMMIT")
        self._in_tx = False

    def rollback(self):
        if self._in_tx:
            self.conn.execute("ROLLBACK")
            self._in_tx = False
            # codes created inside the rolled-back transaction are gone from the table: drop them from the
            # cache too, or a later commit would write rows with a code whose mapping was never persisted
            self._load_codes()

    class _Tx:
        def __init__(self, db: "DB"):
            self.db = db
            self.outer = db._in_tx

        def __enter__(self):
            if not self.outer:
                self.db.begin()
            return self.db

        def __exit__(self, et, e, tb):
            if self.outer:
                return False
            if et is None:
                self.db.commit()
            else:
                self.db.rollback()
            return False

    def tx(self) -> "DB._Tx":
        return DB._Tx(self)

    def q(self, sql: str, args: tuple | list = ()) -> list[tuple]:
        return self.conn.execute(sql, args).fetchall()

    def q1(self, sql: str, args: tuple | list = ()):
        r = self.conn.execute(sql, args).fetchone()
        return r

    def x(self, sql: str, args: tuple | list = ()):
        return self.conn.execute(sql, args)

    # ------------------------------------------------------------------ codes (string <-> small int)
    def code(self, kind: str, value: str | None) -> int:
        if value is None:
            return -1
        k = (kind, value)
        c = self._codes.get(k)
        if c is None:
            c = 1 + max([cc for (kk, _), cc in self._codes.items() if kk == kind], default=-1)
            self.conn.execute("INSERT OR IGNORE INTO codes VALUES (?,?,?)", (kind, value, c))
            self._codes[k] = c
            self._rev[(kind, c)] = value
        return c

    def decode(self, kind: str, code: int) -> str | None:
        return self._rev.get((kind, code))

    # ------------------------------------------------------------------ key/value state
    def kv_get(self, k: str, default=None):
        r = self.q1("SELECT v FROM kv WHERE k=?", (k,))
        return json.loads(r[0]) if r else default

    def kv_set(self, k: str, v: Any):
        self.x("INSERT INTO kv (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, dumps(v)))

    def meta_get(self, k: str):
        r = self.q1("SELECT v FROM meta WHERE k=?", (k,))
        return r[0] if r else None

    def meta_set(self, k: str, v: str):
        self.x("INSERT INTO meta (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))

    # ------------------------------------------------------------------ audit
    def decide(self, minute: int, wf: int | None, kind: str, summary: str, *, reasoning: str = "",
               evidence: Any = None, outcome: str = "", actor: str = "controller", proposal_id: str | None = None,
               approval_id: str | None = None, config_version: int | None = None,
               experiment_id: str | None = None, incident_id: str | None = None) -> int:
        cur = self.x(
            "INSERT INTO decisions (minute, wall, wf, kind, actor, summary, reasoning, evidence, outcome, proposal_id,"
            " approval_id, config_version, experiment_id, incident_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (minute, time.time(), wf, kind, actor, summary, reasoning, dumps(evidence) if evidence is not None else None,
             outcome, proposal_id, approval_id, config_version, experiment_id, incident_id))
        return cur.lastrowid

    def metric(self, minute: int, name: str, value: float, labels: dict | None = None):
        self.x("INSERT INTO metrics (minute, wall, name, value, labels) VALUES (?,?,?,?,?)",
               (minute, time.time(), name, float(value), dumps(labels) if labels else None))

    def close(self):
        self.conn.close()
