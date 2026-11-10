import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from rfc_rag.interfaces import httplog


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(httplog.RequestLog)

    @app.get("/ok")
    def ok():
        return {"ok": True}

    @app.get("/boom")
    def boom():
        raise RuntimeError("kaboom")

    return app


def _lines(caplog) -> list[dict]:
    return [json.loads(r.message) for r in caplog.records
            if r.name == "rfc_rag.http" and r.message.startswith("{")]


def test_a_successful_request_logs_one_line(caplog):
    caplog.set_level("INFO", logger="rfc_rag.http")
    TestClient(_app()).get("/ok")
    entries = _lines(caplog)
    assert len(entries) == 1
    assert entries[0]["status"] == 200
    assert entries[0]["path"] == "/ok"
    assert "ms" in entries[0] and "request_id" in entries[0]


def test_a_failing_request_logs_the_same_shape(caplog):
    caplog.set_level("INFO", logger="rfc_rag.http")
    r = TestClient(_app(), raise_server_exceptions=False).get("/boom")
    entry = _lines(caplog)[-1]
    assert r.status_code == 500
    assert entry["status"] == 500
    assert entry["error"] == "RuntimeError"
    assert entry["level"] == "warn"
    assert set(entry) >= {"ts", "request_id", "method", "path", "status", "ms"}


def test_errors_do_not_leak_the_message_to_the_caller():
    r = TestClient(_app(), raise_server_exceptions=False).get("/boom")
    assert "kaboom" not in r.text
    assert r.json()["request_id"] == r.headers["x-request-id"]


def test_every_response_carries_a_request_id():
    client = TestClient(_app())
    first = client.get("/ok").headers["x-request-id"]
    second = client.get("/ok").headers["x-request-id"]
    assert first != second


def test_summary_counts_statuses_and_percentiles():
    httplog.counters.clear()
    httplog.latencies.clear()
    client = TestClient(_app(), raise_server_exceptions=False)
    for _ in range(3):
        client.get("/ok")
    client.get("/boom")
    s = httplog.summary()
    assert s["requests"] == 4
    assert s["by_class"] == {"2xx": 3, "5xx": 1}
    assert s["routes"]["GET /ok"]["n"] == 3
    assert s["routes"]["GET /ok"]["p95_ms"] >= 0


def test_latency_history_is_bounded():
    httplog.latencies.clear()
    for i in range(1500):
        httplog._record("GET /x", 200, i)
    assert len(httplog.latencies["GET /x"]) == 1000
    assert httplog.latencies["GET /x"][-1] == 1499
