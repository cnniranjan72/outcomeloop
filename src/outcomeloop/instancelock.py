"""One controller per state file.

Two controllers on the same SQLite file would both plan, submit and apply: a duplicate-application risk the
simulator's idempotency keys only partly catch (our proposal ids are derived from local state, so two processes
can mint different ids for the same intent). An exclusive OS lock on `<db>.lock` is taken before the database is
opened and held for the process lifetime. The OS releases it on any exit, including SIGKILL, so a crash never
leaves a stale lock and restart recovery is unaffected.
"""
from __future__ import annotations

import os
from pathlib import Path


class AlreadyRunning(SystemExit):
    pass


class InstanceLock:
    def __init__(self, db_path: str):
        self.path = Path(str(db_path) + ".lock")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = None

    def acquire(self) -> "InstanceLock":
        fh = open(self.path, "a+")
        try:
            if os.name == "nt":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            raise AlreadyRunning(f"another controller already holds {self.path}; refusing to start a second instance "
                                 f"on the same state (it would duplicate submissions and applies)")
        fh.seek(0)
        fh.truncate()
        fh.write(f"pid {os.getpid()}\n")
        fh.flush()
        self.fh = fh
        return self

    def release(self):
        if self.fh:
            try:
                if os.name == "nt":
                    import msvcrt
                    self.fh.seek(0)
                    msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
            finally:
                self.fh.close()
                self.fh = None
