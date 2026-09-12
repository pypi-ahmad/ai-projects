# Technical Reference

## Provider adapters

Every backend implements the `Provider` protocol (`src/providers/base.py`):

```python
class Provider(Protocol):
    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        json_schema: dict | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> ProviderResponse: ...
```

Chat-style messages in, `ProviderResponse(text, model, raw)` out; `text` is
raw (expected-JSON-if-`json_schema`-was-passed) text, not yet validated
against anything. All four adapters call their backend directly over
`httpx` (no vendor SDKs) so requests are mockable in tests without live API
keys (`tests/test_providers.py`). `complete()` must raise `ProviderError`
(never a bare httpx exception) on failure; see Error handling below.

> **Wired to `engine.pipeline.Pipeline` (Phase 4).**
> An earlier `StructuredOutputEngine` (Phase 1, `engine/core.py`) expected
> the older, narrower `generate(*, model, prompt, schema) -> str` shape and
> was never connected to a real provider; deleted in Phase 8. The real,
> current pipeline is `Pipeline` (`engine/pipeline.py`): it calls a
> provider's `complete()` directly and handles
> extraction/validation/retry/repair/fallback itself; see
> `docs/ARCHITECTURE.md`.

## Provider structured-output support (what's actually implemented)

| Provider | Endpoint | Structured-output mechanism | Fallback when unsupported |
|---|---|---|---|
| `OllamaProvider` | `POST {OLLAMA_HOST}/api/chat` | `format=<json schema>`; only on Ollama ≥0.5.0, detected via one cached `GET /api/version` call (structured `format` support was added at that version) | Below 0.5.0: schema embedded as a system-prompt instruction (`embed_schema_in_system_prompt`) |
| `OpenAICompatibleProvider` | `POST {OPENAI_BASE_URL}/chat/completions` | `response_format: {"type": "json_schema", "json_schema": {name, schema, strict: true}}`, always sent when a schema is given | None; assumed always supported for this provider |
| `AgnesProvider` (subclasses the above, `https://apihub.agnes-ai.com/v1`) | same endpoint shape | **Always prompt-embedded** | Their documented parameter list (verified directly against https://wiki.agnes-ai.com/en/docs/agnes-25-flash) has no `response_format`/`json_schema` field, so this is the only path, not a fallback from a failed attempt |
| `GeminiProvider` | `POST {base}/models/{model}:generateContent?key=...` against `generativelanguage.googleapis.com/v1beta` | `generationConfig.responseJsonSchema=<json schema>` + `responseMimeType: "application/json"`; accepts standard JSON Schema directly (verified against the `google-genai` SDK docs), no type-casing translation needed unlike the older `responseSchema` field | None; assumed always supported |

All four call their backend directly over `httpx` (no vendor SDKs), so requests are mockable in tests without live API keys (`tests/test_providers.py`). `unload(model)` (`OllamaProvider` only) posts `keep_alive=0` to `/api/generate` to free VRAM immediately (`docs/RUNBOOK.md`).

## Error handling

`ProviderError(code, message)` (`providers/base.py`); every adapter raises
this, never a bare `httpx` exception, so a caller can catch one exception
type and branch on a stable `code` instead of parsing a traceback:

| `code` | When |
|---|---|
| `missing_api_key` | Constructor: no API key (explicit or from the provider's env var); checked eagerly, before any HTTP call |
| `missing_base_url` | `OpenAICompatibleProvider` only: no base URL |
| `unauthorized` | HTTP 401/403 |
| `not_found` | HTTP 404 |
| `http_error` | Any other 4xx/5xx (after the retry below) |
| `timeout` | `httpx.TimeoutException` |
| `connection_error` | `httpx.ConnectError` |
| `unsupported_response` | `GeminiProvider` only: 200 response with an unexpected shape (missing `candidates[0].content.parts[0].text`) |

**Retries:** exactly 2 attempts, and only a first-attempt 5xx triggers the
second (`request_with_retry` in `providers/base.py`, shared by all four
adapters). A 4xx never retries. A timeout or connection error never
retries; it becomes a `ProviderError` on the first attempt.

## Result envelope

`src/engine/result.py` defines `StructuredResult`; the return type of
`engine.pipeline.Pipeline.run()` (Phase 4, the real and only path since the
disconnected Phase 1 `StructuredOutputEngine` was deleted in Phase 8):

```python
@dataclass(frozen=True)
class StructuredResult:
    ok: bool
    data: BaseModel | dict | None   # dict only from Pipeline's fallback="partial"
    errors: list[ValidationIssue]   # loc, msg, type — empty when ok=True
    raw_text: str
    attempts: int
    model: str | None
    provider: str | None
    latency_ms: float | None
```

`ok=False` never means an exception escaped; `errors` says exactly what
went wrong. A schema `ValidationError` becomes one `ValidationIssue` per
`ValidationError.errors()` entry; a provider exception (network, auth,
timeout) becomes a single `ValidationIssue(loc=(), type="provider_error")`;
`Pipeline` additionally uses `type="parse_error"` when no JSON object could
be found in a reply at all (see "Pipeline" below). Everything builds
results through the same `StructuredResult.from_raw_text` /
`from_provider_error` constructors, so there is one code path that decides
what "valid" means.

## Schema registry

`src/schemas/registry.py`; `SchemaRegistry`: `register(name, model,
example)`, `names()`, `get(name)`, `json_schema(name)`
(`model.model_json_schema()`), `example(name)`. The module-level `registry`
instance (`schemas.registry`) comes pre-populated with the four built-in
schemas; see `docs/SCHEMAS.md`.

## Pipeline (Phase 4)

`src/engine/pipeline.py`; `Pipeline.run(text, schema) -> StructuredResult`,
the component that actually connects a `Provider` to a schema. See
`docs/ARCHITECTURE.md` for the full attempt ladder (initial → retry →
repair → fallback) and `ROADMAP.md`'s Phase 4 entry for what's verified.
Key pieces, all in this one file:

- `extract_json(raw) -> str` / `ParseError`; three fallback strategies (whole reply, fenced block, first balanced `{...}` span via brace-counting that respects string literals) before giving up.
- `build_partial(raw_text, schema) -> (BaseModel | dict, list[ValidationIssue])`; the `fallback="partial"` reconstruction: per-field `TypeAdapter(field.annotation).validate_python(...)`, schema defaults for non-required fields, truly-required-and-missing stays an error.
- `Pipeline` (a dataclass); `provider`, `model`, `repair_provider`/`repair_model` (default: lazily-constructed local `OllamaProvider("qwen3.5:0.8b")`), `pin_provider` (repair with the same provider/model instead of switching), `max_attempts`, `fallback`, `temperature`/`repair_temperature`, `max_tokens`.

## Pydantic v2

- **Schema export:** `schema.model_json_schema()`; called once per `run()`
  and passed to the provider as `schema` on every generate/repair call.
- **Parse + validate in one step:** `schema.model_validate_json(raw)`.
  Raises `pydantic.ValidationError` for both malformed JSON and schema
  violations (missing fields, wrong types, enum mismatches, etc.); the
  engine catches only this exception type from validation.
- **Extra fields forbidden by default:** every built-in schema sets
  `model_config = ConfigDict(extra="forbid")`. A schema that should accept
  extra fields opts in explicitly with `extra="allow"` or `"ignore"`; the
  default is deliberately strict since these schemas describe what a model
  is allowed to hand back, not general-purpose data containers.
- `EmailStr` (used by `ContactRecord.email`) requires the `email` extra:
  `pydantic[email]`, which pulls in `email-validator`. Already added to
  `pyproject.toml`.
- No `instructor` or similar wrapper library; providers are heterogeneous
  enough (local + three hosted APIs) that a thin custom adapter per
  provider is simpler than forcing them through one function-calling
  abstraction.

## JSON Schema export caveats

Not yet handled; relevant once providers are wired to the engine:
- OpenAI's `strict: true` structured-output mode is stricter than plain
  JSON Schema (e.g. it wants `additionalProperties: false` on every object,
  which our schemas already set via `ConfigDict(extra="forbid")`; but it
  also disallows some `anyOf`/`oneOf` shapes `model_json_schema()` produces
  for `Optional[...]` fields). Not yet verified whether our four built-ins
  pass OpenAI's strict-mode validation as-is.
- Ollama's `format` and Gemini's `responseJsonSchema` both accept a JSON
  Schema dict directly (confirmed against current docs for each); no
  transformation needed for either.

## Extraction rules (`engine.pipeline.extract_json`)

Applied in order to a provider's raw reply text; the first that produces a
candidate wins; no further strategies run:

1. **Whole reply**; used as-is if it starts with `{` and ends with `}` after stripping whitespace.
2. **Fenced code block**; first ```` ```json ... ``` ```` or ```` ``` ... ``` ```` block (regex, `re.DOTALL`).
3. **First balanced `{...}` span**; a hand-rolled brace-counting scan from the first `{`, tracking whether it's inside a quoted string (so a `{` or `}` inside a JSON string value doesn't throw off the count). Not a naive `\{.*\}` regex, which would over-match past the first object's true end.

If none of the three find anything JSON-shaped at all (e.g. a plain-prose refusal), `extract_json` raises `ParseError` → `errors=[type="parse_error"]`. A candidate that *is* found but is still syntactically broken or schema-invalid is **not** rejected here; it's handed to `StructuredResult.from_raw_text`, whose `pydantic.ValidationError` handling reports the specific defect (see Result envelope above).

## Retry policy (what's actually implemented)

**`Pipeline` (`engine.pipeline`, the real, connected path):**

| Attempt | Provider / model | Temperature | On failure |
|---|---|---|---|
| 1 (initial) | `provider` / `model` (caller-supplied) | `temperature` (default `0.2`) | validator errors fed into attempt 2's messages |
| 2 (retry) | same `provider` / `model` | `repair_temperature` (default `0.0`) | validator errors fed into attempt 3's messages |
| 3+ (repair) | switches to `repair_provider`/`repair_model` (default: lazily-constructed local `OllamaProvider("qwen3.5:0.8b")`) unless `pin_provider=True`, which keeps attempt 1's provider/model | on exhausting `max_attempts` (default `3`), falls through to `fallback=` (`"partial"` default / `"empty"` / `"raise"` → `PipelineFailure`) |

A `ProviderError` during any attempt is treated exactly like a validation failure; it consumes an attempt and the ladder continues (a deliberate difference from the legacy engine below: this is what lets attempt 3's provider switch recover from an attempt-1 provider outage). No backoff between attempts.

**Provider HTTP layer (all four adapters, `providers/base.py`):**

| Setting | Current default |
|---|---|
| Per-call timeout | 30s (`DEFAULT_TIMEOUT_S`) |
| Retries | 2 attempts total, only on a first-attempt 5xx (see Error handling above) |
| Cross-provider fallback order | not implemented; a hard outage on both `provider` and `repair_provider` still ends in `ok=False` |

**History:** the deleted Phase 1 `StructuredOutputEngine` (`engine/core.py`,
removed Phase 8) did not retry on a provider error; it returned `ok=False`
immediately. `Pipeline`'s current behavior (a provider error consumes an
attempt like a validation failure) was a deliberate change from that, not
the original design.
