import json

import pytest

from src.dataset import Case
from src.providers.base import ProviderConfigError, ProviderSpec
from src.runners import candidate


class _FakeProvider:
    def __init__(self, fail_for: set[str] | None = None):
        self.calls: list[str] = []
        self.fail_for = fail_for or set()
        self.unload_calls: list[str] = []

    def complete(self, *, system, user, model, think=None):
        self.calls.append(user)
        if user in self.fail_for:
            raise RuntimeError("boom")
        return f"echo:{user}"

    def unload(self, model: str) -> None:
        self.unload_calls.append(model)


def _fake_spec(provider: _FakeProvider, model: str = "test-model") -> ProviderSpec:
    return ProviderSpec(factory=lambda: provider, default_model=model, allowed_models=(model,))


def _write_cases(path, *cases) -> None:
    path.write_text("\n".join(json.dumps(c) for c in cases), encoding="utf-8")


def test_run_candidate_writes_records(tmp_path, monkeypatch):
    dataset_path = tmp_path / "cases.jsonl"
    _write_cases(
        dataset_path,
        {"id": "c1", "suite": "smoke", "input": {"user": "hello"}},
        {"id": "c2", "suite": "smoke", "input": {"user": "world", "context": "ctx"}},
    )
    provider = _FakeProvider()
    monkeypatch.setitem(candidate.PROVIDERS, "fake", _fake_spec(provider))

    candidates_path = candidate.run_candidate(
        dataset_path=dataset_path,
        provider_name="fake",
        model="test-model",
        out_dir=tmp_path / "reports",
    )

    records = [json.loads(line) for line in candidates_path.read_text().splitlines()]
    assert [r["case_id"] for r in records] == ["c1", "c2"]
    assert records[0] == {
        "case_id": "c1",
        "text": "echo:hello",
        "model": "test-model",
        "provider": "fake",
        "latency_ms": records[0]["latency_ms"],
        "error": None,
        "skip_reason": None,
    }
    assert isinstance(records[0]["latency_ms"], float)
    assert provider.calls == ["hello", "Context:\nctx\n\nworld"]


def test_run_candidate_resume_skips_completed(tmp_path, monkeypatch):
    dataset_path = tmp_path / "cases.jsonl"
    _write_cases(
        dataset_path,
        {"id": "c1", "suite": "smoke", "input": {"user": "hello"}},
        {"id": "c2", "suite": "smoke", "input": {"user": "world"}},
    )
    provider = _FakeProvider()
    monkeypatch.setitem(candidate.PROVIDERS, "fake", _fake_spec(provider))

    out_dir = tmp_path / "reports"
    run_dir = out_dir / "run-1"
    run_dir.mkdir(parents=True)
    (run_dir / "candidates.jsonl").write_text(
        json.dumps(
            {
                "case_id": "c1",
                "text": "old",
                "model": "test-model",
                "provider": "fake",
                "latency_ms": 1.0,
                "error": None,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    candidate.run_candidate(
        dataset_path=dataset_path,
        provider_name="fake",
        model="test-model",
        out_dir=out_dir,
        run_id="run-1",
        resume=True,
    )

    assert provider.calls == ["world"]


def test_run_candidate_captures_per_case_error(tmp_path, monkeypatch):
    dataset_path = tmp_path / "cases.jsonl"
    _write_cases(
        dataset_path,
        {"id": "c1", "suite": "smoke", "input": {"user": "boom"}},
        {"id": "c2", "suite": "smoke", "input": {"user": "ok"}},
    )
    provider = _FakeProvider(fail_for={"boom"})
    monkeypatch.setitem(candidate.PROVIDERS, "fake", _fake_spec(provider))

    candidates_path = candidate.run_candidate(
        dataset_path=dataset_path,
        provider_name="fake",
        model="test-model",
        out_dir=tmp_path / "reports",
    )

    records = [json.loads(line) for line in candidates_path.read_text().splitlines()]
    assert records[0]["text"] is None
    assert "boom" in records[0]["error"]
    assert records[1]["text"] == "echo:ok"


def test_run_candidate_rejects_unknown_model(tmp_path, monkeypatch):
    dataset_path = tmp_path / "cases.jsonl"
    _write_cases(dataset_path, {"id": "c1", "suite": "smoke", "input": {"user": "hi"}})
    provider = _FakeProvider()
    monkeypatch.setitem(candidate.PROVIDERS, "fake", _fake_spec(provider))

    with pytest.raises(ValueError, match="not allowed"):
        candidate.run_candidate(
            dataset_path=dataset_path,
            provider_name="fake",
            model="wrong-model",
            out_dir=tmp_path / "reports",
        )

    assert provider.calls == []


def test_run_candidate_propagates_provider_config_error(tmp_path, monkeypatch):
    dataset_path = tmp_path / "cases.jsonl"
    _write_cases(dataset_path, {"id": "c1", "suite": "smoke", "input": {"user": "hi"}})

    def _raising_factory():
        raise ProviderConfigError("missing key")

    spec = ProviderSpec(factory=_raising_factory, default_model="m", allowed_models=("m",))
    monkeypatch.setitem(candidate.PROVIDERS, "fake", spec)

    with pytest.raises(ProviderConfigError):
        candidate.run_candidate(
            dataset_path=dataset_path,
            provider_name="fake",
            model="m",
            out_dir=tmp_path / "reports",
        )


def _case(**skip_if) -> Case:
    data = {"id": "c1", "suite": "smoke", "input": {"user": "hi"}}
    if skip_if:
        data["skip_if"] = skip_if
    return Case.model_validate(data)


def test_skip_reason_none_when_no_skip_if():
    assert candidate.skip_reason(_case(), "ollama") is None


def test_skip_reason_needs_provider_mismatch():
    reason = candidate.skip_reason(_case(needs_provider="gemini"), "ollama")
    assert reason is not None and "needs_provider" in reason


def test_skip_reason_needs_provider_match_is_fine():
    assert candidate.skip_reason(_case(needs_provider="ollama"), "ollama") is None


def test_skip_reason_needs_ollama_with_other_provider():
    reason = candidate.skip_reason(_case(needs_ollama=True), "gemini")
    assert reason is not None and "needs_ollama" in reason


def test_skip_reason_needs_gpu_with_other_provider():
    reason = candidate.skip_reason(_case(needs_gpu=True), "agnes")
    assert reason is not None and "needs_gpu" in reason


def test_skip_reason_needs_ollama_and_gpu_satisfied_by_ollama():
    assert candidate.skip_reason(_case(needs_ollama=True, needs_gpu=True), "ollama") is None


def test_run_candidate_skips_case_without_calling_provider(tmp_path, monkeypatch):
    dataset_path = tmp_path / "cases.jsonl"
    _write_cases(
        dataset_path,
        {
            "id": "c1",
            "suite": "smoke",
            "input": {"user": "hi"},
            "skip_if": {"needs_provider": "ollama"},
        },
        {"id": "c2", "suite": "smoke", "input": {"user": "hello"}},
    )
    provider = _FakeProvider()
    monkeypatch.setitem(candidate.PROVIDERS, "fake", _fake_spec(provider))

    candidates_path = candidate.run_candidate(
        dataset_path=dataset_path,
        provider_name="fake",
        model="test-model",
        out_dir=tmp_path / "reports",
    )

    records = [json.loads(line) for line in candidates_path.read_text().splitlines()]
    assert provider.calls == ["hello"]  # c1 never sent to the provider
    assert records[0] == {
        "case_id": "c1",
        "text": None,
        "model": "test-model",
        "provider": "fake",
        "latency_ms": 0.0,
        "error": None,
        "skip_reason": "needs_provider='ollama', running with 'fake'",
    }
    assert records[1]["skip_reason"] is None


def test_run_candidate_unloads_ollama_model_when_provider_is_ollama(tmp_path, monkeypatch):
    dataset_path = tmp_path / "cases.jsonl"
    _write_cases(dataset_path, {"id": "c1", "suite": "smoke", "input": {"user": "hi"}})
    provider = _FakeProvider()
    monkeypatch.setitem(candidate.PROVIDERS, "ollama", _fake_spec(provider, model="test-model"))

    candidate.run_candidate(
        dataset_path=dataset_path,
        provider_name="ollama",
        model="test-model",
        out_dir=tmp_path / "reports",
    )

    assert provider.unload_calls == ["test-model"]


def test_run_candidate_does_not_unload_for_non_ollama_provider(tmp_path, monkeypatch):
    dataset_path = tmp_path / "cases.jsonl"
    _write_cases(dataset_path, {"id": "c1", "suite": "smoke", "input": {"user": "hi"}})
    provider = _FakeProvider()
    monkeypatch.setitem(candidate.PROVIDERS, "fake", _fake_spec(provider))

    candidate.run_candidate(
        dataset_path=dataset_path,
        provider_name="fake",
        model="test-model",
        out_dir=tmp_path / "reports",
    )

    assert provider.unload_calls == []
