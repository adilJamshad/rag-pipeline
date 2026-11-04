import time
from pathlib import Path

import httpx

BASE = "https://www.rfc-editor.org/rfc"
CACHE = Path("data/html")
DELAY = 0.5


def html(number: int, client: httpx.Client | None = None) -> str:
    path = CACHE / f"rfc{number}.html"
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace")

    path.parent.mkdir(parents=True, exist_ok=True)
    owned = client is None
    client = client or httpx.Client(timeout=60, follow_redirects=True)
    try:
        r = client.get(f"{BASE}/rfc{number}.html")
        r.raise_for_status()
        text = r.text
    finally:
        if owned:
            client.close()

    path.write_text(text, encoding="utf-8")
    time.sleep(DELAY)
    return text


def many(numbers: list[int]) -> dict[int, str]:
    out = {}
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        for n in numbers:
            out[n] = html(n, client)
    return out
