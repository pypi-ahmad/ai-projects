"""Cache policy config: config/cache.yaml, loaded once per SemanticCache.

A missing file falls back to the same defaults documented in that file --
policy is enforced even if no config was ever written to disk.
"""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

DEFAULT_POLICY_CONFIG_PATH = Path("config/cache.yaml")

# Checked against an answer's text (src/policy/enforcement.py:check_puttable)
# before it's ever embedded/stored: API keys, secret/password assignments,
# and 16-digit-grouped numbers (credit-card-shaped). Best-effort pattern
# matching, not a guarantee -- content that doesn't match these shapes is
# still cached as-is.
DEFAULT_NEVER_CACHE_REGEXES = [
    r"(?i)api[-_ ]?key",
    r"(?i)\b(secret|password|passwd)\b\s*[:=]",
    r"\b\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}\b",
]


class PolicyConfig(BaseModel):
    threshold: float = 0.89
    ttl_seconds: int = 0
    max_entries: int = 10000
    min_answer_chars: int = 3
    never_cache_regexes: list[str] = Field(
        default_factory=lambda: list(DEFAULT_NEVER_CACHE_REGEXES)
    )
    require_same_producer_model: bool = True


def load_policy_config(path: Path = DEFAULT_POLICY_CONFIG_PATH) -> PolicyConfig:
    if not path.exists():
        return PolicyConfig()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return PolicyConfig(**data)
