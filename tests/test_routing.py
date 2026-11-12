import pytest

from rfc_rag.models import Change
from rfc_rag.services import stages


@pytest.mark.parametrize("question", [
    "what was the last spec change in dns model?",
    "what changed recently in DNS?",
    "what are the most recent DNS updates",
    "which RFCs were published last",
    "latest revisions to DNSSEC",
    "what was updated most recently",
])
def test_aggregate_change_questions_get_their_own_route(question):
    """These ask about the corpus, not a document, so no facts route fits."""
    assert stages.plan(stages.analyse(question)) == "recent_changes"


@pytest.mark.parametrize("question,route", [
    ("is RFC 2065 still current", "facts"),
    ("what replaced RFC 2845", "facts"),
    ("what updates RFC 1035", "facts"),
    ("what is the current DNS specification", "topic_facts"),
    ("what does RFC 2181 say about TTL", "passage"),
    ("what is a CNAME record", "synthesis"),
    ("how do wildcards work in DNS", "synthesis"),
])
def test_other_routes_are_unchanged(question, route):
    assert stages.plan(stages.analyse(question)) == route


def test_a_named_rfc_still_wins_over_the_aggregate_route():
    """'what changed in RFC 1035 recently' is about that document."""
    assert stages.plan(stages.analyse("what changed in RFC 1035 recently")) == "facts"


def test_change_alone_no_longer_hijacks_the_question():
    """The word 'change' used to route anything to topic_facts."""
    a = stages.analyse("what was the last spec change in dns model?")
    assert a.intent == "updated"          # the intent still matches
    assert stages.plan(a) != "topic_facts"  # but it no longer decides the route


def test_change_sentence_reads_correctly():
    obs = Change("obsoletes", 10001, "New", 2026, 3901, "Old")
    upd = Change("updates", 9975, "Clarifications", 2026, 7344, "Automating")
    assert obs.sentence == "RFC 10001 (2026) replaced RFC 3901"
    assert upd.sentence == "RFC 9975 (2026) updated RFC 7344"
