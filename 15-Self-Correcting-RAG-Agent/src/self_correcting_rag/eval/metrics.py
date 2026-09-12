"""Pure metric functions over eval results -- no live calls, easily unit-tested."""

from self_correcting_rag.eval.records import EvalCaseResult


def citation_legality_rate(results: list[EvalCaseResult]) -> float | None:
    """Fraction of ANSWERED cases where no illegal citation was detected
    before stripping. None (undefined) if nothing was answered.
    """
    answered = [r for r in results if r.answered]
    if not answered:
        return None
    return sum(1 for r in answered if not r.illegal_citation_found) / len(answered)


def abstain_on_unknown_rate(results: list[EvalCaseResult]) -> float | None:
    """Fraction of out_of_corpus cases that correctly abstained (answer is
    None). None (undefined) if the eval set has no out_of_corpus cases.
    """
    out_of_corpus = [r for r in results if r.case.category == "out_of_corpus"]
    if not out_of_corpus:
        return None
    return sum(1 for r in out_of_corpus if not r.answered) / len(out_of_corpus)


def no_web_when_disabled_rate(results: list[EvalCaseResult], *, web_enabled: bool) -> float | None:
    """When the eval run had web disabled, the fraction of cases where web
    genuinely never fired -- should always be 1.0 if the disable mechanism
    holds. None (undefined) if the run had web enabled or there are no
    results; this metric only means something for a disabled-web run.
    """
    if web_enabled or not results:
        return None
    return sum(1 for r in results if not r.web_fired) / len(results)
