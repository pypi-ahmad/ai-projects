"""Post-generation citation validation: every [S#]/[W#] tag in the answer
must reference a chunk actually supplied as context. See docs/CITATIONS.md.
"""

import re

_CITATION_RE = re.compile(r"\[([SW])(\d+)\]")
_CITATION_WITH_SPACE_RE = re.compile(r" ?\[([SW])(\d+)\]")


def check_citations(answer_text: str, *, n_source: int, n_web: int) -> tuple[str, list[str], bool]:
    """Returns (cleaned_text, citation_tags_present, illegal_citation_found).

    An illegal tag (referencing a chunk index beyond what was supplied) is
    stripped from the text along with one preceding space. Whether that's the
    right response (vs. failing closed) is the caller's policy decision --
    see agent/loop.py's `citation_fail_closed`.
    """
    allowed = {f"S{i}" for i in range(1, n_source + 1)} | {f"W{i}" for i in range(1, n_web + 1)}
    illegal_found = False

    def _strip_if_illegal(match: re.Match) -> str:
        nonlocal illegal_found
        tag = f"{match.group(1)}{match.group(2)}"
        if tag in allowed:
            return match.group(0)
        illegal_found = True
        return ""

    cleaned = _CITATION_WITH_SPACE_RE.sub(_strip_if_illegal, answer_text)
    used = [f"{letter}{number}" for letter, number in _CITATION_RE.findall(cleaned)]
    return cleaned, used, illegal_found
