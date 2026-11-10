"""One structured JSON line per request, success or failure.

This is service-level observability: method, path, status, duration, client.
It goes to stdout so the platform collects it, and deliberately knows nothing
about routes, grounding or retrieval — those are answer-quality signals and
live in query_log.

Errors travel the same path as successes. A 500 is a line with status 500 and
an error type, not a stack trace in a different format somewhere else.
"""

import json
import logging
import sys
import time
import uuid
from collections import Counter

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

SLOW_MS = 3000

counters: Counter = Counter()
latencies: dict[str, list[int]] = {}

log = logging.getLogger("rfc_rag.http")


def setup(level: str = "INFO") -> None:
    """Plain lines to stdout; the surrounding platform does the collecting."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger("rfc_rag")
    root.handlers = [handler]
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.propagate = False


def _emit(payload: dict) -> None:
    log.info(json.dumps(payload, separators=(",", ":")))


def _record(route: str, status: int, ms: int) -> None:
    counters[f"status_{status // 100}xx"] += 1
    counters[f"status_{status}"] += 1
    counters["requests"] += 1
    latencies.setdefault(route, []).append(ms)
    if len(latencies[route]) > 1000:
        del latencies[route][:-1000]


class RequestLog(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request_id = uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        started = time.perf_counter()
        route = f"{request.method} {request.url.path}"
        error = None

        try:
            response = await call_next(request)
            status = response.status_code
        except Exception as exc:
            status, error = 500, type(exc).__name__
            log.exception("unhandled error on %s", route)
            response = JSONResponse({"error": "Internal error.",
                                     "request_id": request_id}, status_code=500)

        ms = int((time.perf_counter() - started) * 1000)
        _record(route, status, ms)
        response.headers["x-request-id"] = request_id

        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status": status,
            "ms": ms,
            "client": request.headers.get("x-forwarded-for", "").split(",")[0].strip()
                      or (request.client.host if request.client else None),
        }
        if error:
            entry["error"] = error
        if status >= 500 or ms > SLOW_MS:
            entry["level"] = "warn"
        _emit(entry)
        return response


def summary() -> dict:
    out = {"requests": counters["requests"],
           "by_status": {k.removeprefix("status_"): v for k, v in sorted(counters.items())
                         if k.startswith("status_") and k.count("x") == 0},
           "by_class": {k.removeprefix("status_"): v for k, v in sorted(counters.items())
                        if k.endswith("xx")},
           "routes": {}}
    for route, values in latencies.items():
        ordered = sorted(values)
        pick = lambda q: ordered[min(int(len(ordered) * q), len(ordered) - 1)]
        out["routes"][route] = {"n": len(ordered), "p50_ms": pick(0.5),
                                "p95_ms": pick(0.95), "max_ms": ordered[-1]}
    return out
