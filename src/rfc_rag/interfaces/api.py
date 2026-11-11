"""HTTP interface.

Every answer names the RFCs it researched, with their supersession status, so
a caller can tell a current specification from a replaced one without a second
request.
"""

import logging
import os
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from .. import corpus, observability
from ..clients.base import LLMError
from ..db import connect
from ..models import Answer
from ..services import chat as chat_service
from ..services import supersession
from ..services.answering import ask
from . import guards, httplog

app = FastAPI(
    title="rfc-rag",
    description="Answers about DNS RFCs, with verified quotes and supersession status.",
    version="0.1.0",
)
log = logging.getLogger(__name__)
STARTED = time.time()
UI = Path(__file__).parent / "static" / "index.html"

httplog.setup(os.getenv("LOG_LEVEL", "INFO"))
app.add_middleware(httplog.RequestLog)
METRICS_TOKEN = os.getenv("METRICS_TOKEN", "")


class Question(BaseModel):
    question: str = Field(..., examples=["What is the maximum length of a DNS label?"])


class NewChat(BaseModel):
    token_budget: int | None = Field(None, ge=1000, le=200_000)


def _client(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    return (forwarded.split(",")[0].strip() if forwarded
            else (request.client.host if request.client else "unknown"))


def _sources(answer: Answer) -> list[dict]:
    """The RFCs researched, in the order retrieval ranked them."""
    by_rfc: dict[int, dict] = {}
    for hit in answer.hits:
        entry = by_rfc.setdefault(hit.rfc, {
            "rfc": hit.rfc, "url": f"https://www.rfc-editor.org/rfc/rfc{hit.rfc}",
            "sections": [], "used_in_answer": False, "obsolete": hit.obsolete,
        })
        entry["sections"].append({
            "section": hit.number, "title": hit.title, "anchor": hit.anchor,
            "score": round(hit.score, 4), "url": hit.url,
            "quoted": any(u.section_id == hit.section_id for u in answer.used),
        })
        if any(u.rfc == hit.rfc for u in answer.used):
            entry["used_in_answer"] = True

    for fact in answer.status:
        if fact.rfc in by_rfc:
            by_rfc[fact.rfc]["status"] = {
                "obsolete": fact.obsolete,
                "replaced_by": fact.obsoleted_by or None,
                "read_instead": [n for n, _ in fact.current] if fact.obsolete else None,
                "updated_by_count": len(fact.updated_by),
                "updated_by": fact.updated_by or None,
                "warning": fact.headline,
            }
    return list(by_rfc.values())


def _payload(answer: Answer) -> dict:
    return {
        "route": answer.route,
        "answer": answer.text,
        "quote": answer.quote,
        "verified": answer.grounded,
        "sources": _sources(answer),
        "fact": ({"rfc": answer.fact.rfc, "status": answer.fact.status,
                  "obsolete": answer.fact.obsolete,
                  "replaced_by": answer.fact.obsoleted_by or None,
                  "read_instead": [n for n, _ in answer.fact.current],
                  "updated_by": answer.fact.updated_by or None}
                 if answer.fact else None),
        "meta": {
            "models": answer.trace.models,
            "escalated": answer.trace.escalated,
            "llm_calls": answer.trace.llm_calls,
            "took_ms": int(answer.trace.total * 1000),
            "cached": False,
        },
    }


@app.exception_handler(LLMError)
async def _upstream(request: Request, exc: LLMError):
    """Never leak the provider URL, key or stack trace to a caller."""
    throttled = "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc)
    log.warning("upstream failure: %s", exc)
    if throttled:
        return JSONResponse(
            {"error": "The model provider is rate limiting this demo. Try again shortly."},
            status_code=503, headers={"Retry-After": "60"})
    return JSONResponse({"error": "The model backend is unavailable."}, status_code=502)


@app.exception_handler(corpus.EmbeddingMismatch)
async def _mismatch(request: Request, exc: corpus.EmbeddingMismatch):
    log.error("corpus mismatch: %s", exc)
    return JSONResponse({"error": "Search index is being rebuilt."}, status_code=503,
                        headers={"Retry-After": "300"})


@app.exception_handler(guards.Rejected)
async def _rejected(request: Request, exc: guards.Rejected):
    headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
    return JSONResponse({"error": exc.detail}, status_code=exc.status, headers=headers)


@app.exception_handler(RequestValidationError)
async def _invalid(request: Request, exc: RequestValidationError):
    return JSONResponse({"error": "Malformed request body."}, status_code=422)


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(UI, media_type="text/html")


@app.post("/ask")
def ask_endpoint(body: Question, request: Request):
    question = guards.clean_question(body.question)
    client = _client(request)

    hit = guards.cached(question)
    if hit:
        hit["meta"] = {**hit.get("meta", {}), "cached": True}
        return hit

    guards.check_rate(client)
    answer = ask(question)
    payload = _payload(answer)
    if answer.route != "error":
        guards.store(question, payload)
    _tag(client, answer)
    return payload


@app.get("/rfc/{number}")
def rfc_endpoint(number: int):
    """Supersession facts only. SQL, no model, no rate limit."""
    fact = supersession.lookup(number)
    if not fact:
        return JSONResponse({"error": f"RFC {number} is not in this corpus."}, 404)
    return {
        "rfc": fact.rfc, "title": fact.title, "year": fact.year, "status": fact.status,
        "obsolete": fact.obsolete, "replaced_by": fact.obsoleted_by or None,
        "read_instead": [{"rfc": n, "title": t} for n, t in fact.current],
        "updated_by": fact.updated_by or None,
        "summary": fact.headline,
        "url": fact.url,
    }


@app.exception_handler(chat_service.ChatClosed)
async def _closed(request: Request, exc: chat_service.ChatClosed):
    return JSONResponse({"error": str(exc), "state": "readonly"}, status_code=409)


@app.exception_handler(chat_service.ChatMissing)
async def _missing(request: Request, exc: chat_service.ChatMissing):
    return JSONResponse({"error": str(exc)}, status_code=404)


def _chat_json(c: chat_service.Chat) -> dict:
    return {"id": str(c.id), "title": c.title, "state": c.state,
            "readonly": c.readonly, "tokens_used": c.tokens_used,
            "token_budget": c.token_budget, "tokens_left": c.tokens_left,
            "message_count": c.message_count, "max_messages": c.max_messages,
            "turns_left": c.turns_left}


@app.post("/chats", status_code=201)
def create_chat(body: NewChat | None = None, request: Request = None):
    budget = (body.token_budget if body and body.token_budget
              else chat_service.DEFAULT_BUDGET)
    return _chat_json(chat_service.create(_client(request), budget))


@app.get("/chats")
def list_chats(request: Request):
    return {"chats": chat_service.listing(_client(request))}


@app.get("/chats/{chat_id}")
def get_chat(chat_id: str):
    c = chat_service.get(chat_id)
    return {**_chat_json(c), "messages": chat_service.messages(chat_id)}


@app.post("/chats/{chat_id}/messages")
def send_message(chat_id: str, body: Question, request: Request):
    question = guards.clean_question(body.question)
    client = _client(request)
    guards.check_rate(client)

    turn = chat_service.send(chat_id, question, _sources)
    payload = _payload(turn.answer)
    _tag(client, turn.answer)
    return {**payload, "chat": _chat_json(turn.chat),
            "resolved_question": turn.resolved_question
                                 if turn.resolved_question != question else None}


@app.get("/healthz")
def healthz():
    checks = {}
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute("select count(*) from section where embedding is not null")
            embedded = cur.fetchone()[0]
            cur.execute("select count(*) from section")
            total = cur.fetchone()[0]
        checks["database"] = "ok"
        checks["embedded"] = f"{embedded}/{total}"
        checks["corpus_ready"] = embedded == total and total > 0
    except Exception as exc:
        checks["database"] = f"error: {type(exc).__name__}"
        checks["corpus_ready"] = False
    try:
        corpus.check()
        stamp = corpus.recorded()
        checks["embedding_model"] = f"{stamp[0]} ({stamp[1]}d)" if stamp else "not stamped"
        if not stamp:
            checks["corpus_ready"] = False
    except Exception as exc:
        checks["embedding_model"] = str(exc)[:140]
        checks["corpus_ready"] = False

    ok = checks.get("corpus_ready", False)
    return JSONResponse({"status": "ok" if ok else "degraded",
                         "uptime_s": int(time.time() - STARTED), **checks},
                        status_code=200 if ok else 503)


@app.get("/metrics")
def metrics(request: Request):
    if METRICS_TOKEN and request.headers.get("authorization") != f"Bearer {METRICS_TOKEN}":
        return JSONResponse({"error": "unauthorized"}, 401)
    report = observability.report()
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select count(*), coalesce(sum(hits), 0) from answer_cache")
        entries, hits = cur.fetchone()
        cur.execute("""select count(*) from query_log
                        where at > now() - interval '1 day' and not cached""")
        today = cur.fetchone()[0]
    return {
        "http": httplog.summary(),
        "quota": {"used_today": today, "global_daily_limit": guards.GLOBAL_PER_DAY},
        "cache": {"entries": entries, "hits": hits},
        "answers": report,
    }


def _tag(client: str, answer: Answer) -> None:
    """Attach the caller to the row ask() just wrote."""
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute("""update query_log set client = %s
                            where id = (select max(id) from query_log)""", (client,))
            conn.commit()
    except Exception:
        pass
