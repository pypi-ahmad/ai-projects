# Runbook

## Start

```powershell
uv sync --group dev
uv run uvicorn guardrails.api:app --host 127.0.0.1 --port 8000
uv run streamlit run src/guardrails/ui.py
```

Or `run.cmd`, which runs `uv sync --group dev` then starts both of the above, each in its own
`cmd` window via `start`. There is no separate "stop" script.

## Stop

Close the window (or `Ctrl+C` inside it) for whichever process you started. On Windows, a
process started via `uv run uvicorn ...` or `uv run streamlit ...` spawns a child process tree;
if you backgrounded it in a way where the parent shell's own stop/kill doesn't reach the actual
listener, find the real PID with `netstat -ano | findstr <port>` and stop that PID directly
(`taskkill /PID <pid> /F /T`). This was observed directly while verifying this repo: killing the
shell job that launched `uv run streamlit`/`uv run uvicorn` left the server itself still
listening until the actual PID was killed.

## Logs

There is no application log file by default. The only file the application writes is
`data/logs/findings.jsonl`, and only when the `GUARDRAILS_LOG_FINDINGS` environment variable is
set to `1`, `true`, or `yes` (case-insensitive); see README and `docs/TECHNICAL.md`. Each line
is one JSON record: a `GuardDecision` (`action`, `findings`, `text_out`, `policy`, `latency_ms`)
plus `timestamp` and `direction`, with `text_in` always removed. If that variable isn't set, the
`data/logs/` directory may not exist at all.

Console/process output (uvicorn's and Streamlit's own stdout/stderr in their respective windows)
is the only other place to look; neither is configured to write to a file.

## Common failures (inferred from error strings and messages in the code)

- **HTTP `400` with body `{"detail": {"error": "GUARD_BLOCK", "findings": [...]}}`** from
  `POST /v1/wrap_chat`; the last `user` message was blocked by a detector (`api.py`). This is
  expected behavior, not a bug: the configured provider was never called. Check `findings` in
  the response body for which detector fired.
- **A `Finding` with `message: "detector_error"`** anywhere in a response; some detector raised
  an exception during `Pipeline.run()` (`pipeline.py`). Whether the overall `action` is
  `"block"` or the run continued depends on `fail_mode` (`"closed"` blocks, `"open"` continues).
- **A `Finding` with `message: "classifier_unavailable"`**; the LLM classifier is enabled
  (`config/classifier.yaml`'s `use_llm_classifier: true`) but its health check failed (Ollama not
  reachable at the configured `host`, default `http://localhost:11434`), and
  `require_classifier` is `false`, so this was treated as a soft skip, not a failure.
- **`RuntimeError: llm classifier required but unavailable`**; same as above, but
  `require_classifier: true`, so it was raised instead of soft-skipped, and now goes through the
  `fail_mode` path above.
- **`ValueError: classifier returned unparseable JSON after one repair attempt`**; the Ollama
  model's response didn't parse as the expected `{injection, exfil, benign}` JSON shape even
  after one retry with a repair prompt (`providers.py`, `OllamaClassifier.classify`). Also goes
  through the `fail_mode` path.
- **Streamlit or uvicorn fails to bind its port**; something else is already listening. For
  Streamlit this was observed directly as the log line `Port <N> is not available` while
  verifying this repo; the fix is to free the port or use a different one
  (`--server.port`/`.streamlit/config.toml` for Streamlit, `--port` for uvicorn).
