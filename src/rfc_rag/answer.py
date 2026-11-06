import time

from . import facts, llm, pipeline
from .pipeline import Analysis, Answer, Trace


def _facts_answer(number: int, trace: Trace) -> Answer:
    fact = facts.lookup(number)
    if not fact:
        return Answer("facts", f"RFC {number} is not in this corpus.", trace)
    return Answer("facts", fact.headline, trace, fact=fact)


def ask(question: str) -> Answer:
    trace = Trace(question)

    started = time.time()
    analysis: Analysis = pipeline.analyse(question)
    route = pipeline.plan(analysis)
    trace.rfc_refs = analysis.rfc_refs
    trace.step("analyse", started)

    if route == "facts":
        trace.route = "facts"
        return _facts_answer(analysis.rfc_refs[0], trace)

    if route == "topic_facts":
        started = time.time()
        number = pipeline.resolve_topic(question)
        trace.topic_rfc = number
        trace.step("resolve_topic", started)
        if number:
            trace.route = "facts"
            return _facts_answer(number, trace)
        route = "synthesis"

    hits = pipeline.gather(analysis, route, trace)
    if not hits:
        trace.route = "refusal"
        return Answer("refusal", "Nothing in the corpus matches that question.", trace)

    if route == "passage" and not analysis.intent:
        trace.route = "passage"
        top = hits[0]
        return Answer("passage", top.body, trace, hits=hits, used=[top],
                      quote=top.body, grounded=True,
                      status=pipeline.statuses([top]))

    sections, kept = pipeline.compose(hits, trace)

    started = time.time()
    raw = llm.complete(pipeline.PROMPT.format(question=question, sections=sections),
                       max_tokens=900)
    trace.llm_calls += 1
    trace.step("generate", started)

    parsed = pipeline._parse(raw)
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
    grounded = pipeline.verify(quote, used or kept)
    status = pipeline.statuses(used)
    trace.step("verify", started)

    trace.route = "synthesis"
    return Answer("synthesis", parsed["answer"].strip(), trace, hits=kept, used=used,
                  quote=quote or None, grounded=grounded, status=status)
