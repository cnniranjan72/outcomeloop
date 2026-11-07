"""Sharding prototype: shards that each ingest only their own workflows store exactly what one process stores."""
import json

import httpx

from fakes import EventFactory
from outcomeloop.db import DB
from outcomeloop.ingest import Ingestor, shard_of, workflow_line_filter
from outcomeloop.simclient import SimClient


def _client(body: bytes):
    c = SimClient("http://sim")
    c.http = httpx.Client(base_url="http://sim", transport=httpx.MockTransport(lambda r: httpx.Response(200, content=body)))
    return c


def _chunk():
    a, b = EventFactory("wfA"), EventFactory("wfB")
    b.eid = 1000
    evs = [a.lead(1, 101, 100), b.lead(1, 201, 100), a.call(1, 101, 110, engaged=True), b.call(1, 201, 115),
           b.call(1, 201, 130, connected=False), a.call(1, 101, 140, connected=False)]
    evs.sort(key=lambda e: e["ts"])
    return evs, "".join(json.dumps(e, separators=(",", ":")) + "\n" for e in evs).encode()


def _calls(db):
    return sorted((db.decode("wf", wf), m, eid) for wf, m, eid in db.q("SELECT wf, minute, event_id FROM calls"))


def test_two_shards_store_exactly_what_one_process_stores(tmp_path):
    evs, body = _chunk()
    meta = {"chunk": 0, "kind": "events", "events": len(evs)}
    full = DB(tmp_path / "full.db")
    Ingestor(full, _client(body)).ingest_chunk(meta)
    parts = []
    for name, mine in (("a", {"wfA"}), ("b", {"wfB"})):
        db = DB(tmp_path / f"{name}.db")
        assert Ingestor(db, _client(body), workflows=mine).ingest_chunk(meta) > 0
        parts += _calls(db)
    assert sorted(parts) == _calls(full) and len(parts) == 4


def test_line_filter_keeps_own_and_workflowless_lines_only():
    keep = workflow_line_filter({"wfA"})
    assert keep('{"type":"call","workflow_id":"wfA","x":1}')
    assert not keep('{"type":"call","workflow_id":"wfB","x":1}')
    assert keep('{"type":"tick"}')                       # no workflow: kept, parsing decides


def test_shard_assignment_is_stable_and_spreads():
    ids = [f"wf{i}" for i in range(120)]
    a = [shard_of(w, 4) for w in ids]
    assert a == [shard_of(w, 4) for w in ids] and set(a) == {0, 1, 2, 3}
    assert max(a.count(k) for k in range(4)) < 45      # roughly even
