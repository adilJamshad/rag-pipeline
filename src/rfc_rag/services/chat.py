"""Multi-turn conversations over the stateless answering pipeline.

`ask()` stays stateless. A chat adds three things around it: history for
follow-up questions, a running token budget, and a terminal read-only state
when that budget is spent.
"""

import json
import re
import uuid
from dataclasses import dataclass, field

from ..clients import llm
from ..db import connect
from ..models import Answer
from .answering import ask

DEFAULT_BUDGET = 30000
MAX_MESSAGES = 60
HISTORY_TURNS = 3

# A follow-up is short, or leans on the previous turn instead of naming its
# subject. Rule-based on purpose: a model call to classify this would cost more
# than the question it is classifying.
FOLLOW_UP = re.compile(
    r"^\s*(and|but|what about|how about|why|why not|what else|ok|okay|then|also|"
    r"does it|is it|are they|do they|can it|can they|that|those|this|these|it|they)\b",
    re.I)


class ChatClosed(Exception):
    pass


class ChatMissing(Exception):
    pass


@dataclass
class Chat:
    id: uuid.UUID
    title: str | None
    state: str
    token_budget: int
    tokens_used: int
    message_count: int
    max_messages: int = MAX_MESSAGES

    @property
    def readonly(self) -> bool:
        return self.state == "readonly"

    @property
    def turns_left(self) -> int:
        return max(0, (self.max_messages - self.message_count) // 2)

    @property
    def tokens_left(self) -> int:
        return max(0, self.token_budget - self.tokens_used)


@dataclass
class Turn:
    answer: Answer
    chat: Chat
    resolved_question: str
    history_used: list[str] = field(default_factory=list)


def create(client: str | None = None, budget: int = DEFAULT_BUDGET) -> Chat:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""insert into chat (client, token_budget) values (%s, %s)
                       returning id, title, state, token_budget, tokens_used,
                                 message_count, max_messages""",
                    (client, budget))
        row = cur.fetchone()
        conn.commit()
    return Chat(*row)


def _as_uuid(chat_id: str) -> str:
    """A malformed id is a missing chat, not a database error."""
    try:
        return str(uuid.UUID(str(chat_id)))
    except (ValueError, AttributeError, TypeError):
        raise ChatMissing(f"chat {chat_id} not found") from None


def get(chat_id: str) -> Chat:
    chat_id = _as_uuid(chat_id)
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""select id, title, state, token_budget, tokens_used,
                              message_count, max_messages
                         from chat where id = %s""", (chat_id,))
        row = cur.fetchone()
    if not row:
        raise ChatMissing(f"chat {chat_id} not found")
    return Chat(*row)


def messages(chat_id: str) -> list[dict]:
    chat_id = _as_uuid(chat_id)
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""select position, role, content, at, route, quote, verified,
                              sources, tokens_in, tokens_out, resolved_question
                         from message where chat_id = %s order by position""", (chat_id,))
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def recent(chat_id: str, turns: int = HISTORY_TURNS) -> list[tuple[str, str]]:
    chat_id = _as_uuid(chat_id)
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""select role, content from message
                        where chat_id = %s order by position desc limit %s""",
                    (chat_id, turns * 2))
        return [(r, c) for r, c in reversed(cur.fetchall())]


def resolve(question: str, history: list[tuple[str, str]]) -> str:
    """Make a follow-up searchable on its own.

    Retrieval sees one string, so "what about TTL?" would match nothing useful.
    Prefixing the previous question restores the subject without a model call.
    """
    if not history:
        return question
    looks_like_follow_up = bool(FOLLOW_UP.match(question)) or len(question.split()) <= 4
    if not looks_like_follow_up:
        return question
    previous = next((c for r, c in reversed(history) if r == "user"), None)
    return f"{previous} {question}" if previous else question


def _title(question: str) -> str:
    text = question.strip()
    return text[:57] + "..." if len(text) > 60 else text


def send(chat_id: str, question: str, sources_of) -> Turn:
    chat = get(chat_id)
    if chat.readonly:
        reason = ("reached its message limit" if chat.message_count >= chat.max_messages
                  else f"used its {chat.token_budget:,} token budget")
        raise ChatClosed(f"This chat has {reason} and is read-only. "
                         f"Start a new chat to continue.")

    history = recent(chat_id)
    resolved = resolve(question, history)

    answer = ask(resolved)
    usage = llm.last_usage or {}
    tokens_in = usage.get("prompt_tokens") or 0
    tokens_out = usage.get("completion_tokens") or 0

    with connect() as conn, conn.cursor() as cur:
        # Lock the chat for the duration of the write. Reading message_count
        # outside the transaction let two concurrent sends pick the same
        # position, and the unique constraint turned that into a 500.
        cur.execute("select message_count from chat where id = %s for update", (chat_id,))
        row = cur.fetchone()
        if row is None:
            raise ChatMissing(f"chat {chat_id} not found")
        position = row[0]
        cur.execute("""insert into message (chat_id, position, role, content,
                                            resolved_question)
                       values (%s, %s, 'user', %s, %s)""",
                    (chat_id, position, question,
                     resolved if resolved != question else None))
        cur.execute("""insert into message (chat_id, position, role, content, route,
                                            quote, verified, sources, tokens_in, tokens_out)
                       values (%s, %s, 'assistant', %s, %s, %s, %s, %s, %s, %s)""",
                    (chat_id, position + 1, answer.text, answer.route, answer.quote,
                     answer.grounded, json.dumps(sources_of(answer)),
                     tokens_in, tokens_out))
        cur.execute("""update chat
                          set tokens_used = tokens_used + %s,
                              message_count = message_count + 2,
                              updated_at = now(),
                              title = coalesce(title, %s),
                              state = case
                                  when tokens_used + %s >= token_budget
                                    or message_count + 2 >= max_messages
                                  then 'readonly' else state end
                        where id = %s
                    returning id, title, state, token_budget, tokens_used,
                              message_count, max_messages""",
                    (tokens_in + tokens_out, _title(question),
                     tokens_in + tokens_out, chat_id))
        chat = Chat(*cur.fetchone())
        conn.commit()

    return Turn(answer, chat, resolved, [c for _, c in history])


def listing(client: str | None = None, limit: int = 20) -> list[dict]:
    with connect() as conn, conn.cursor() as cur:
        if client:
            cur.execute("""select id, title, state, tokens_used, token_budget,
                                  message_count, updated_at
                             from chat where client = %s
                            order by updated_at desc limit %s""", (client, limit))
        else:
            cur.execute("""select id, title, state, tokens_used, token_budget,
                                  message_count, updated_at
                             from chat order by updated_at desc limit %s""", (limit,))
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
