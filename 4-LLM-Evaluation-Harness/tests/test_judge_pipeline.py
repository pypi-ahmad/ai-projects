import json

from src.dataset import Case
from src.judge import repair as repair_module
from src.judge.pipeline import judge_case
from src.judge.rubric import Rubric
from src.providers.base import ProviderSpec

VALID_VERDICT_JSON = json.dumps(
    {
        "scores": {"correctness": 0.9, "completeness": 0.8},
        "overall": 0.85,
        "pass": True,
        "rationale": "Good answer",
        "evidence_spans": ["4"],
    }
)


def _rubric() -> Rubric:
    return Rubric.model_validate(
        {
            "id": "test_rubric",
            "version": 1,
            "dimensions": [
                {"name": "correctness", "description": "x", "weight": 0.5},
                {"name": "completeness", "description": "y", "weight": 0.5},
            ],
        }
    )


def _case(*, judge_required: bool | None = True) -> Case:
    judge = (
        {"rubric_id": "test_rubric", "required": judge_required}
        if judge_required is not None
        else None
    )
    data = {"id": "c1", "suite": "smoke", "input": {"user": "2+2?"}}
    if judge is not None:
        data["judge"] = judge
    return Case.model_validate(data)


class _ScriptedProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.think_values: list[bool | None] = []
        self.unload_calls: list[str] = []

    def complete(self, *, system, user, model, think=None):
        self.think_values.append(think)
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        if isinstance(response, Exception):
            raise response
        return response

    def unload(self, model: str) -> None:
        self.unload_calls.append(model)


def _patch_ollama_repair(monkeypatch, provider):
    monkeypatch.setitem(
        repair_module.PROVIDERS,
        "ollama",
        ProviderSpec(
            factory=lambda: provider, default_model="qwen3.5:0.8b", allowed_models=("qwen3.5:0.8b",)
        ),
    )


def test_judge_case_returns_none_when_case_has_no_judge():
    case = _case(judge_required=None)

    def _fail(**kwargs):
        raise AssertionError("provider should never be called")

    provider = type("P", (), {"complete": staticmethod(_fail)})()

    result = judge_case(
        case,
        candidate_text="4",
        rubric=_rubric(),
        judge_provider=provider,
        judge_provider_name="ollama",
        judge_model="granite4.1:3b",
        candidate_provider_name="ollama",
        candidate_model="granite4.1:3b",
    )

    assert result is None


def test_judge_case_valid_json_on_first_try():
    case = _case()
    provider = _ScriptedProvider([VALID_VERDICT_JSON])

    result = judge_case(
        case,
        candidate_text="4",
        rubric=_rubric(),
        judge_provider=provider,
        judge_provider_name="gemini",
        judge_model="gemini-3.5-flash-lite",
        candidate_provider_name="ollama",
        candidate_model="granite4.1:3b",
    )

    assert result.status == "ok"
    assert result.overall == 0.85
    assert result.passed is True
    assert result.scores == {"correctness": 0.9, "completeness": 0.8}
    assert result.same_model_warning is False
    assert provider.think_values == [False]  # judge calls always force thinking off


def test_judge_case_flags_same_model_warning():
    case = _case()
    provider = _ScriptedProvider([VALID_VERDICT_JSON])

    result = judge_case(
        case,
        candidate_text="4",
        rubric=_rubric(),
        judge_provider=provider,
        judge_provider_name="ollama",
        judge_model="granite4.1:3b",
        candidate_provider_name="ollama",
        candidate_model="granite4.1:3b",
    )

    assert result.same_model_warning is True


def test_judge_case_repairs_malformed_json(monkeypatch):
    repair_provider = _ScriptedProvider([VALID_VERDICT_JSON])
    _patch_ollama_repair(monkeypatch, repair_provider)

    judge_provider = _ScriptedProvider(["```json\n" + VALID_VERDICT_JSON + "\n```"])

    result = judge_case(
        _case(),
        candidate_text="4",
        rubric=_rubric(),
        judge_provider=judge_provider,
        judge_provider_name="gemini",
        judge_model="gemini-3.5-flash-lite",
        candidate_provider_name="ollama",
        candidate_model="granite4.1:3b",
    )

    assert result.status == "ok"
    assert repair_provider.calls == 1
    assert repair_provider.think_values == [False]  # repair also forces thinking off
    assert repair_provider.unload_calls == ["qwen3.5:0.8b"]


def test_required_judge_failure_flips_pass_to_false(monkeypatch):
    def _ollama_unavailable():
        raise RuntimeError("ollama not running")

    monkeypatch.setitem(
        repair_module.PROVIDERS,
        "ollama",
        ProviderSpec(factory=_ollama_unavailable, default_model="x", allowed_models=("x",)),
    )
    judge_provider = _ScriptedProvider(["not json at all", "still not json"])

    result = judge_case(
        _case(judge_required=True),
        candidate_text="4",
        rubric=_rubric(),
        judge_provider=judge_provider,
        judge_provider_name="gemini",
        judge_model="gemini-3.5-flash-lite",
        candidate_provider_name="ollama",
        candidate_model="granite4.1:3b",
    )

    assert result.status == "judge_error"
    assert result.passed is False
    assert result.overall is None
    assert judge_provider.calls == 2  # primary call + fallback repair call


def test_non_required_judge_failure_is_skipped(monkeypatch):
    def _ollama_unavailable():
        raise RuntimeError("ollama not running")

    monkeypatch.setitem(
        repair_module.PROVIDERS,
        "ollama",
        ProviderSpec(factory=_ollama_unavailable, default_model="x", allowed_models=("x",)),
    )
    judge_provider = _ScriptedProvider(["not json at all", "still not json"])

    result = judge_case(
        _case(judge_required=False),
        candidate_text="4",
        rubric=_rubric(),
        judge_provider=judge_provider,
        judge_provider_name="gemini",
        judge_model="gemini-3.5-flash-lite",
        candidate_provider_name="ollama",
        candidate_model="granite4.1:3b",
    )

    assert result is None
