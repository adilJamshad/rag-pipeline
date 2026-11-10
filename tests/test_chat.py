import pytest

from rfc_rag.models import Answer, Hit, Trace
from rfc_rag.services import chat


def _answer(text: str = "63 octets.") -> Answer:
    hit = Hit(1, 1035, "section-2.3.4", "2.3.4", "Size limits", "labels 63 octets", 0.8)
    trace = Trace("q")
    trace.llm_calls = 1
    return Answer("synthesis", text, trace, hits=[hit], used=[hit],
                  quote="labels 63 octets", grounded=True)


@pytest.fixture
def stub(monkeypatch):
    monkeypatch.setattr(chat, "ask", lambda q: _answer())
    monkeypatch.setattr(chat.llm, "last_usage",
                        {"prompt_tokens": 1000, "completion_tokens": 100})


# --- follow-up resolution: pure, no database ---

def test_a_standalone_question_is_left_alone():
    history = [("user", "what is a CNAME?"), ("assistant", "An alias.")]
    q = "what is the maximum length of a DNS label?"
    assert chat.resolve(q, history) == q


@pytest.mark.parametrize("follow_up", [
    "what about TTL?", "why?", "and NSEC3?", "is it still current?",
    "does it apply to IPv6?", "what else?",
])
def test_follow_ups_inherit_the_previous_subject(follow_up):
    history = [("user", "what is a CNAME record?"), ("assistant", "An alias.")]
    assert chat.resolve(follow_up, history).startswith("what is a CNAME record?")


def test_short_questions_are_treated_as_follow_ups():
    history = [("user", "how does DNSSEC work?"), ("assistant", "...")]
    assert chat.resolve("NSEC3 records?", history).startswith("how does DNSSEC work?")


def test_the_first_message_has_nothing_to_inherit():
    assert chat.resolve("why?", []) == "why?"


def test_resolution_uses_the_last_user_turn_not_the_assistant():
    history = [("user", "what is a SOA record?"), ("assistant", "It holds the serial.")]
    assert "It holds the serial" not in chat.resolve("why?", history)


# --- budget and read-only ---

def test_tokens_accumulate_across_turns(stub):
    c = chat.create(budget=10_000)
    assert c.tokens_used == 0
    turn = chat.send(str(c.id), "what is the maximum length of a DNS label?", lambda a: [])
    assert turn.chat.tokens_used == 1100
    turn = chat.send(str(c.id), "what is a CNAME record?", lambda a: [])
    assert turn.chat.tokens_used == 2200
    assert turn.chat.state == "open"


def test_chat_becomes_readonly_when_the_budget_is_spent(stub):
    c = chat.create(budget=2000)
    chat.send(str(c.id), "what is the maximum length of a DNS label?", lambda a: [])
    turn = chat.send(str(c.id), "what is a CNAME record?", lambda a: [])
    assert turn.chat.readonly
    assert turn.chat.tokens_left == 0


def test_a_readonly_chat_rejects_new_messages(stub):
    c = chat.create(budget=1100)
    chat.send(str(c.id), "what is the maximum length of a DNS label?", lambda a: [])
    with pytest.raises(chat.ChatClosed, match="read-only"):
        chat.send(str(c.id), "what is a CNAME record?", lambda a: [])


def test_a_readonly_chat_is_still_readable(stub):
    c = chat.create(budget=1100)
    chat.send(str(c.id), "what is the maximum length of a DNS label?", lambda a: [])
    assert chat.get(str(c.id)).readonly
    assert len(chat.messages(str(c.id))) == 2


def test_history_is_stored_as_alternating_turns(stub):
    c = chat.create(budget=50_000)
    chat.send(str(c.id), "what is the maximum length of a DNS label?", lambda a: [])
    chat.send(str(c.id), "and the full name?", lambda a: [])
    rows = chat.messages(str(c.id))
    assert [m["role"] for m in rows] == ["user", "assistant", "user", "assistant"]
    assert [m["position"] for m in rows] == [0, 1, 2, 3]


def test_a_follow_up_records_what_it_was_resolved_to(stub):
    c = chat.create(budget=50_000)
    chat.send(str(c.id), "what is a CNAME record?", lambda a: [])
    chat.send(str(c.id), "why?", lambda a: [])
    stored = [m for m in chat.messages(str(c.id)) if m["role"] == "user"]
    assert stored[0]["resolved_question"] is None
    assert "CNAME" in stored[1]["resolved_question"]


def test_the_title_comes_from_the_first_question(stub):
    c = chat.create(budget=50_000)
    turn = chat.send(str(c.id), "what is the maximum length of a DNS label?", lambda a: [])
    assert turn.chat.title == "what is the maximum length of a DNS label?"
    turn = chat.send(str(c.id), "something else entirely here", lambda a: [])
    assert turn.chat.title == "what is the maximum length of a DNS label?"


def test_missing_chat_raises():
    with pytest.raises(chat.ChatMissing):
        chat.get("00000000-0000-0000-0000-000000000000")


def test_a_chat_of_free_turns_still_closes_on_message_count(monkeypatch):
    """Facts-route turns cost no tokens, so the budget alone would never close them."""
    monkeypatch.setattr(chat, "ask", lambda q: _answer())
    monkeypatch.setattr(chat.llm, "last_usage", {"prompt_tokens": 0, "completion_tokens": 0})
    c = chat.create(budget=100_000)
    with connect_max_messages(str(c.id), 4):
        chat.send(str(c.id), "is RFC 2065 still current?", lambda a: [])
        turn = chat.send(str(c.id), "is RFC 1035 still current?", lambda a: [])
    assert turn.chat.tokens_used == 0
    assert turn.chat.readonly
    with pytest.raises(chat.ChatClosed, match="message limit"):
        chat.send(str(c.id), "one more", lambda a: [])


def test_turns_left_counts_down():
    c = chat.create()
    assert c.turns_left == c.max_messages // 2


import contextlib

from rfc_rag.db import connect


@contextlib.contextmanager
def connect_max_messages(chat_id: str, limit: int):
    with connect() as conn, conn.cursor() as cur:
        cur.execute("update chat set max_messages = %s where id = %s", (limit, chat_id))
        conn.commit()
    yield


@pytest.mark.parametrize("bad", ["not-a-uuid", "", "123", "' or 1=1 --"])
def test_a_malformed_id_is_a_missing_chat_not_a_server_error(bad):
    with pytest.raises(chat.ChatMissing):
        chat.get(bad)
    with pytest.raises(chat.ChatMissing):
        chat.messages(bad)
