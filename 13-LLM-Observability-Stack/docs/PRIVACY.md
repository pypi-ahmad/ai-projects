# Privacy

Redaction (sha256 hash + 120-char preview) is always computed. Full prompt
text is stored **only** when `OBS_STORE_PROMPTS=true` is set; off by
default. Response text has no separate redaction/store path yet (Phase 2
only implements `span.set_prompt`).

## Stored raw

- `trace_id`, `span_id`, `parent_id`, span `name`/`kind`
- `provider`, `model`
- `ts`, `start_ns`/`end_ns`, `latency_ms`
- `status`, `error` text (error messages are not treated as sensitive)
- `usage` (token counts, `cost_est`, `ttft_ms`)
- trace-level `attrs` (`route`, `tenant`, `prompt_name`, `prompt_version` ;
  set via `span.set_trace(...)`; none of these are prompt/response content)

## Stored hashed + preview always; full text opt-in

- prompt text → `attrs["prompt_hash"]` (sha256) + `attrs["prompt_preview"]`
  (first 120 characters); always
- `attrs["full_prompt"]`; only when the `OBS_STORE_PROMPTS` environment
  variable is set to `true` (case-insensitive); absent otherwise

## Never stored

- API keys, tokens, or any credential value (see `.env.example`; names
  only, no values are ever written to disk by this project)
