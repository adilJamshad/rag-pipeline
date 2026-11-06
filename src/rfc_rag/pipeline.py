import json
import math
import re
import time
from dataclasses import dataclass, field

from . import facts, llm
from .db import connect
from .search import Hit, semantic

DEMOTE = 0.05
POOL = 6
CONTEXT_TOKENS = 3500
FOUNDATIONAL_WEIGHT = 0.015
TOPIC_POOL = 25

SECTION_REF = re.compile(r"(?:\bsection\s*|§\s*)(\d+(?:\.\d+)*)", re.I)

PROMPT = """You answer questions about DNS specifications using only the numbered \
sections below. You may not use any other knowledge.

Rules:
- If the sections do not answer the question, reply exactly: NOT_FOUND
- Otherwise reply with JSON only: {{"answer": "...", "used": [1,2], "quote": "..."}}
- "answer" is one or two plain sentences.
- "quote" must be copied character for character from one of the sections.
- "used" lists the section numbers you relied on.

Question: {question}

{sections}"""


@dataclass
class Trace:
    question: str
    route: str | None = None
    rfc_refs: list[int] = field(default_factory=list)
    topic_rfc: int | None = None
    retrieved: list[str] = field(default_factory=list)
    context_tokens: int = 0
    llm_calls: int = 0
    timings: dict[str, float] = field(default_factory=dict)

    def step(self, name: str, started: float) -> None:
        self.timings[name] = round(time.time() - started, 3)

    @property
    def total(self) -> float:
        return round(sum(self.timings.values()), 3)


@dataclass
class Analysis:
    question: str
    rfc_refs: list[int]
    section_ref: str | None
    intent: str | None


@dataclass
class Answer:
    route: str
    text: str
    trace: Trace = field(default_factory=lambda: Trace(""))
    hits: list[Hit] = field(default_factory=list)
    used: list[Hit] = field(default_factory=list)
    quote: str | None = None
    grounded: bool | None = None
    fact: facts.Fact | None = None
    status: list[facts.Fact] = field(default_factory=list)


def analyse(question: str) -> Analysis:
    refs = [int(n) for n in facts.RFC_REF.findall(question)]
    m = SECTION_REF.search(question)
    return Analysis(question, refs, m.group(1) if m else None, facts.intent(question))


def resolve_topic(question: str) -> int | None:
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
    best = max(rows, key=lambda r: r[2] + FOUNDATIONAL_WEIGHT * math.log1p(r[1]))
    return best[0]


def plan(analysis: Analysis) -> str:
    if analysis.rfc_refs and analysis.intent:
        return "facts"
    if analysis.intent and not analysis.rfc_refs:
        return "topic_facts"
    if analysis.rfc_refs:
        return "passage"
    return "synthesis"


def gather(analysis: Analysis, route: str, trace: Trace) -> list[Hit]:
    started = time.time()
    restrict = analysis.rfc_refs[0] if route == "passage" else None
    hits = semantic(analysis.question, POOL, demote=DEMOTE, only_rfc=restrict)
    trace.retrieved = [f"{h.rfc}/{h.anchor}" for h in hits]
    trace.step("gather", started)
    return hits


def compose(hits: list[Hit], trace: Trace) -> tuple[str, list[Hit]]:
    blocks, kept, budget = [], [], CONTEXT_TOKENS
    for i, h in enumerate(hits, 1):
        cost = len(h.body) // 4 + 20
        if blocks and cost > budget:
            break
        budget -= cost
        kept.append(h)
        blocks.append(f"[{i}] {h.cite}\n{h.body}")
    trace.context_tokens = CONTEXT_TOKENS - budget
    return "\n\n".join(blocks), kept


def _parse(raw: str) -> dict | None:
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def normalise(text: str) -> str:
    collapsed = re.sub(r"\s+", " ", text).strip().lower()
    return re.sub(r"^[^\w]+|[^\w]+$", "", collapsed)


def verify(quote: str, candidates: list[Hit]) -> bool:
    if not quote:
        return False
    needle = normalise(quote)
    return any(needle in normalise(h.body) for h in candidates)


def statuses(hits: list[Hit]) -> list[facts.Fact]:
    out = []
    for number in dict.fromkeys(h.rfc for h in hits):
        fact = facts.lookup(number)
        if fact and (fact.obsolete or fact.updated_by):
            out.append(fact)
    return out
