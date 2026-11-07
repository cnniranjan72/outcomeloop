"""End-to-end: real simulator over HTTP (port 8725), the real Controller, a temp DB. Slow; opt in with
OUTCOMELOOP_SLOW=1. Asserts the governance invariants that must hold on any scenario."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCENARIO = ROOT / "tests" / "fixtures" / "tiny_2day.yaml"
PORT = 8725
URL = f"http://127.0.0.1:{PORT}"


@pytest.fixture()
def sim_server(tmp_path):
    try:   # never collide with a server someone else started
        httpx.get(f"{URL}/health", timeout=1)
        pytest.skip(f"port {PORT} already in use")
    except httpx.HTTPError:
        pass
    log = open(tmp_path / "sim.log", "w", encoding="utf-8")
    env = dict(os.environ, PYTHONUTF8="1")
    proc = subprocess.Popen([sys.executable, "-m", "sim", "serve", "--scenario", str(SCENARIO),
                             "--run-dir", str(tmp_path / "run"), "--port", str(PORT)],
                            cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT, env=env)
    try:
        for _ in range(120):
            if proc.poll() is not None:
                raise RuntimeError(f"simulator exited: {(tmp_path / 'sim.log').read_text(encoding='utf-8')}")
            try:
                if httpx.get(f"{URL}/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.5)
        else:
            raise RuntimeError("simulator did not become healthy")
        yield URL
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()


@pytest.mark.slow
def test_controller_runs_tiny_scenario_to_completion(sim_server, tmp_path):
    from outcomeloop.config import Settings
    from outcomeloop.controller import Controller

    s = Settings(sim_url=sim_server, db_path=str(tmp_path / "ol.db"), http_retries=2)
    c = Controller(s)
    try:
        c.run()
        db = c.db
        http = httpx.Client(base_url=sim_server, timeout=30)
        state = http.get("/sim/state").json()
        assert state["finished"]

        kinds = Counter(k for (k,) in db.q("SELECT kind FROM decisions"))
        assert kinds["controller_start"] == 1 and kinds["controller_finish"] == 1
        assert sum(kinds.values()) > 2, kinds
        assert kinds["bootstrap"] == 1                       # one workflow, bootstrapped once
        assert db.q1("SELECT COUNT(*) FROM calls")[0] > 1000  # history + 2 days were ingested

        for wf in http.get("/workflows").json():
            wid = wf["workflow_id"]
            hist = http.get(f"/workflows/{wid}/config/history").json()
            pids = [h["proposal_id"] for h in hist if h["proposal_id"]]
            assert len(pids) == len(set(pids)), "a proposal id was applied twice"
            for h in hist:
                if not h["actor"].startswith("controller"):
                    continue
                rows = db.q("SELECT proposal_id, state, applied_version FROM proposals WHERE proposal_id=?",
                            (h["proposal_id"],))
                assert len(rows) == 1, f"v{h['version']} has no proposal row in our store"
                assert rows[0][1] == "APPLIED" and rows[0][2] == h["version"], (h, rows)
            # conversely: every APPLIED proposal in our store is a real version in the simulator
            applied = db.q("SELECT proposal_id, applied_version FROM proposals p JOIN workflows w ON p.wf=w.wf"
                           " WHERE w.workflow_id=? AND state='APPLIED'", (wid,))
            versions = {(h["proposal_id"], h["version"]) for h in hist}
            assert set(applied) <= versions
            # governance hygiene: never more open approval-route proposals than one, nothing stuck in flight
            assert db.q1("SELECT COUNT(*) FROM proposals WHERE state IN ('SUBMITTING','APPLYING','AUTO_APPLYING')")[0] == 0
            # we never exceeded the approver's request budget
            reqs = sorted(m for (m,) in db.q("SELECT created_minute FROM proposals WHERE route='approval' AND"
                                              " state!='SUBMIT_FAILED'"))
            cap = wf["governance"]["max_requests_per_24h"]
            assert all(sum(1 for r in reqs if t - 1440 < r <= t) <= cap for t in reqs)
        # the audit trail explains every config change we observed
        for (ver,) in db.q("SELECT version FROM config_versions WHERE actor LIKE 'controller%'"):
            assert db.q1("SELECT COUNT(*) FROM decisions WHERE kind='config_changed' AND config_version=?",
                         (ver,))[0] >= 1
        # non-vacuous: the fixture (seeded) drives at least one change through governance
        assert db.q1("SELECT COUNT(*) FROM proposals WHERE state='APPLIED'")[0] >= 1
        http.close()
    finally:
        c.db.close()
        c.sim.close()
