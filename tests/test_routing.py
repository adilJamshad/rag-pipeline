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


@pytest.mark.parametrize("question", [
    "what does the last rfc on dns say?",
    "what is the newest DNS RFC",
    "which is the latest DNS specification",
    "show me the most recent RFCs",
    "what is the newest DNS standard",
])
def test_recency_about_the_subject_gets_a_date_ordered_route(question):
    """'the last RFC' is a date constraint; similarity cannot represent it."""
    assert stages.plan(stages.analyse(question)) == "recent_documents"


def test_recency_about_an_event_is_still_a_different_route():
    """'last change' and 'last RFC' are different questions."""
    assert stages.plan(stages.analyse("what changed last")) == "recent_changes"
    assert stages.plan(stages.analyse("what is the last RFC")) == "recent_documents"


def test_a_named_rfc_beats_both_recency_routes():
    assert stages.plan(stages.analyse("what does the latest RFC 1035 update say")) == "facts"


@pytest.mark.parametrize("question,expected", [
    ("what do RFCs published since 2020 say about NSEC3", "since"),
    ("what was the first DNS specification", "first"),
    ("which is the oldest DNS RFC still in force", "oldest"),
    ("what changed in 2024", "in 2024"),
    ("what is a CNAME record", None),
    ("how do wildcards work", None),
])
def test_unrepresentable_constraints_are_detected(question, expected):
    got = stages.unrepresentable_constraint(question)
    assert (got.lower() if got else None) == expected
