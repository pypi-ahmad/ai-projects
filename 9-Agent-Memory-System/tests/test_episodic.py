"""EpisodicMemory: session isolation, FTS5 keyword search (incl. punctuation
that would otherwise be an FTS5 syntax error), eviction policy."""

from datetime import datetime, timedelta, timezone

import pytest

from memory.episodic import Episode, EpisodicMemory, EvictionPolicy


@pytest.fixture
def store(tmp_path):
    mem = EpisodicMemory(db_path=tmp_path / "episodes.db")
    yield mem
    mem.close()


def test_write_and_list(store):
    store.write(Episode.create("s1", "utterance", "hello there"))
    store.write(Episode.create("s1", "tool", "ran a search"))

    items = store.list("s1")

    assert [item.type for item in items] == ["utterance", "tool"]
    assert all(item.session_id == "s1" for item in items)


def test_session_isolation(store):
    store.write(Episode.create("s1", "utterance", "session one secret"))
    store.write(Episode.create("s2", "utterance", "session two secret"))

    assert [e.session_id for e in store.list("s1")] == ["s1"]
    assert [e.session_id for e in store.list("s2")] == ["s2"]

    hits_s1 = store.search_keyword("s1", "secret")
    hits_s2 = store.search_keyword("s2", "secret")
    assert {e.session_id for e in hits_s1} == {"s1"}
    assert {e.session_id for e in hits_s2} == {"s2"}


def test_search_keyword(store):
    store.write(Episode.create("s1", "utterance", "the quick brown fox"))
    store.write(Episode.create("s1", "decision", "chose the slow turtle"))

    hits = store.search_keyword("s1", "fox")

    assert len(hits) == 1
    assert "fox" in hits[0].text


def test_search_keyword_handles_natural_language_punctuation(store):
    """Regression: a raw question like "...codename?" is a syntax error to
    FTS5 (bare "?" isn't valid query syntax) unless sanitized first --
    found by driving Phase 6's recall() through the actual Streamlit UI."""
    store.write(Episode.create("s1", "utterance", "the codename for this initiative is Nimbus Finch"))

    hits = store.search_keyword("s1", "what is the codename?")

    assert any("Nimbus Finch" in e.text for e in hits)


def test_search_keyword_no_tokens_returns_empty(store):
    store.write(Episode.create("s1", "utterance", "some content"))

    assert store.search_keyword("s1", "???") == []


def test_eviction_keeps_pinned(store):
    store.write(Episode.create("s1", "utterance", "keep me", salience=0.1, pinned=True))
    for i in range(5):
        store.write(Episode.create("s1", "utterance", f"filler {i}", salience=0.1))

    deleted = store.evict("s1", EvictionPolicy(max_rows=1, salience_threshold=0.5))

    remaining = store.list("s1")
    assert any(e.text == "keep me" and e.pinned for e in remaining)
    assert deleted == 5  # every unpinned filler row -- none clears the max_rows=1 cap alone


def test_eviction_low_salience_first(store):
    store.write(Episode.create("s1", "utterance", "high salience", salience=0.9))
    store.write(Episode.create("s1", "utterance", "low salience", salience=0.1))

    store.evict("s1", EvictionPolicy(max_rows=1, salience_threshold=0.95))

    remaining = [e.text for e in store.list("s1")]
    assert remaining == ["high salience"]


def test_eviction_max_age(store):
    old = Episode.create("s1", "utterance", "ancient", salience=0.1)
    old.ts = datetime.now(timezone.utc) - timedelta(days=30)
    store.write(old)
    store.write(Episode.create("s1", "utterance", "recent", salience=0.1))

    store.evict("s1", EvictionPolicy(max_age_days=7, salience_threshold=0.5))

    remaining = [e.text for e in store.list("s1")]
    assert remaining == ["recent"]
