"""Seed demo data: publishes greet v1/v2, starts a 50/50 experiment,
resolves 20 fake users, and records + tracks an outcome for each.

Meant to run once against a fresh data/ dir (uses monotonic version
numbers and only allows one running experiment per prompt, so re-running
against the same data/ will fail on the second `create_experiment`/
`set_status` call). Point PROMPTREG_DB_PATH etc. at a scratch dir to
re-run it.

    uv run python scripts/seed_demo.py
"""

from __future__ import annotations

import os
import random

from promptreg.execute.models import ExecutionResult
from promptreg.outcomes.models import OutcomeMetrics
from promptreg.outcomes.storage import OutcomeStore
from promptreg.registry.models import PromptConfig
from promptreg.registry.storage import Registry
from promptreg.split.models import Arm
from promptreg.split.storage import ExperimentStore

DB_PATH = os.environ.get("PROMPTREG_DB_PATH", "data/registry.db")
PROMPTS_DIR = os.environ.get("PROMPTREG_PROMPTS_DIR", "data/prompts")
OUTCOMES_JSONL = os.environ.get("PROMPTREG_OUTCOMES_JSONL", "data/outcomes.jsonl")

CONFIG = PromptConfig(model="stub", provider="stub")
FAKE_USERS = 20


def main() -> None:
    registry = Registry(DB_PATH, PROMPTS_DIR)
    experiments = ExperimentStore(DB_PATH)
    outcomes = OutcomeStore(DB_PATH, OUTCOMES_JSONL)

    v1 = registry.publish("greet", "Hello, {name}!", CONFIG, "baseline greeting", "seed")
    v2 = registry.publish(
        "greet", "Hi {name}, great to see you!", CONFIG, "friendlier tone", "seed"
    )
    registry.set_pointer("greet", "prod", v1.version)

    experiment = experiments.create_experiment(
        "greet-tone-test",
        "greet",
        [
            Arm(name="control", version=v1.version, weight=50),
            Arm(name="treat_a", version=v2.version, weight=50),
        ],
    )
    experiments.set_status(experiment.id, "running")

    rng = random.Random(0)
    for i in range(FAKE_USERS):
        user_key = f"seed-user-{i}"
        resolution = experiments.resolve(registry, "greet", user_key, "prod")
        version = registry.get("greet", resolution.version)
        # fake execution stats (stub provider is always dry+instant) so the
        # Outcomes table's latency column has something to show.
        result = ExecutionResult(
            body=version.body or "",
            config=version.config,
            dry=True,
            output=None,
            ok=rng.random() > 0.05,
            latency_ms=rng.uniform(80, 350),
        )
        event = outcomes.record(
            user_key,
            "greet",
            resolution.version,
            resolution.arm,
            resolution.experiment_id,
            result,
        )
        outcomes.track(
            event.request_id,
            OutcomeMetrics(
                thumbs=rng.choice([1, 1, -1, None]), task_ok=rng.choice([True, True, False])
            ),
        )

    print(f"Seeded 'greet': v{v1.version} (control), v{v2.version} (treat_a)")
    print(f"Experiment #{experiment.id} 'greet-tone-test' running, 50/50")
    print(f"Recorded {FAKE_USERS} outcomes for {FAKE_USERS} fake users")


if __name__ == "__main__":
    main()
