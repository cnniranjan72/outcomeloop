"""Synthetic call-row builders for tests that work on the SQLite store directly (no ingestion)."""
from __future__ import annotations

from outcomeloop.db import DB

_EID = [0]


def add_calls(db: DB, wf: int, n: int, conn: int, eng: int = 0, *, minute: int = 0, spread: int = 0,
              cfg_ver: int = 1, wm: str = "W1", voice: str = "V1", did: str = "D1", prompt: str = "P1",
              flags: int = 0, lang: str = "hi", tier: str = "1", age: str = "31-45", val: str = "mid",
              cohort: str = "default"):
    """Insert exactly n call rows with exactly `conn` connected, `eng` engaged (eng <= conn) and `flags`
    hallucination flags (flags <= conn). Rows are spread evenly over [minute, minute+spread)."""
    assert 0 <= eng <= conn <= n and 0 <= flags <= conn
    c = db.code
    codes = (c("cohort", cohort), c("welcome_message", wm), c("voice", voice), c("caller_id", did),
             c("prompt_version", prompt), c("lang", lang), c("city_tier", tier), c("age_band", age),
             c("value_band", val))
    rows = []
    j = 0  # index among connected rows
    for i in range(n):
        _EID[0] += 1
        m = minute + (i * spread // n if spread else 0)
        # Bresenham-style interleaving: outcomes are spread uniformly over time, not front-loaded
        k = (i + 1) * conn // n - i * conn // n
        g = f = 0
        if k:
            g = (j + 1) * eng // conn - j * eng // conn
            f = (j + 1) * flags // conn - j * flags // conn
            j += 1
        rows.append((wf, m, _EID[0], _EID[0], _EID[0], 1, cfg_ver, codes[0], codes[1], codes[2], codes[3], codes[4],
                     k, g, f, codes[5], codes[6], codes[7], codes[8]))
    with db.tx():
        db.conn.executemany("INSERT INTO calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)


def count(db: DB, table: str) -> int:
    return db.q1(f"SELECT COUNT(*) FROM {table}")[0]
