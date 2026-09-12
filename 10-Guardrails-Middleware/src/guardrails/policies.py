"""Policy names for guardrails enforcement.

Partially wired: `Pipeline.run()` (see `pipeline.py`) reads the active
policy for exactly one thing -- `"observe"` skips the block short-circuit,
so nothing is actually blocked, only reported. Beyond that it's still a
stub: `pii.py`, `rules.py`, and `providers.py` each pick their own
severity/threshold from their own YAML config, independent of which
`Policy` is active. Wiring policy-based threshold selection into those
modules is future-phase work — see docs/POLICIES.md.
"""

from __future__ import annotations

from typing import Literal

Policy = Literal["strict", "standard", "observe"]
DEFAULT_POLICY: Policy = "standard"
