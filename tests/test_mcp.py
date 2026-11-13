"""The MCP tools, and the limits that keep a connected agent from draining the quota."""

import pytest

from rfc_rag.interfaces import guards, mcp_server


class Ctx:
    """Stands in for the injected MCP Context."""

    def __init__(self, ip="1.2.3.4"):
        self.headers = {"x-forwarded-for": ip}


@pytest.fixture(autouse=True)
def clear_windows():
    guards._mcp_minute.clear()
    guards._global_minute.clear()
    yield
    guards._mcp_minute.clear()


def test_status_returns_the_supersession_chain():
    out = mcp_server.rfc_status(2065, ctx=Ctx())
    assert out["obsolete"] is True
    assert out["read_instead"] == [4033, 4034, 4035]
    assert "obsolete" in out["summary"].lower()


def test_status_of_an_unknown_rfc_is_an_error_not_an_exception():
    assert "error" in mcp_server.rfc_status(999999, ctx=Ctx())


def test_search_returns_citable_sections():
    out = mcp_server.rfc_search("how are negative answers cached", k=3, ctx=Ctx())
    assert 1 <= len(out["sections"]) <= 3
    for s in out["sections"]:
        assert {"rfc", "section", "url", "text", "obsolete_document"} <= set(s)


def test_search_k_is_clamped():
    assert len(mcp_server.rfc_search("dns", k=500, ctx=Ctx())["sections"]) <= mcp_server.MAX_K
    assert len(mcp_server.rfc_search("dns", k=0, ctx=Ctx())["sections"]) >= 1


def test_search_can_exclude_replaced_documents():
    out = mcp_server.rfc_search("DNSSEC key records", k=8, current_only=True, ctx=Ctx())
    assert all(not s["obsolete_document"] for s in out["sections"])


def test_section_is_exact_or_an_error():
    good = mcp_server.rfc_section(1035, "2.3.4", ctx=Ctx())
    assert good["sections"][0]["section"] == "2.3.4"
    assert "63 octets" in good["sections"][0]["text"]

    missing = mcp_server.rfc_section(1035, "99.99", ctx=Ctx())
    assert "error" in missing and "99.99" in missing["error"]


def test_every_tool_is_rate_limited(monkeypatch):
    monkeypatch.setattr(guards, "MCP_PER_MINUTE", 3)
    for _ in range(3):
        mcp_server.rfc_status(1035, ctx=Ctx("9.9.9.9"))
    with pytest.raises(guards.Rejected) as exc:
        mcp_server.rfc_status(1035, ctx=Ctx("9.9.9.9"))
    assert exc.value.status == 429


def test_limits_are_per_caller(monkeypatch):
    monkeypatch.setattr(guards, "MCP_PER_MINUTE", 2)
    mcp_server.rfc_status(1035, ctx=Ctx("a"))
    mcp_server.rfc_status(1035, ctx=Ctx("a"))
    mcp_server.rfc_status(1035, ctx=Ctx("b"))      # a different agent is unaffected


def test_tools_without_a_context_still_work():
    """stdio and direct calls have no HTTP headers."""
    assert mcp_server.rfc_status(1035, ctx=None)["rfc"] == 1035


def test_model_calling_tools_would_share_the_provider_budget(monkeypatch):
    """No MCP tool calls the model today; the path exists for when one does."""
    monkeypatch.setattr(guards, "GLOBAL_PER_MINUTE", 1)
    monkeypatch.setattr(guards, "provider_calls_last_minute", lambda: 0)
    guards.check_mcp("x", calls_model=True)
    with pytest.raises(guards.Rejected):
        guards.check_mcp("x", calls_model=True)


def test_provider_budget_is_shared_across_workers(monkeypatch):
    """The in-process window only sees one worker; this one reads the log."""
    monkeypatch.setattr(guards, "GLOBAL_PER_MINUTE", 5)
    monkeypatch.setattr(guards, "provider_calls_last_minute", lambda: 5)
    with pytest.raises(guards.Rejected) as exc:
        guards.check_provider_budget()
    assert exc.value.status == 503


def test_tool_descriptions_say_when_to_use_them():
    """The description is the only basis a model has for choosing the tool."""
    import asyncio

    tools = asyncio.run(mcp_server.mcp.list_tools())
    assert {t.name for t in tools} == {"rfc_status", "rfc_search", "rfc_section"}
    for t in tools:
        assert len(t.description) > 150, f"{t.name} description is too thin"
        assert "ctx" not in t.input_schema.get("properties", {})
