"""Shared pytest setup: put src/ (the controller) and the repo root (the simulator, for parity checks only)
on sys.path, plus tests/ so `fakes` and `helpers` import cleanly."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT / "src", ROOT, Path(__file__).resolve().parent):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

os.environ.setdefault("PYTHONUTF8", "1")


def pytest_collection_modifyitems(config, items):
    if os.environ.get("OUTCOMELOOP_SLOW") == "1":
        return
    skip = pytest.mark.skip(reason="slow end-to-end test: set OUTCOMELOOP_SLOW=1 to run")
    for it in items:
        if "slow" in it.keywords:
            it.add_marker(skip)


@pytest.fixture()
def db(tmp_path):
    from outcomeloop.db import DB
    d = DB(tmp_path / "t.db")
    yield d
    d.close()


@pytest.fixture()
def settings():
    from outcomeloop.config import Settings
    return Settings(tenant_preferences={"kestrel_finance": {"not_before_hour": 11, "max_requests_per_24h": 2},
                                        "northwind_life": {}})
