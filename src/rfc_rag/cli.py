import argparse
import dataclasses
import json
import sys

from .answer import Answer, ask
from .facts import Fact

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

    lines.append("")
    lines.append(_c(DIM, f"route: {answer.route}"))
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(prog="rfc", description="Ask about DNS RFCs.")
    parser.add_argument("question", nargs="+")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    answer = ask(" ".join(args.question))

    if args.json:
        payload = dataclasses.asdict(answer)
        payload["hits"] = [{"rfc": h.rfc, "anchor": h.anchor, "score": h.score,
                            "cite": h.cite, "url": h.url, "obsolete": h.obsolete}
                           for h in answer.hits]
        payload["used"] = [{"rfc": h.rfc, "anchor": h.anchor, "cite": h.cite, "url": h.url}
                           for h in answer.used]
        print(json.dumps(payload, indent=2, default=str))
    else:
        print(render(answer), end="")

    return 0 if answer.route != "refusal" else 1


if __name__ == "__main__":
    raise SystemExit(main())
