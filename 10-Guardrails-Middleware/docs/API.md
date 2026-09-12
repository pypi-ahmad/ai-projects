# API

FastAPI app (`src/guardrails/api.py`), meant for `127.0.0.1` only — see `run.cmd` and the
`__main__` block at the bottom of `api.py`, both bind loopback explicitly. Backed by one shared
`Guard`: `PiiDetector` + `InputRulesDetector` + `LlmClassifierDetector` on input,
`PiiDetector` + `OutputRulesDetector` on output. The classifier is config-gated
(`config/classifier.yaml`) and off by default, same as everywhere else.

## `POST /v1/check_input`

Request: `{"text": "...", "policy": "standard"}` (`policy` optional, defaults to `"standard"`).
Response: a `GuardDecision` — `action`, `findings`, `text_in`, `text_out`, `policy`,
`latency_ms`. Always `200` — this endpoint *reports* what would happen, it doesn't enforce
anything itself.

## `POST /v1/check_output`

Same request/response shape as `check_input`, run through the output pipeline instead.

## `POST /v1/wrap_chat`

Request: `{"messages": [{"role": "...", "content": "..."}, ...], "policy": "standard"}`. Checks
the *last* `user` message:

- **Blocked** → `400`, body `{"detail": {"error": "GUARD_BLOCK", "findings": [...]}}`. The
  configured provider (`_PROVIDER`, `EchoProvider` by default — swap it for a real client) is
  never called.
- **Allowed or transformed** → the (possibly redacted) messages go to the provider, its reply
  runs through `check_output`, and the response is
  `{"reply": "...", "input_decision": {...}, "output_decision": {...}}`.

This is the HTTP mirror of the library's `Guard.wrap_call` context manager (see
`docs/ARCHITECTURE.md`).

## Isolation

`GuardDecision.text_in` (the raw, pre-redaction input) is never written anywhere by this module.
The optional JSONL log (`GUARDRAILS_LOG_FINDINGS=1`, appended to `data/logs/findings.jsonl`, off
by default) excludes it explicitly — every record is `decision.model_dump(exclude={"text_in"})`
plus a timestamp and direction. See `docs/phase-6-http-and-ui.md` for what's verified about this.
