"""OutcomeLoop CLI.

  python -m outcomeloop run --url http://127.0.0.1:8700          # the controller (what run.sh starts)
  python -m outcomeloop why nw_renewal --at "D3 14:00"           # why did X change at T, who approved, what next
  python -m outcomeloop supervisor ks_cancel                     # one screen for a client supervisor
  python -m outcomeloop status                                   # loop health for on-call
  python -m outcomeloop alerts                                   # paging rules; exit 1 if one fires
  python -m outcomeloop serve-views --port 8800                  # read-only HTTP: /status /alerts /supervisor/<wf>
  python -m outcomeloop audit --wf nw_renewal --kind proposal_submitted
  python -m outcomeloop customer nw_renewal:p0004567 --day 3     # what did this person hear, and why
All read commands only read the SQLite store (OUTCOMELOOP_DB, default state/outcomeloop.db).
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from .config import Settings


def main(argv=None):
    ap = argparse.ArgumentParser(prog="outcomeloop")
    ap.add_argument("--db", default=os.environ.get("OUTCOMELOOP_DB", "state/outcomeloop.db"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--url", default="http://127.0.0.1:8700")
    r.add_argument("--log-level", default=os.environ.get("OUTCOMELOOP_LOG", "INFO"))
    w = sub.add_parser("why")
    w.add_argument("workflow")
    w.add_argument("--at", required=True, help='"D3 14:00", ISO timestamp, or sim minute')
    sv = sub.add_parser("supervisor")
    sv.add_argument("workflow")
    sub.add_parser("status")
    sub.add_parser("alerts", help="evaluate paging rules; exit 1 if any fires")
    sv2 = sub.add_parser("serve-views", help="read-only HTTP front for the views")
    sv2.add_argument("--port", type=int, default=8800)
    au = sub.add_parser("audit")
    au.add_argument("--wf")
    au.add_argument("--kind")
    au.add_argument("--limit", type=int, default=50)
    de = sub.add_parser("decision", help="one decision in full: why, evidence, links, before/after")
    de.add_argument("decision_id", type=int)
    de.add_argument("--full", action="store_true", help="print the whole evidence JSON")
    lc = sub.add_parser("lifecycle", help="whole life of an experiment (exp-..), incident (inc-..) or proposal (ol-..)")
    lc.add_argument("ref")
    cu = sub.add_parser("customer")
    cu.add_argument("person_id")
    cu.add_argument("--day", type=int)
    a = ap.parse_args(argv)
    os.environ["OUTCOMELOOP_DB"] = a.db

    if a.cmd == "run":
        logging.basicConfig(level=a.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                            stream=sys.stdout)
        logging.getLogger("httpx").setLevel(logging.WARNING)
        from .controller import Controller
        s = Settings.load(a.url)
        c = Controller(s)
        c.run()
        if c.stopping:
            raise SystemExit(143)   # requested stop, not "scenario finished": run.sh restarts unless it asked
        return
    from . import views
    from .db import DB
    db = DB(a.db)
    if a.cmd == "why":
        print(views.why(db, a.workflow, a.at))
    elif a.cmd == "supervisor":
        print(views.supervisor(db, a.workflow))
    elif a.cmd == "status":
        print(views.status(db))
    elif a.cmd == "alerts":
        text, firing = views.alerts(db)
        print(text)
        raise SystemExit(1 if firing else 0)
    elif a.cmd == "serve-views":
        db.close()
        views.serve(a.db, a.port)
    elif a.cmd == "audit":
        print(views.audit(db, a.wf, a.kind, a.limit))
    elif a.cmd == "decision":
        print(views.decision(db, a.decision_id, 10_000 if a.full else 60))
    elif a.cmd == "lifecycle":
        print(views.lifecycle(db, a.ref))
    elif a.cmd == "customer":
        print(views.customer(db, a.person_id, a.day))


if __name__ == "__main__":
    main()
