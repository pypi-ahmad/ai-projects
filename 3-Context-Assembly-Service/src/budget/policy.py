"""
BudgetPolicy — per-family caps and reserve fractions. Loaded from config/policies/*.yaml.
See src/budget/allocator.py for how caps and reserves are actually applied.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import yaml

_POLICIES_DIR = Path(__file__).parent.parent.parent / "config" / "policies"
# Process-lifetime cache keyed by policy name. A YAML file edited on disk is not
# picked up until the process restarts — there is no invalidation.
_cache: dict[str, "BudgetPolicy"] = {}


@dataclass
class FamilyCaps:
    memory: float
    docs: float
    tools: float

    def __post_init__(self) -> None:
        total = self.memory + self.docs + self.tools
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Family caps must sum to 1.0, got {total:.3f}")


@dataclass
class BudgetPolicy:
    name: str
    caps: FamilyCaps
    output_pct: float = 0.20   # fraction of context_window reserved for model output
    system_pct: float = 0.08   # fraction of context_window reserved for system prompt
    description: str = ""

    def output_reserve(self, window: int) -> int:
        return int(window * self.output_pct)

    def system_reserve(self, window: int) -> int:
        return int(window * self.system_pct)


def load_policy(name: str) -> BudgetPolicy:
    """Load a named policy from config/policies/{name}.yaml. Cached after first load."""
    if name in _cache:
        return _cache[name]
    path = _POLICIES_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"Policy '{name}' not found at {path}. "
            f"Available: {[p.stem for p in _POLICIES_DIR.glob('*.yaml')]}"
        )
    with open(path, encoding="utf-8") as f:
        d = yaml.safe_load(f)
    c = d["caps"]
    policy = BudgetPolicy(
        name=d["name"],
        caps=FamilyCaps(memory=c["memory"], docs=c["docs"], tools=c["tools"]),
        output_pct=d.get("output_pct", 0.20),
        system_pct=d.get("system_pct", 0.08),
        description=d.get("description", ""),
    )
    _cache[name] = policy
    return policy
