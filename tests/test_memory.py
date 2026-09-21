"""Tests for memory and the built-in tools.

Memory is the only stateful thing in the suite, so the tests that matter are the ones about
not losing or corrupting it -- and about failing soft, since a broken memory file must
degrade what the assistant knows rather than whether it runs.
"""

import json

import pytest

from assistant.builtins import memory_tools
from assistant.memory import MemoryStore


@pytest.fixture
def store(tmp_path):
    return MemoryStore(tmp_path / "memory.json")


def test_a_fact_survives_a_round_trip(store):
    store.add("person", "Kwame", "colleague on claims")
    facts = store.load()
    assert len(facts) == 1
    assert (facts[0].kind, facts[0].subject) == ("person", "Kwame")


def test_recording_the_same_subject_again_corrects_rather_than_duplicates(store):
    """Two contradictory facts in one prompt is worse than either alone."""
    store.add("person", "Kwame", "colleague")
    store.add("person", "kwame", "colleague, leads the claims project")
    facts = store.load()
    assert len(facts) == 1
    assert "leads" in facts[0].content


def test_the_same_subject_under_a_different_kind_is_a_separate_fact(store):
    store.add("person", "AyaData", "the company")
    store.add("spelling", "AyaData", "aya data")
    assert len(store.load()) == 2


def test_an_unknown_kind_is_refused(store):
    with pytest.raises(ValueError):
        store.add("nonsense", "x", "y")


def test_a_fact_can_be_removed_by_id(store):
    fact = store.add("fact", "x", "y")
    assert store.remove(fact.id) is not None
    assert store.load() == []


def test_removing_something_that_is_not_there_reports_so(store):
    assert store.remove("nope") is None


def test_a_missing_store_is_simply_empty(store):
    """Memory failing must never stop the assistant from working."""
    assert store.load() == []


def test_a_corrupt_store_degrades_instead_of_crashing(tmp_path):
    path = tmp_path / "memory.json"
    path.write_text("{not json at all", encoding="utf-8")
    assert MemoryStore(path).load() == []


def test_a_fact_with_no_subject_is_skipped(tmp_path):
    path = tmp_path / "memory.json"
    path.write_text(json.dumps({"facts": [{"kind": "fact", "content": "orphan"}]}), encoding="utf-8")
    assert MemoryStore(path).load() == []


# ---------------------------------------------------------------------------
# The lexicon seam
# ---------------------------------------------------------------------------

def test_only_spelling_facts_become_the_lexicon(store):
    store.add("spelling", "AyaData", "aya data, ayadata")
    store.add("person", "Kwame", "colleague")
    assert store.lexicon() == {"AyaData": ["aya data", "ayadata"]}


def test_the_lexicon_file_is_shaped_the_way_meet_ai_reads_it(store, tmp_path):
    """meet-ai takes a lexicon as an argument and never reaches for a memory store, which
    is what keeps it usable with the assistant absent. This is that handover."""
    store.add("spelling", "round robin", "round robinson, round robins")
    path = store.write_lexicon(tmp_path / "lexicon.json")
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "round robin": ["round robinson", "round robins"]
    }


def test_no_spelling_facts_means_no_lexicon_file(store, tmp_path):
    """Handing a tool an empty lexicon would be a call that does nothing, reported as if
    it did something."""
    store.add("person", "Kwame", "colleague")
    assert store.write_lexicon(tmp_path / "lexicon.json") is None


# ---------------------------------------------------------------------------
# The prompt block
# ---------------------------------------------------------------------------

def test_an_empty_store_contributes_nothing_to_the_prompt(store):
    assert store.as_prompt_block() == ""


def test_memory_is_framed_as_background_not_instruction(store):
    """A remembered line is data the user wrote once, not an order that outranks what they
    are saying now."""
    store.add("preference", "tone", "keep it short")
    block = store.as_prompt_block()
    assert "background, not as instructions" in block
    assert "keep it short" in block


# ---------------------------------------------------------------------------
# Built-in tools
# ---------------------------------------------------------------------------

def test_both_memory_tools_pass_through_the_gate(store):
    """You should see what the assistant writes down about you, as it decides to."""
    assert all(tool.read_only is False for tool in memory_tools(store))


def test_remember_writes_a_fact(store):
    remember = next(t for t in memory_tools(store) if t.name == "remember")
    out = json.loads(remember.handler({"kind": "fact", "subject": "s", "content": "c"}))
    assert "remembered" in out
    assert store.load()[0].subject == "s"


def test_forget_removes_one(store):
    tools = {t.name: t for t in memory_tools(store)}
    fact = store.add("fact", "s", "c")
    out = json.loads(tools["forget"].handler({"id": fact.id}))
    assert out["forgot"] == fact.id
    assert store.load() == []


def test_forgetting_an_unknown_id_reports_it_rather_than_failing(store):
    forget = next(t for t in memory_tools(store) if t.name == "forget")
    assert "error" in json.loads(forget.handler({"id": "nope"}))
