import json
import re
from dataclasses import dataclass, field

from . import facts, llm
from .search import Hit, semantic

DEMOTE = 0.05
POOL = 6
CONTEXT_TOKENS = 3500

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
class Answer:
    route: str
    text: str
    hits: list[Hit] = field(default_factory=list)
    used: list[Hit] = field(default_factory=list)
    quote: str | None = None
    grounded: bool | None = None
    fact: facts.Fact | None = None


def _context(hits: list[Hit]) -> tuple[str, list[Hit]]:
    blocks, kept, budget = [], [], CONTEXT_TOKENS
    for i, h in enumerate(hits, 1):
        cost = len(h.body) // 4 + 20
        if blocks and cost > budget:
            break
        budget -= cost
        kept.append(h)
        blocks.append(f"[{i}] {h.cite}\n{h.body}")
    return "\n\n".join(blocks), kept


def _parse(raw: str) -> dict | None:
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def ask(question: str) -> Answer:
    if facts.is_fact_question(question):
        number = facts.referenced(question)
        fact = facts.lookup(number)
        if fact:
            return Answer("facts", fact.headline, fact=fact)
        return Answer("facts", f"RFC {number} is not in this corpus.")

    hits = semantic(question, POOL, demote=DEMOTE)
    if not hits:
        return Answer("refusal", "Nothing in the corpus matches that question.")

    sections, kept = _context(hits)
    raw = llm.complete(PROMPT.format(question=question, sections=sections), max_tokens=900)

    if "NOT_FOUND" in raw and not _parse(raw):
        return Answer("refusal",
                      "These RFCs do not answer that. They specify the DNS protocol, "
                      "not particular software or deployments.", hits=kept)

    parsed = _parse(raw)
    if not parsed or not parsed.get("answer"):
        return Answer("refusal", "Could not produce a grounded answer.", hits=kept)

    used = [kept[i - 1] for i in parsed.get("used", []) if 1 <= i <= len(kept)]
    quote = (parsed.get("quote") or "").strip()
    grounded = bool(quote) and any(_normalise(quote) in _normalise(h.body) for h in (used or kept))

    return Answer("synthesis", parsed["answer"].strip(), hits=kept,
                  used=used or kept[:1], quote=quote or None, grounded=grounded)


def _normalise(text: str) -> str:
    collapsed = re.sub(r"\s+", " ", text).strip().lower()
    return re.sub(r"^[^\w]+|[^\w]+$", "", collapsed)
