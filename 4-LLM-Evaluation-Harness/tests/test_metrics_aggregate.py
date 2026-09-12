from src.dataset import Case
from src.metrics.aggregate import score_case


def _case(**expected) -> Case:
    return Case.model_validate(
        {
            "id": "c1",
            "suite": "smoke",
            "input": {"user": "hi"},
            "expected": expected,
        }
    )


def test_score_case_only_includes_metrics_for_set_fields():
    case = _case(answer="4")

    result = score_case(case, text="The answer is 4", latency_ms=10.0)

    names = [m.name for m in result.metrics]
    assert names == ["latency_ms", "length_tokens_approx", "exact_match"]


def test_score_case_skips_metric_when_expected_field_absent():
    case = _case()  # no expected fields at all

    result = score_case(case, text="anything", latency_ms=10.0)

    names = [m.name for m in result.metrics]
    assert "exact_match" not in names
    assert "contains_all" not in names
    assert names == ["latency_ms", "length_tokens_approx"]


def test_score_case_runs_all_applicable_metrics():
    case = _case(
        contains_all=["jupiter"],
        contains_any=["planet"],
        forbidden_any=["mars"],
        regex=r"\d+",
        json_schema_name="ok_flag",
    )

    result = score_case(case, text="Jupiter is planet 5", latency_ms=5.0)

    names = {m.name for m in result.metrics}
    assert names == {
        "latency_ms",
        "length_tokens_approx",
        "contains_all",
        "contains_any",
        "forbidden_any",
        "regex",
        "json_parse_ok",
    }
    by_name = {m.name: m for m in result.metrics}
    assert by_name["json_parse_ok"].passed is False  # "Jupiter is planet 5" isn't JSON


def test_score_case_skips_content_metrics_when_text_is_none():
    case = _case(answer="4", contains_all=["x"])

    result = score_case(case, text=None, latency_ms=42.0)

    names = [m.name for m in result.metrics]
    assert names == ["latency_ms"]
    assert result.metrics[0].detail == "42.0"
