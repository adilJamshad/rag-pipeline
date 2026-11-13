"""Pure pipeline stages. No database, no network, no model."""

import json
import re

from ..models import Analysis, Hit, Trace

CONTEXT_TOKENS = 3500

RFC_REF = re.compile(r"\brfc[\s-]*(\d{1,5})\b", re.I)
SECTION_REF = re.compile(r"(?:\bsection\s*|§\s*)(\d+(?:\.\d+)*)", re.I)

# "What changed recently?" is about the corpus, not about one document. Without
# its own route it matched the `updated` intent, lost its RFC number to nothing,
# and was answered with facts about whichever document a vague query happened to
# retrieve.
_WHEN = r"(last|latest|most recent|recent(ly)?|newest|new)"
_WHAT = r"(chang|updat|revis|amend|supersed|obsolet|publish)\w*"

# Recency as an event: "what changed last".
RECENT_CHANGE = re.compile(
    rf"\b{_WHEN}\b.{{0,40}}\b{_WHAT}|\b{_WHAT}.{{0,40}}\b{_WHEN}\b", re.I)

# Recency as the subject: "the last RFC on DNS". A different shape entirely,
# and the one that slipped through - "last ... say" is not "last ... change".
RECENT_DOC = re.compile(
    rf"\b{_WHEN}\b\s+(\w+\s+){{0,2}}\b(rfc|spec|specification|standard|document|draft)s?\b",
    re.I)

# Anything embeddings cannot represent. Similarity has no notion of time or
# ordering, so these words contribute noise to retrieval and the answer must
# not imply the constraint was honoured.
UNREPRESENTABLE = re.compile(
    rf"\b({_WHEN}|oldest|first|earliest|before|after|since|in \d{{4}}|"
    rf"this year|last year)\b", re.I)

INTENTS = [
    ("current", re.compile(r"\b(still (current|valid|in force)|current|valid|up to date|obsolete|dead)\b", re.I)),
    ("replaced", re.compile(r"\b(replac|supersed|obsolet|instead of|what should i read)\w*\b", re.I)),
    ("updated", re.compile(r"\b(update|updated by|amend|chang|modif)\w*\b", re.I)),
]

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


def referenced(question: str) -> int | None:
    m = RFC_REF.search(question)
    return int(m.group(1)) if m else None


def intent(question: str) -> str | None:
    for name, pattern in INTENTS:
        if pattern.search(question):
            return name
    return None


def analyse(question: str) -> Analysis:
    refs = [int(n) for n in RFC_REF.findall(question)]
    m = SECTION_REF.search(question)
    return Analysis(question, refs, m.group(1) if m else None, intent(question))


def plan(analysis: Analysis) -> str:
    if analysis.rfc_refs and analysis.intent:
        return "facts"
    if not analysis.rfc_refs and RECENT_CHANGE.search(analysis.question):
        return "recent_changes"
    if not analysis.rfc_refs and RECENT_DOC.search(analysis.question):
        return "recent_documents"
    if analysis.intent and not analysis.rfc_refs:
        return "topic_facts"
    if analysis.rfc_refs:
        return "passage"
    return "synthesis"


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


def parse_response(raw: str) -> dict | None:
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def clean_response(parsed: dict | None) -> dict | None:
    """Coerce a parsed response into the shape the pipeline assumes.

    The model is asked for {answer, used, quote} and mostly complies, but a
    string where a list belongs, or a number where a string belongs, reached
    code that indexed and called .strip() on it and raised. A malformed answer
    is a refusal, not a 500.
    """
    if not isinstance(parsed, dict):
        return None

    answer = parsed.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        return None

    used = parsed.get("used")
    if not isinstance(used, (list, tuple)):
        used = [used] if isinstance(used, (int, bool)) else []
    indexes = [i for i in used if isinstance(i, int) and not isinstance(i, bool)]

    quote = parsed.get("quote")
    quote = quote.strip() if isinstance(quote, str) else ""

    return {"answer": answer.strip(), "used": indexes, "quote": quote}


def normalise(text: str) -> str:
    collapsed = re.sub(r"\s+", " ", text).strip().lower()
    return re.sub(r"^[^\w]+|[^\w]+$", "", collapsed)


def verify(quote: str, candidates: list[Hit]) -> bool:
    if not quote:
        return False
    needle = normalise(quote)
    return any(needle in normalise(h.body) for h in candidates)


def unrepresentable_constraint(question: str) -> str | None:
    """The part of a question retrieval cannot act on, if any."""
    m = UNREPRESENTABLE.search(question)
    return m.group(0) if m else None
