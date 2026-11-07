"""HTTP client for the simulator. The only way the controller learns anything about the world.

Retry policy:
* Reads (GET) are idempotent: retried with exponential back-off on connection errors, timeouts and 5xx.
* Writes are split by idempotency:
  - `advance` is NOT retried blindly: a timeout may mean time already moved. Callers re-read `/sim/state`.
  - proposals / auto-apply carry our `proposal_id`; apply carries `approval_id`. On timeout we raise
    `Uncertain`; the caller reconciles against `/approvals` or `/config/history` before any retry.
  - LLM / validation spend credits and have no idempotency key: never retried automatically.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Iterator

import httpx

log = logging.getLogger("outcomeloop.sim")


class ApiError(Exception):
    def __init__(self, status: int, code: str, detail: Any):
        super().__init__(f"{status} {code}: {detail}")
        self.status, self.code, self.detail = status, code, detail


class Uncertain(Exception):
    """A write whose outcome is unknown (timeout / connection drop after send). Reconcile, don't assume."""


class SimClient:
    def __init__(self, base_url: str, timeout: float = 120.0, retries: int = 5):
        self.base_url = base_url.rstrip("/")
        self.retries = retries
        # connect fast-fails (a dead simulator is noticed in seconds); reads stay long because one /sim/advance on a
        # load-scale world legitimately takes many seconds
        self.http = httpx.Client(base_url=self.base_url, timeout=httpx.Timeout(timeout, connect=5.0))
        self.calls = 0
        self.errors = 0

    def close(self):
        self.http.close()

    # ------------------------------------------------------------------ plumbing
    @staticmethod
    def _raise_for(r: httpx.Response):
        if r.status_code < 400:
            return
        try:
            body = r.json()
            code, detail = body.get("error") or "http_error", body.get("detail")
        except ValueError:
            code, detail = "http_error", r.text[:500]
        raise ApiError(r.status_code, code, detail)

    def _get(self, path: str, **params) -> Any:
        delay = 0.5
        for attempt in range(self.retries + 1):
            self.calls += 1
            try:
                r = self.http.get(path, params=params or None)
                if r.status_code >= 500 and attempt < self.retries:
                    raise httpx.HTTPStatusError("5xx", request=r.request, response=r)
                self._raise_for(r)
                return r.json()
            except (httpx.TransportError, httpx.HTTPStatusError) as e:
                self.errors += 1
                if attempt == self.retries:
                    raise
                log.warning("GET %s failed (%s), retry %d in %.1fs", path, e, attempt + 1, delay)
                time.sleep(delay)
                delay = min(delay * 2, 10)

    def _write(self, method: str, path: str, body: dict, *, retry_connect: bool = True) -> Any:
        """Send a write. Connection errors *before* the request is sent are safe to retry
        (httpx.ConnectError); anything after that is Uncertain."""
        delay = 0.5
        for attempt in range(self.retries + 1):
            self.calls += 1
            try:
                r = self.http.request(method, path, json=body)
            except httpx.ConnectError as e:
                self.errors += 1
                if not retry_connect or attempt == self.retries:
                    raise Uncertain(f"{method} {path}: {e}") from e
                time.sleep(delay)
                delay = min(delay * 2, 10)
                continue
            except httpx.TransportError as e:   # read timeout, connection reset after send
                self.errors += 1
                raise Uncertain(f"{method} {path}: {e}") from e
            if r.status_code >= 500:
                self.errors += 1
                raise Uncertain(f"{method} {path}: HTTP {r.status_code}")
            self._raise_for(r)
            return r.json()

    # ------------------------------------------------------------------ reads
    def health(self) -> bool:
        try:
            return bool(self._get("/health").get("ok"))
        except Exception:
            return False

    def state(self) -> dict:
        return self._get("/sim/state")

    def workflows(self) -> list[dict]:
        return self._get("/workflows")

    def workflow(self, wid: str) -> dict:
        return self._get(f"/workflows/{wid}")

    def config(self, wid: str) -> dict:
        return self._get(f"/workflows/{wid}/config")

    def config_history(self, wid: str) -> list[dict]:
        return self._get(f"/workflows/{wid}/config/history")

    def list_chunks(self, kind: str, after: int = -1) -> list[dict]:
        return self._get("/events/chunks", kind=kind, after=after)

    def approval(self, aid: str) -> dict:
        return self._get(f"/approvals/{aid}")

    def approvals(self, workflow_id: str | None = None, status: str | None = None) -> list[dict]:
        params = {k: v for k, v in (("workflow_id", workflow_id), ("status", status)) if v}
        return self._get("/approvals", **params)

    def iter_chunk(self, n: int) -> Iterator[dict]:
        """Stream a chunk's NDJSON. Retried as a whole on failure (callers ingest in one transaction)."""
        delay = 0.5
        for attempt in range(self.retries + 1):
            self.calls += 1
            try:
                with self.http.stream("GET", f"/events/chunks/{n}") as r:
                    self._raise_for(r) if r.status_code >= 400 else None
                    lines = list(r.iter_lines())
                break
            except httpx.TransportError as e:
                self.errors += 1
                if attempt == self.retries:
                    raise
                log.warning("chunk %d fetch failed (%s), retrying", n, e)
                time.sleep(delay)
                delay = min(delay * 2, 10)
        loads = json.loads
        for line in lines:
            if line:
                yield loads(line)

    # ------------------------------------------------------------------ writes
    def advance(self, minutes: int) -> dict:
        return self._write("POST", "/sim/advance", {"minutes": minutes}, retry_connect=True)

    def request_approval(self, body: dict) -> dict:
        return self._write("POST", "/approvals", body)

    def apply(self, wid: str, approval_id: str) -> dict:
        return self._write("POST", f"/workflows/{wid}/apply", {"approval_id": approval_id})

    def auto_apply(self, wid: str, body: dict) -> dict:
        return self._write("PUT", f"/workflows/{wid}/config", body)

    def suggest_fixes(self, wid: str, problem: str) -> dict:
        return self._write("POST", "/llm/suggest-fixes", {"workflow_id": wid, "problem": problem},
                           retry_connect=False)

    def validate(self, wid: str, prompt_version: str, n: int) -> dict:
        return self._write("POST", "/validation/runs", {"workflow_id": wid, "prompt_version": prompt_version, "n": n},
                           retry_connect=False)
