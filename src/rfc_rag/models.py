import time
from dataclasses import dataclass, field

RFC_URL = "https://www.rfc-editor.org/rfc/rfc{number}"


@dataclass
class Rfc:
    """One row of the published RFC index."""

    number: int
    title: str
    year: int | None
    status: str | None
    stream: str | None
    pages: int | None
    errata_url: str | None
    keywords: list[str] = field(default_factory=list)
    abstract: str = ""
    wg: str | None = None
    obsoletes: list[int] = field(default_factory=list)
    updates: list[int] = field(default_factory=list)


@dataclass
class Section:
    """A parsed section of an RFC, before it reaches the database."""

    anchor: str
    number: str | None
    title: str
    body: str
    has_pre: bool

    @property
    def tokens(self) -> int:
        return max(1, len(self.body) // 4)


@dataclass
class Hit:
    """A section returned by retrieval, with its score."""

    section_id: int
    rfc: int
    anchor: str
    number: str | None
    title: str
    body: str
    score: float
    obsolete: bool = False

    @property
    def cite(self) -> str:
        where = f"§{self.number}" if self.number else ""
        return f"RFC {self.rfc} {where} {self.title}".strip()

    @property
    def url(self) -> str:
        anchor = self.anchor.split(".p")[0]
        return f"{RFC_URL.format(number=self.rfc)}#{anchor}"


@dataclass
class Fact:
    """What the supersession graph knows about one RFC."""

    rfc: int
    title: str
    year: int | None
    status: str
    obsolete: bool
    obsoleted_by: list[int]
    updated_by: list[int]
    current: list[tuple[int, str]]

    @property
    def url(self) -> str:
        return RFC_URL.format(number=self.rfc)

    @property
    def headline(self) -> str:
        if not self.obsolete and not self.updated_by:
            return f"RFC {self.rfc} is current and has never been updated."
        if not self.obsolete:
            n = len(self.updated_by)
            return f"RFC {self.rfc} is current, but {n} later RFC{'s' if n != 1 else ''} updated it."
        live = ", ".join(f"RFC {n}" for n, _ in self.current)
        return f"RFC {self.rfc} is obsolete. Read {live} instead."


@dataclass
class Change:
    """One edge of the supersession graph, with both documents named."""

    kind: str
    src: int
    src_title: str
    year: int | None
    dst: int
    dst_title: str

    @property
    def sentence(self) -> str:
        verb = "replaced" if self.kind == "obsoletes" else "updated"
        return f"RFC {self.src} ({self.year}) {verb} RFC {self.dst}"


@dataclass
class Analysis:
    """What `analyse` extracted from the question."""

    question: str
    rfc_refs: list[int]
    section_ref: str | None
    intent: str | None


@dataclass
class Trace:
    """Per-question observability, threaded through every stage."""

    question: str
    route: str | None = None
    rfc_refs: list[int] = field(default_factory=list)
    topic_rfc: int | None = None
    retrieved: list[str] = field(default_factory=list)
    context_tokens: int = 0
    llm_calls: int = 0
    models: list[str] = field(default_factory=list)
    escalated: bool = False
    timings: dict[str, float] = field(default_factory=dict)

    def step(self, name: str, started: float) -> None:
        self.timings[name] = round(time.time() - started, 3)

    @property
    def total(self) -> float:
        return round(sum(self.timings.values()), 3)


@dataclass
class Answer:
    """What the pipeline returns, and what the interfaces render."""

    route: str
    text: str
    trace: Trace = field(default_factory=lambda: Trace(""))
    hits: list[Hit] = field(default_factory=list)
    used: list[Hit] = field(default_factory=list)
    quote: str | None = None
    grounded: bool | None = None
    fact: Fact | None = None
    status: list[Fact] = field(default_factory=list)
    changes: list[Change] = field(default_factory=list)
    newest: list[Fact] = field(default_factory=list)
    # A part of the question retrieval could not act on, such as a date or a
    # superlative. Set so the answer can say the constraint was not applied.
    ignored_constraint: str | None = None
    # True when no RFC was named and the subject was inferred from the
    # question. The facts are still SQL, but the choice of document is a guess.
    inferred_subject: bool = False


@dataclass
class RetrievalScore:
    """One row of the retrieval comparison table."""

    name: str
    n: int
    doc1: float
    doc5: float
    doc10: float
    mrr: float

    def __str__(self) -> str:
        return (f"{self.name:<22} n={self.n:<4} doc@1 {self.doc1:.2f}  doc@5 {self.doc5:.2f}  "
                f"doc@10 {self.doc10:.2f}  MRR {self.mrr:.3f}")
