"""Orchestration: runs the stages, touches the database and the model."""

import math
import time

from ..clients import llm
from ..db import connect
from ..models import Analysis, Answer, Fact, Hit, Trace
from . import stages, supersession
from .search import semantic

DEMOTE = 0.05
POOL = 6
FOUNDATIONAL_WEIGHT = 0.015
TOPIC_POOL = 25


def resolve_topic(question: str) -> int | None:
    """Pick the base specification for a topic.

    Being foundational is structural, not topical, so similarity alone is not
    enough: the base spec of an area is its most-amended document.
    """
    vector = str(llm.embed([question])[0])
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""
            select r.number,
                   (select count(*) from rfc_relation x
                     where x.dst = r.number and x.kind = 'updates') as updates,
                   1 - (r.embedding <=> %s::vector) as sim
              from rfc r
             where r.embedding is not null
               and not exists (select 1 from rfc_relation y
                                where y.dst = r.number and y.kind = 'obsoletes')
             order by r.embedding <=> %s::vector
             limit %s
        """, (vector, vector, TOPIC_POOL))
        rows = cur.fetchall()
    if not rows:
        return None
    return max(rows, key=lambda r: r[2] + FOUNDATIONAL_WEIGHT * math.log1p(r[1]))[0]


def gather(analysis: Analysis, route: str, trace: Trace) -> list[Hit]:
    started = time.time()
    restrict = analysis.rfc_refs[0] if route == "passage" else None
    hits = semantic(analysis.question, POOL, demote=DEMOTE, only_rfc=restrict)
    trace.retrieved = [f"{h.rfc}/{h.anchor}" for h in hits]
    trace.step("gather", started)
    return hits


def statuses(hits: list[Hit]) -> list[Fact]:
    out = []
    for number in dict.fromkeys(h.rfc for h in hits):
        fact = supersession.lookup(number)
        if fact and (fact.obsolete or fact.updated_by):
            out.append(fact)
    return out


def _facts_answer(number: int, trace: Trace) -> Answer:
    fact = supersession.lookup(number)
    if not fact:
        return Answer("facts", f"RFC {number} is not in this corpus.", trace)
    return Answer("facts", fact.headline, trace, fact=fact)


def ask(question: str) -> Answer:
    trace = Trace(question)

    started = time.time()
    analysis = stages.analyse(question)
    route = stages.plan(analysis)
    trace.rfc_refs = analysis.rfc_refs
    trace.step("analyse", started)

    if route == "facts":
        trace.route = "facts"
        return _facts_answer(analysis.rfc_refs[0], trace)

    if route == "topic_facts":
        started = time.time()
        number = resolve_topic(question)
        trace.topic_rfc = number
        trace.step("resolve_topic", started)
        if number:
            trace.route = "facts"
            return _facts_answer(number, trace)
        route = "synthesis"

    hits = gather(analysis, route, trace)
    if not hits:
        trace.route = "refusal"
        return Answer("refusal", "Nothing in the corpus matches that question.", trace)

    if route == "passage" and not analysis.intent:
        trace.route = "passage"
        top = hits[0]
        return Answer("passage", top.body, trace, hits=hits, used=[top],
                      quote=top.body, grounded=True, status=statuses([top]))

    sections, kept = stages.compose(hits, trace)

    started = time.time()
    raw = llm.complete(stages.PROMPT.format(question=question, sections=sections),
                       max_tokens=900)
    trace.llm_calls += 1
    trace.step("generate", started)

    parsed = stages.parse_response(raw)
    if "NOT_FOUND" in raw and not parsed:
        trace.route = "refusal"
        return Answer("refusal",
                      "These RFCs do not answer that. They specify the DNS protocol, "
                      "not particular software or deployments.", trace, hits=kept)
    if not parsed or not parsed.get("answer"):
        trace.route = "refusal"
        return Answer("refusal", "Could not produce a grounded answer.", trace, hits=kept)

    used = [kept[i - 1] for i in parsed.get("used", []) if 1 <= i <= len(kept)] or kept[:1]
    quote = (parsed.get("quote") or "").strip()

    started = time.time()
    grounded = stages.verify(quote, used or kept)
    status = statuses(used)
    trace.step("verify", started)

    trace.route = "synthesis"
    return Answer("synthesis", parsed["answer"].strip(), trace, hits=kept, used=used,
                  quote=quote or None, grounded=grounded, status=status)
