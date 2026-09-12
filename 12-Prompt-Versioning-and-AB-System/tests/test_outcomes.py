from pathlib import Path

import pytest

from promptreg.execute.completer import execute
from promptreg.outcomes.models import OutcomeMetrics
from promptreg.outcomes.storage import OutcomeStore
from promptreg.registry.models import PromptConfig
from promptreg.registry.storage import Registry
from promptreg.split.models import Arm
from promptreg.split.storage import ExperimentStore

CONFIG = PromptConfig(model="stub", provider="stub")
SAMPLE_SIZE = 20


def _setup(tmp_path: Path) -> tuple[Registry, ExperimentStore, OutcomeStore]:
    db_path = tmp_path / "registry.db"
    registry = Registry(db_path, tmp_path / "prompts")
    experiments = ExperimentStore(db_path)
    outcomes = OutcomeStore(db_path, tmp_path / "outcomes.jsonl")
    return registry, experiments, outcomes


def test_track_two_arms_and_summary_counts(tmp_path: Path) -> None:
    registry, experiments, outcomes = _setup(tmp_path)
    v1 = registry.publish("greeting", "control body", CONFIG, "v1", "ada")
    v2 = registry.publish("greeting", "treatment body", CONFIG, "v2", "ada")
    exp = experiments.create_experiment(
        "tone-test",
        "greeting",
        [
            Arm(name="control", version=v1.version, weight=50),
            Arm(name="treat_a", version=v2.version, weight=50),
        ],
    )
    experiments.set_status(exp.id, "running")

    events_by_arm: dict[str, list[str]] = {"control": [], "treat_a": []}
    for i in range(SAMPLE_SIZE):
        user_key = f"user-{i}"
        resolution = experiments.resolve(registry, "greeting", user_key, "prod")
        version = registry.get("greeting", resolution.version)
        result = execute(version.body, version.config)
        event = outcomes.record(
            user_key,
            "greeting",
            resolution.version,
            resolution.arm,
            resolution.experiment_id,
            result,
        )
        events_by_arm[resolution.arm].append(event.request_id)

    assert events_by_arm["control"], "expected at least one control assignment"
    assert events_by_arm["treat_a"], "expected at least one treat_a assignment"

    outcomes.track(events_by_arm["control"][0], OutcomeMetrics(thumbs=1, task_ok=True))
    outcomes.track(events_by_arm["treat_a"][0], OutcomeMetrics(thumbs=-1, task_ok=False))

    summary = outcomes.summary(exp.id)
    assert set(summary.keys()) == {"control", "treat_a"}
    assert summary["control"]["count"] + summary["treat_a"]["count"] == SAMPLE_SIZE
    assert summary["control"]["thumbs_up"] == 1
    assert summary["control"]["task_ok"] == 1
    assert summary["treat_a"]["thumbs_down"] == 1
    assert summary["treat_a"]["task_ok"] == 0

    # derived, descriptive-only fields (no significance testing/Bayesian claims)
    assert summary["control"]["ok_rate"] == 1.0
    assert summary["control"]["thumbs_net"] == 1
    assert summary["treat_a"]["thumbs_net"] == -1
    assert summary["control"]["p50_latency_ms"] == 0.0
    assert summary["control"]["avg_latency_ms"] == 0.0


def test_track_unknown_request_id_raises(tmp_path: Path) -> None:
    _, _, outcomes = _setup(tmp_path)
    with pytest.raises(KeyError):
        outcomes.track("does-not-exist", OutcomeMetrics(thumbs=1))


def test_user_key_is_hashed_not_stored_raw(tmp_path: Path) -> None:
    registry, experiments, outcomes = _setup(tmp_path)
    v1 = registry.publish("greeting", "body", CONFIG, "v1", "ada")
    registry.set_pointer("greeting", "prod", v1.version)

    user_key = "super-secret-user-42"
    resolution = experiments.resolve(registry, "greeting", user_key, "prod")
    result = execute(v1.body, v1.config)
    event = outcomes.record(
        user_key, "greeting", resolution.version, resolution.arm, resolution.experiment_id, result
    )

    assert event.user_key_hash != user_key
    assert user_key not in outcomes.jsonl_path.read_text(encoding="utf-8")
