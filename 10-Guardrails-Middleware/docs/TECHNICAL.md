# Technical notes

## Stack

From `pyproject.toml` and import statements in `src/guardrails/`:

- **Python 3.13+**, **`uv`** for environment/dependency management and as the build backend
  (`[build-system] requires = ["uv_build>=0.12.13,<0.13"]`). No `setup.py`, no `poetry.lock`, no
  `requirements.in` — `uv.lock` is the resolved dependency source; `requirements.txt` is a
  generated export of it (see README).
- **Pydantic** (`models.py`, `providers.py`) — every core type (`Span`, `Finding`,
  `GuardContext`, `GuardDecision`, `ClassifierResult`) is a `pydantic.BaseModel`. This is why
  `providers.py`'s `ClassifierResult` can declare `injection: float = Field(ge=0, le=1)` and get
  validation for free, and why `api.py` can pass `GuardDecision` straight through as a FastAPI
  `response_model` without a separate serialization layer.
- **FastAPI** + **uvicorn** (`api.py`) — the HTTP layer. Request bodies (`CheckRequest`,
  `WrapChatRequest`) are themselves pydantic models, matching the rest of the codebase.
- **Streamlit** (`ui.py`) — the manual test console. `.streamlit/config.toml` sets its port and
  theme; nothing in `ui.py` itself sets the port.
- **PyYAML** — `pii.py`, `rules.py`, `providers.py` each call `yaml.safe_load` in their own
  `load_*_config` function to read the corresponding `config/*.yaml` file.
- **pytest** for tests; **ruff** (lint + format) and **ty** for type checking, both configured
  under `[tool.ruff]`/`[tool.ty]` in `pyproject.toml`.

## Invariants

Stated here because they're enforced by the type shapes themselves, not just by convention:

- **A `Span` cannot carry raw matched text.** Its pydantic fields are `start`, `end`, `type`,
  `score`, `replacement` (`models.py`) — there is no field for the original matched substring.
  `pii.py`'s and `rules.py`'s module docstrings call this out explicitly as what keeps findings
  "safe to log."
- **`GuardDecision.text_in` is the one field that can hold raw, pre-redaction text.** `api.py`'s
  `_log_finding` writes `decision.model_dump(exclude={"text_in"})` — verified by reading the
  function; this is the only place in `src/` that serializes a `GuardDecision` to disk.
- **First block wins.** `Pipeline.run()` (`pipeline.py`) iterates detectors in list order and
  `break`s the loop the moment a finding's `severity == "block"` and the active policy isn't
  `"observe"`. Detectors after that point never run for that call.
- **Detector order determines what later detectors see.** Each detector's `Finding.spans` (with
  a `replacement` set) get applied to the working text via `apply_spans` before the next
  detector runs (`pipeline.py`). Both `api.py` and `ui.py` put `PiiDetector` first in every
  detector list they construct.

## Error handling

- **Any detector exception is caught in `Pipeline.run()`** (`except Exception`, `pipeline.py`,
  annotated `# noqa: BLE001` acknowledging the broad catch is deliberate). What happens next
  depends on `GuardContext.fail_mode`: `"closed"` records a `detector_error` finding at
  `severity="block"` and stops the pipeline immediately; `"open"` records the same finding at
  `severity="warn"` and continues to the next detector.
- **`api.py`'s `/v1/wrap_chat`** catches `GuardBlocked` specifically (not detector exceptions —
  those already became a `GuardDecision` with `action="block"` inside `check_input`, which
  `wrap_call` turns into a raised `GuardBlocked`) and raises a FastAPI `HTTPException(400,
  detail={"error": "GUARD_BLOCK", "findings": [...]})`. FastAPI serializes any `HTTPException`'s
  `detail` argument under a `"detail"` key, so the actual response body is
  `{"detail": {"error": "GUARD_BLOCK", "findings": [...]}}` — see `docs/RUNBOOK.md` for the
  exact shape as a caller would see it.
- **`providers.py`'s `OllamaClassifier.classify()`** raises a plain `ValueError` if the model's
  response still doesn't parse as JSON after one repair attempt. **`LlmClassifierDetector.run()`**
  raises a plain `RuntimeError` if `config["require_classifier"]` is true and the provider's
  health check fails. Both exceptions are ordinary Python exceptions with no custom type — they
  propagate up to `Pipeline.run()`'s catch-all above, where `fail_mode` takes over.

## Persistence

Confirmed by grepping `src/` for file-write calls (`.open(`, `.write(`, `.write_text(`): the only
one is `api.py`'s `_log_finding`, writing to `data/logs/findings.jsonl` when
`GUARDRAILS_LOG_FINDINGS` is truthy. Nothing else in `src/guardrails/` writes to disk — no
database, no cache file, no other log file. The directory is created on first write
(`_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)`); it does not exist until then.
