"""Unit tests for the [S#]/[W#] post-generation citation check."""

from self_correcting_rag.agent.citations import check_citations


def test_legal_citations_pass_through_unchanged():
    text = "First point [S1]. Second point [S2] and [W1]."
    cleaned, used, illegal = check_citations(text, n_source=2, n_web=1)
    assert cleaned == text
    assert used == ["S1", "S2", "W1"]
    assert illegal is False


def test_illegal_citation_is_stripped_with_leading_space():
    text = "This claim is unsupported [S9]."
    cleaned, used, illegal = check_citations(text, n_source=1, n_web=0)
    assert cleaned == "This claim is unsupported."
    assert used == []
    assert illegal is True


def test_mixed_legal_and_illegal_citations():
    text = "Legal [S1] and illegal [W7] both appear."
    cleaned, used, illegal = check_citations(text, n_source=1, n_web=0)
    assert cleaned == "Legal [S1] and illegal both appear."
    assert used == ["S1"]
    assert illegal is True


def test_no_citations_present():
    cleaned, used, illegal = check_citations("No tags here.", n_source=3, n_web=2)
    assert cleaned == "No tags here."
    assert used == []
    assert illegal is False
