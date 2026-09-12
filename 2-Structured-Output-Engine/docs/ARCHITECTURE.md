# Architecture

The real, connected flow is `engine.pipeline.Pipeline.run(text, schema)`
(`src/engine/pipeline.py`, Phase 4); text in, a real `Provider.complete()`
call, `StructuredResult` out. (An earlier `StructuredOutputEngine`,
`src/engine/core.py`, Phase 1, called an older, narrower provider interface
and was never connected to a real provider; deleted in Phase 8; `Pipeline`
was always the real path.)

```mermaid
flowchart TD
    A["Input: text + Pydantic schema"] --> B["Build messages<br/>system rules + JSON Schema + 'one JSON object only'"]
    B --> C["provider.complete(messages, json_schema, temperature, max_tokens)"]
    C -->|ProviderError| PE["errors=[provider_error]"]
    C -->|reply text| D["extract_json(reply)<br/>whole reply / fenced block / first balanced {...}"]
    D -->|ParseError: nothing JSON-shaped found| PA["errors=[parse_error]"]
    D -->|candidate text| E["StructuredResult.from_raw_text(candidate, schema)"]
    E -->|ok=True| R["Result: ok=True, data, attempts, model, provider, latency_ms"]
    E -->|ok=False| F
    PE --> F
    PA --> F
    F{"attempt < max_attempts?<br/>(default 3)"}
    F -->|attempt 2: retry| G["Same provider/model, lower temperature,<br/>validator errors fed back"]
    G --> C
    F -->|attempt 3+: repair| H["Switch to repair_model<br/>(default: local Ollama qwen3.5:0.8b,<br/>even if attempt 1 used a different provider —<br/>unless pin_provider=True)"]
    H --> C
    F -->|no, exhausted| I{"fallback="}
    I -->|partial, default| J["build_partial: keep validated fields,<br/>default non-required missing ones,<br/>required-missing stays in errors"]
    I -->|empty| K["data=None, errors kept"]
    I -->|raise| L["raise PipelineFailure<br/>(caught at the CLI's top level, --strict)"]
    J --> X["Result: ok=False, data=partial model or dict, errors=[...]"]
    K --> X
```

Every attempt; success or failure, including a `ProviderError`; is logged
(`logging.info`: attempt, stage, provider, model, ok, latency_ms, error
types, a raw-reply snippet).

## Notes

- **A provider error consumes an attempt, like a validation failure does.**
  It doesn't short-circuit immediately (the deleted Phase 1
  `StructuredOutputEngine` did); the point is that if the *initial*
  provider is down, attempt 3's switch to the (different, by default)
  repair provider can still succeed.
- **A repair-stage provider switch unloads the outgoing model first**
  (`old_provider.unload(old_model)`, best-effort, Phase 8); skipped when
  the provider has no `unload` or `pin_provider=True` keeps the same one.
  See `docs/RUNBOOK.md` "VRAM unload order".
- **Extraction is lenient by design.** `extract_json` returns the best
  candidate substring it can find even if it's still syntactically broken.
  That is what `StructuredResult.from_raw_text`'s own JSON/schema validation
  is for. `ParseError` (→ `errors=[type="parse_error"]`) only fires when
  none of the three strategies find anything resembling a JSON object at
  all (e.g. a plain-prose refusal).
- **`fallback="partial"` never returns `ok=True`.** Even when the
  reconstructed data happens to satisfy the schema fully (e.g. the only
  problem was a field with a usable default), the result still reports
  `ok=False`; a fabricated/defaulted field was involved, so it's not the
  same guarantee as a model's own valid output.

## History: `StructuredOutputEngine` (Phase 1, deleted Phase 8)

`src/engine/core.py`'s `run()` predated the `complete()` provider interface
(Phase 3) and expected an older `generate(*, model, prompt, schema) -> str`
shape that nothing ever implemented, so it never played a role in a real
run; `Pipeline` above was always the connected path. Deleted in Phase 8
along with its test (`tests/test_engine.py`).
