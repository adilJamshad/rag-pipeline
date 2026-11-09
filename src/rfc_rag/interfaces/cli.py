import argparse
import dataclasses
import json
import sys

from .. import observability
from ..models import Answer, Fact
from ..services.answering import ask

DIM, BOLD, RED, YELLOW, GREEN, OFF = "\033[2m", "\033[1m", "\033[31m", "\033[33m", "\033[32m", "\033[0m"


def _plain() -> bool:
    return not sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return text if _plain() else f"{code}{text}{OFF}"


def _fact_block(fact: Fact) -> list[str]:
    out = [f"  {_c(DIM, 'status')}  {fact.status}, {fact.year}"]
    if fact.obsoleted_by:
        direct = ", ".join(f"RFC {n}" for n in fact.obsoleted_by)
        live = ", ".join(f"RFC {n}" for n, _ in fact.current)
        chain = f"{direct} -> {live}" if live and live != direct else direct
        out.append(f"  {_c(DIM, 'dead')}    replaced by {chain}")
    if fact.updated_by:
        shown = ", ".join(f"RFC {n}" for n in fact.updated_by[:6])
        more = f" (+{len(fact.updated_by) - 6} more)" if len(fact.updated_by) > 6 else ""
        out.append(f"  {_c(DIM, 'updated')} {len(fact.updated_by)} RFCs: {shown}{more}")
    out.append(f"  {_c(DIM, 'link')}    https://www.rfc-editor.org/rfc/rfc{fact.rfc}")
    return out


def render(answer: Answer) -> str:
    lines = [""]

    if answer.route == "passage":
        source = answer.used[0]
        flag = _c(RED, " [OBSOLETE]") if source.obsolete else ""
        lines.append(_c(BOLD, source.cite) + flag)
        lines.append("")
        for line in answer.text.splitlines():
            lines.append(f"  {line}")
        lines.append("")
        lines.append(_c(DIM, f"  {source.url}"))
        if answer.status:
            lines.append("")
            lines.append(_c(YELLOW, "Check before relying on this:"))
            for fact in answer.status:
                if fact.obsolete:
                    live = ", ".join(f"RFC {n}" for n, _ in fact.current)
                    lines.append(f"  RFC {fact.rfc} is OBSOLETE - read {live}")
                else:
                    lines.append(f"  RFC {fact.rfc} is current but "
                                 f"{len(fact.updated_by)} later RFCs updated it")
        lines.append("")
        lines.append(_c(DIM, f"route: passage  {answer.trace.total}s  llm calls: 0"))
        return "\n".join(lines) + "\n"

    if answer.route == "refusal":
        lines.append(_c(YELLOW, "No answer found."))
        lines.append(answer.text)
        if answer.hits:
            lines.append("")
            lines.append(_c(DIM, "Closest sections:"))
            for h in answer.hits[:3]:
                lines.append(f"  {h.score:.3f}  {h.cite}")
        return "\n".join(lines) + "\n"

    lines.append(_c(BOLD, answer.text))

    if answer.quote:
        mark = _c(GREEN, "verified") if answer.grounded else _c(RED, "UNVERIFIED")
        lines.append("")
        for line in answer.quote.splitlines():
            lines.append(_c(DIM, f"  > {line}"))
        source = answer.used[0] if answer.used else None
        if source:
            flag = _c(RED, " [OBSOLETE]") if source.obsolete else ""
            lines.append(f"  {_c(DIM, source.cite)}{flag}  {mark}")
            lines.append(f"  {_c(DIM, source.url)}")

    if answer.fact:
        lines.append("")
        lines.extend(_fact_block(answer.fact))

    if answer.route == "synthesis" and len(answer.used) > 1:
        lines.append("")
        lines.append(_c(DIM, "Also used:"))
        for h in answer.used[1:4]:
            flag = _c(RED, " [OBSOLETE]") if h.obsolete else ""
            lines.append(f"  {_c(DIM, h.cite)}{flag}")

    if answer.status:
        lines.append("")
        lines.append(_c(YELLOW, "Check before relying on this:"))
        for fact in answer.status:
            if fact.obsolete:
                live = ", ".join(f"RFC {n}" for n, _ in fact.current)
                lines.append(f"  RFC {fact.rfc} is OBSOLETE - read {live}")
            else:
                lines.append(f"  RFC {fact.rfc} is current but {len(fact.updated_by)} "
                             f"later RFCs updated it")

    t = answer.trace
    meta = f"route: {answer.route}  {t.total}s  llm calls: {t.llm_calls}"
    if t.context_tokens:
        meta += f"  context: ~{t.context_tokens} tok"
    lines.append("")
    lines.append(_c(DIM, meta))
    return "\n".join(lines) + "\n"


def _stats(r: dict) -> str:
    lines = ["", _c(BOLD, f"{r['total']} questions in the last 30 days"), ""]
    if not r["total"]:
        return "\n".join(lines) + "  nothing recorded yet\n"
    pct = lambda n: f"{n / r['total'] * 100:.0f}%"
    lines += [
        f"  answered        {r['answered']:>5}  ({pct(r['answered'])})",
        f"  refused         {r['refused']:>5}  ({pct(r['refused'])})",
        f"  ungrounded      {r['ungrounded']:>5}",
        f"  model calls     {r['llm_calls']:>5}  ({pct(r['llm_calls'])} of questions)",
        f"  tokens in/out   {r['prompt_tokens']:>5} / {r['completion_tokens']}",
        "",
        _c(DIM, "  route         n     p50      p95   model calls"),
    ]
    for row in r["routes"]:
        lines.append(f"  {row['route'] or '?':<12} {row['n']:>3}  {row['p50_ms'] or 0:>6}ms "
                     f"{row['p95_ms'] or 0:>7}ms   {row['llm_calls']}")
    if r["attention"]:
        lines += ["", _c(YELLOW, "Needs attention:")]
        for a in r["attention"]:
            why = "ungrounded" if a["grounded"] is False else a["route"]
            lines.append(f"  {why:<12} {a['question'][:54]}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(prog="rfc", description="Ask about DNS RFCs.")
    parser.add_argument("question", nargs="*")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--stats", action="store_true", help="show usage over the last 30 days")
    args = parser.parse_args()
    observability.setup_logging()

    if args.stats:
        print(_stats(observability.report()), end="")
        return 0

    answer = ask(" ".join(args.question))

    if args.json:
        payload = dataclasses.asdict(answer)
        payload["hits"] = [{"rfc": h.rfc, "anchor": h.anchor, "score": h.score,
                            "cite": h.cite, "url": h.url, "obsolete": h.obsolete}
                           for h in answer.hits]
        payload["used"] = [{"rfc": h.rfc, "anchor": h.anchor, "cite": h.cite, "url": h.url}
                           for h in answer.used]
        payload["status"] = [{"rfc": f.rfc, "obsolete": f.obsolete,
                              "updated_by": f.updated_by,
                              "current": [n for n, _ in f.current]} for f in answer.status]
        print(json.dumps(payload, indent=2, default=str))
    else:
        print(render(answer), end="")

    return 0 if answer.route != "refusal" else 1


if __name__ == "__main__":
    raise SystemExit(main())
