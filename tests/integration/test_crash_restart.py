"""Crash/restart at the process level (slow; OUTCOMELOOP_SLOW=1): the controller subprocess is hard-killed twice
(Popen.kill = SIGKILL / TerminateProcess) at different points, restarted on the same DB, and must finish with the
same invariants as an uninterrupted run. The full 9-kill harness is scripts/crash_recovery.py."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import time
from collections import Counter

import httpx
import pytest

from test_end_to_end import ROOT, sim_server  # noqa: F401  (fixture reuse)


def _launch(url, db, log):
    env = dict(os.environ, PYTHONUTF8="1", OUTCOMELOOP_DB=str(db), PYTHONPATH=str(ROOT / "src"))
    return subprocess.Popen([sys.executable, "-m", "outcomeloop", "run", "--url", url], cwd=str(ROOT),
                            stdout=log, stderr=subprocess.STDOUT, env=env)


def _sim_minute(url):
    return httpx.get(f"{url}/sim/state", timeout=10).json()["sim_minute"]


@pytest.mark.slow
def test_kill_twice_restart_finishes_without_duplicates(sim_server, tmp_path):
    url, db = sim_server, tmp_path / "ol.db"
    log = open(tmp_path / "ctl.log", "w", encoding="utf-8")
    kills = []
    for target in (0, 900):            # 1) during start-up / history ingestion, 2) mid-D0 after decisions began
        p = _launch(url, db, log)
        deadline = time.time() + 120
        while time.time() < deadline and p.poll() is None:
            if target == 0 and db.exists():
                time.sleep(0.5)
                break
            if target and _sim_minute(url) >= target:
                break
            time.sleep(0.2)
        assert p.poll() is None, "controller exited before it could be killed"
        p.kill()
        p.wait()
        kills.append(_sim_minute(url))
    p = _launch(url, db, log)
    assert p.wait(timeout=600) == 0
    log.close()

    st = httpx.get(f"{url}/sim/state", timeout=10).json()
    c = sqlite3.connect(db)
    assert st["finished"]
    # exactly-once ingestion: every chunk once, event count equal to the simulator's
    chunks = [r[0] for r in c.execute("SELECT chunk FROM chunks")]
    assert len(chunks) == len(set(chunks)) == st["chunks"]
    assert c.execute("SELECT SUM(events) FROM chunks").fetchone()[0] == st["last_event_id"]
    # no double application: each of our proposal ids appears at most once in the simulator's history,
    # and every controller version maps to exactly one APPLIED row
    wid = c.execute("SELECT workflow_id FROM workflows").fetchone()[0]
    hist = httpx.get(f"{url}/workflows/{wid}/config/history", timeout=10).json()
    ctl = [h for h in hist if h["actor"].startswith("controller")]
    assert all(n == 1 for n in Counter(h["proposal_id"] for h in ctl).values())
    applied = {r[0]: r[1] for r in c.execute("SELECT proposal_id, applied_version FROM proposals WHERE state='APPLIED'")}
    assert {h["proposal_id"]: h["version"] for h in ctl} == applied
    # nothing left in flight; every approval the simulator knows is ours and known to us
    assert c.execute("SELECT COUNT(*) FROM proposals WHERE state IN ('SUBMITTING','APPLYING','AUTO_APPLYING')"
                     ).fetchone()[0] == 0
    known = {r[0] for r in c.execute("SELECT approval_id FROM proposals WHERE approval_id IS NOT NULL")}
    assert {a["approval_id"] for a in httpx.get(f"{url}/approvals", timeout=10).json()} <= known
    # learning kept: bootstrap ran once; restarts recorded
    kinds = Counter(r[0] for r in c.execute("SELECT kind FROM decisions"))
    assert kinds["bootstrap"] == 1 and kinds["controller_finish"] == 1 and kinds["controller_restart"] >= 1
    assert kills[1] >= 900
