"""Model allowlist and provider verification state.

A provider's env key being present means "can attempt", not "verified".
`PROVIDERS` starts every provider disabled; each provider flips to
enabled=True only after its own phase runs a live smoke test against the
real API. Do not enable one on env-var presence alone.

Pure data/config -- must not read the environment or make network calls
itself (`stream.api` does both, using the names declared here). Next:
`stream.session` for what actually consumes `BackpressureConfig`, or
`stream.api` for where `PROVIDERS`/`PROVIDER_KEY_VARS` gate a request.
"""

from dataclasses import dataclass

# Exact allowed Ollama models. Do not stream any model outside this list.
OLLAMA_MODELS: tuple[str, ...] = (
    "granite4.1:3b",
    "qwen3.5:2b",
    "qwen3.5:0.8b",
    "qwen3-vl:2b",
    "qwen3-embedding:0.6b",
    "qwen3-embedding:4b",
    "translategemma:4b",
    "AuditAid/PaddleOCR-VL-1.6-0.9B",
)
OLLAMA_SMOKE_MODEL = "qwen3.5:0.8b"

OPENAI_COMPAT_MODELS: tuple[str, ...] = ("gpt-5.6-luna", "gpt-5.6-terra")
OPENAI_API_KEY_VAR = "OPENAI_API_KEY"
OPENAI_BASE_URL_VAR = "OPENAI_BASE_URL"

AGNES_MODELS: tuple[str, ...] = ("agnes-2.5-flash",)
AGNES_BASE_URL = "https://apihub.agnes-ai.com/v1"
# Catalogued env var name is AGNESAI_API_KEY (verified present). The user's
# shorthand "AGNES_API_KEY" is not a real variable in this environment.
AGNES_API_KEY_VAR = "AGNESAI_API_KEY"

GEMINI_MODELS: tuple[str, ...] = ("gemini-3.5-flash-lite", "gemini-3.7-flash")
GEMINI_API_KEY_VAR = "GOOGLE_API_KEY"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

# provider name -> allowed models, for /v1/stream/start request validation.
MODEL_ALLOWLIST: dict[str, tuple[str, ...]] = {
    "ollama": OLLAMA_MODELS,
    "openai_compatible": OPENAI_COMPAT_MODELS,
    "agnes": AGNES_MODELS,
    "gemini": GEMINI_MODELS,
}

# provider name -> env var that must be present to attempt it (None = no key
# needed, e.g. local Ollama). Checked live at /v1/stream/start time, not just
# baked into PROVIDERS.enabled -- see docs/API.md.
PROVIDER_KEY_VARS: dict[str, str | None] = {
    "ollama": None,
    "openai_compatible": OPENAI_API_KEY_VAR,
    "agnes": AGNES_API_KEY_VAR,
    "gemini": GEMINI_API_KEY_VAR,
}


@dataclass
class ProviderStatus:
    name: str
    enabled: bool
    reason: str


PROVIDERS: dict[str, ProviderStatus] = {
    "ollama": ProviderStatus(
        "ollama", enabled=True, reason="verified: live streamed reply + usage on qwen3.5:0.8b"
    ),
    "openai_compatible": ProviderStatus(
        "openai_compatible",
        enabled=True,
        reason="verified: live streamed reply + usage on gpt-5.6-luna",
    ),
    "agnes": ProviderStatus(
        "agnes", enabled=True, reason="verified: live streamed reply + usage on agnes-2.5-flash"
    ),
    "gemini": ProviderStatus(
        "gemini",
        enabled=False,
        reason=(
            "adapter built, request reaches the API, but GOOGLE_API_KEY was rejected "
            "(400 API_KEY_INVALID) -- could not verify streaming end-to-end"
        ),
    ),
}


@dataclass(frozen=True, slots=True)
class BackpressureConfig:
    """Watermarks + drop policy for `stream.session.pump`.

    `high_watermark`/`low_watermark` give hysteresis: pulling pauses once the
    buffer hits `high_watermark` and doesn't resume until it drains to the
    lower `low_watermark`, instead of flapping right at one threshold.
    """

    high_watermark: int = 64
    low_watermark: int = 16
    # Backpressure fallback for a provider we don't control the read loop of
    # (pump() called with can_pause=False) -- default drops the newest
    # incoming token rather than an already-buffered, still-replayable one.
    drop_oldest_replayable: bool = False
    poll_interval_s: float = 0.01
