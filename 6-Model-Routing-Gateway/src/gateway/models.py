"""Request/response contracts shared by route/router.py, route/executor.py,
and the CLI/UI entry points. No routing or provider-call logic lives here —
only the Pydantic v2 models that carry data between those layers.
Next: route/router.py (turns a GatewayRequest + Features into a RouteDecision).
"""
from __future__ import annotations
from enum import Enum
from typing import Literal, Optional
from pydantic import BaseModel, Field

# Declaration order is significant: it is the upward-only promotion order
# (lite -> mid -> heavy) that route/router.py's _TIER_ORDER constant mirrors.
# The two are not linked in code — keep them in sync by hand if tiers change.
TierName = Literal["lite", "mid", "heavy"]


class RequestFlags(BaseModel):
    has_image: bool = False
    has_tools: bool = False
    long_context: bool = False


class GatewayRequest(BaseModel):
    id: str
    user_text: str
    system: Optional[str] = None
    need_json: bool = False
    max_tokens: Optional[int] = None
    preferred_tier: Optional[TierName] = None
    disallow_tiers: list[TierName] = Field(default_factory=list)
    schema_name: Optional[str] = None
    flags: RequestFlags = Field(default_factory=RequestFlags)


class ReasonCode(str, Enum):
    PREFERRED_TIER_USED = "PREFERRED_TIER_USED"
    AUTO_SELECTED = "AUTO_SELECTED"
    FALLBACK_FROM_PREFERRED = "FALLBACK_FROM_PREFERRED"
    SKIPPED_SCORE_RANGE = "SKIPPED_SCORE_RANGE"
    SKIPPED_FLAG_REQUIRED = "SKIPPED_FLAG_REQUIRED"
    SKIPPED_UNAVAILABLE = "SKIPPED_UNAVAILABLE"
    SKIPPED_HARD_JSON_LITE = "SKIPPED_HARD_JSON_LITE"
    SKIPPED_NO_VISION = "SKIPPED_NO_VISION"


class RouteDecision(BaseModel):
    # "ok": a target was selected, safe to call execute().
    # "unsupported": has_image=true but no vision_ok target exists in any tier
    #   (a config gap, not a transient outage).
    # "unavailable": every target that could otherwise match was skipped for
    #   availability (missing key / unreachable host) — may be transient.
    status: Literal["ok", "unsupported", "unavailable"]
    tier: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    reason_codes: list[ReasonCode] = Field(default_factory=list)
    fallback_chain: list[str] = Field(default_factory=list)  # "provider:model" strings


class UsageRecord(BaseModel):
    in_tokens: int = 0
    out_tokens: int = 0
    approximate: bool = False  # True when estimated by tiktoken, not provider-reported


class AttemptRecord(BaseModel):
    provider: str
    model: str
    ok: bool
    error: Optional[str] = None
    latency_ms: float = 0.0


class GatewayResponse(BaseModel):
    text: str = ""
    tier_used: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    attempts: list[AttemptRecord] = Field(default_factory=list)
    usage: Optional[UsageRecord] = None
    ok: bool = False
    error: Optional[str] = None
