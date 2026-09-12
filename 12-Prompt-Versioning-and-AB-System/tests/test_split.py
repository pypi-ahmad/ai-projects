from pathlib import Path

from promptreg.registry.models import PromptConfig
from promptreg.registry.storage import Registry
from promptreg.split.models import Arm
from promptreg.split.storage import ExperimentStore

CONFIG = PromptConfig(model="stub", provider="stub")
SAMPLE_SIZE = 1000
LOOSE_BOUND = 50


def _setup(tmp_path: Path) -> tuple[Registry, ExperimentStore]:
    db_path = tmp_path / "registry.db"
    registry = Registry(db_path, tmp_path / "prompts")
    experiments = ExperimentStore(db_path)
    return registry, experiments


def test_list_experiments(tmp_path: Path) -> None:
    registry, experiments = _setup(tmp_path)
    v1 = registry.publish("greeting", "control body", CONFIG, "v1", "ada")
    exp = experiments.create_experiment(
        "tone-test", "greeting", [Arm(name="control", version=v1.version, weight=100)]
    )

    listed = experiments.list_experiments("greeting")
    assert [e.id for e in listed] == [exp.id]
    assert experiments.list_experiments("nonexistent") == []


def test_bucket_distribution_matches_weights_within_loose_bound(tmp_path: Path) -> None:
    registry, experiments = _setup(tmp_path)
    v1 = registry.publish("greeting", "control body", CONFIG, "v1", "ada")
    v2 = registry.publish("greeting", "treatment body", CONFIG, "v2", "ada")
    exp = experiments.create_experiment(
        "tone-test",
        "greeting",
        [
            Arm(name="control", version=v1.version, weight=70),
            Arm(name="treat_a", version=v2.version, weight=30),
        ],
    )
    experiments.set_status(exp.id, "running")

    counts = {"control": 0, "treat_a": 0}
    for i in range(SAMPLE_SIZE):
        resolution = experiments.resolve(registry, "greeting", f"user-{i}", "prod")
        counts[resolution.arm] += 1

    assert abs(counts["control"] - 700) < LOOSE_BOUND
    assert abs(counts["treat_a"] - 300) < LOOSE_BOUND


def test_same_key_same_arm(tmp_path: Path) -> None:
    registry, experiments = _setup(tmp_path)
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

    first = experiments.resolve(registry, "greeting", "steady-user", "prod")
    second = experiments.resolve(registry, "greeting", "steady-user", "prod")
    assert first.arm == second.arm
    assert first.version == second.version


def test_rollback_of_pointer_does_not_break_running_experiment(tmp_path: Path) -> None:
    registry, experiments = _setup(tmp_path)
    v1 = registry.publish("greeting", "v1 body", CONFIG, "v1", "ada")
    v2 = registry.publish("greeting", "v2 body", CONFIG, "v2", "ada")
    registry.set_pointer("greeting", "prod", v1.version)
    registry.set_pointer("greeting", "prod", v2.version)

    exp = experiments.create_experiment(
        "tone-test", "greeting", [Arm(name="control", version=v1.version, weight=100)]
    )
    experiments.set_status(exp.id, "running")

    registry.rollback("greeting", "prod")  # unrelated to the experiment

    resolution = experiments.resolve(registry, "greeting", "some-user", "prod")
    assert resolution.experiment_id == exp.id
    assert resolution.version == v1.version
    assert resolution.reason == "experiment_new"


def test_paused_experiment_honors_sticky_but_not_new_users(tmp_path: Path) -> None:
    registry, experiments = _setup(tmp_path)
    v1 = registry.publish("greeting", "v1 body", CONFIG, "v1", "ada")
    registry.set_pointer("greeting", "prod", v1.version)
    v2 = registry.publish("greeting", "v2 body", CONFIG, "v2", "ada")

    exp = experiments.create_experiment(
        "tone-test", "greeting", [Arm(name="treat_a", version=v2.version, weight=100)]
    )
    experiments.set_status(exp.id, "running")
    sticky = experiments.resolve(registry, "greeting", "early-user", "prod")
    assert sticky.arm == "treat_a"

    experiments.set_status(exp.id, "paused")

    still_sticky = experiments.resolve(registry, "greeting", "early-user", "prod")
    assert still_sticky.arm == "treat_a"
    assert still_sticky.reason == "experiment_sticky"

    new_user = experiments.resolve(registry, "greeting", "brand-new-user", "prod")
    assert new_user.arm is None
    assert new_user.experiment_id is None
    assert new_user.version == v1.version
    assert new_user.reason == "pointer"
