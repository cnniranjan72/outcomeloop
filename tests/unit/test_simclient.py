"""SimClient retry semantics: reads retry transient failures (bounded); writes never retry blindly after the request
may have been received — a timeout is Uncertain, to be reconciled, never treated as failure."""
import httpx
import pytest

from outcomeloop.simclient import ApiError, SimClient, Uncertain


def client(handler, retries=3):
    c = SimClient("http://sim", retries=retries)
    c.http = httpx.Client(base_url="http://sim", transport=httpx.MockTransport(handler))
    return c


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("outcomeloop.simclient.time.sleep", lambda s: None)


def test_get_retries_5xx_then_succeeds():
    calls = []

    def h(req):
        calls.append(1)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, json={"sim_minute": 15})
    assert client(h).state()["sim_minute"] == 15
    assert len(calls) == 3


def test_get_4xx_is_not_retried_and_carries_the_error_code():
    calls = []

    def h(req):
        calls.append(1)
        return httpx.Response(404, json={"error": "unknown_workflow", "detail": "x"})
    with pytest.raises(ApiError) as e:
        client(h).workflow("x")
    assert e.value.status == 404 and e.value.code == "unknown_workflow" and len(calls) == 1


def test_get_retries_are_bounded():
    calls = []

    def h(req):
        calls.append(1)
        raise httpx.ConnectError("down", request=req)
    with pytest.raises(httpx.ConnectError):
        client(h, retries=3).state()
    assert len(calls) == 4          # first try + 3 retries, then give up


def test_write_timeout_after_send_is_uncertain_and_not_retried():
    calls = []

    def h(req):
        calls.append(1)
        raise httpx.ReadTimeout("slow", request=req)
    with pytest.raises(Uncertain):
        client(h).request_approval({"proposal_id": "p1"})
    assert len(calls) == 1          # the approval may exist remotely: reconcile, don't resend


def test_write_5xx_is_uncertain():
    with pytest.raises(Uncertain):
        client(lambda req: httpx.Response(500)).apply("wf", "apr_1")


def test_write_connect_refused_before_send_is_retried():
    calls = []

    def h(req):
        calls.append(1)
        if len(calls) < 2:
            raise httpx.ConnectError("refused", request=req)
        return httpx.Response(200, json={"approval_id": "apr_1", "status": "pending"})
    assert client(h).request_approval({"proposal_id": "p1"})["approval_id"] == "apr_1"
    assert len(calls) == 2


def test_write_conflict_is_a_definite_answer():
    def h(req):
        return httpx.Response(409, json={"error": "stale_base_version", "detail": {"current_version": 4}})
    with pytest.raises(ApiError) as e:
        client(h).apply("wf", "apr_1")
    assert e.value.code == "stale_base_version" and e.value.detail == {"current_version": 4}


def test_credit_spending_calls_never_retry_even_on_connect_error():
    calls = []

    def h(req):
        calls.append(1)
        raise httpx.ConnectError("refused", request=req)
    with pytest.raises(Uncertain):
        client(h).validate("wf", "P1", 100)
    assert len(calls) == 1
