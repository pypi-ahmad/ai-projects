# Metrics

Two related but distinct shapes exist. Both come from `StreamSession`; they
just serialize different subsets of it for different consumers.

## `logs/streams.jsonl`; one row per finished session

Written once by `stream.api._produce()` when generation ends (success or
`provider_error`); see [API.md](API.md#session-lifecycle). Field names here
are exactly what `_log_session()` writes; this table is generated from
reading that function, not the other way around:

| Field | Meaning |
|---|---|
| `session_id` | The session's id, same as in `sse_url`. |
| `provider` | What was requested at `/v1/stream/start` (`fake`, `ollama`, `openai_compatible`, `agnes`, `gemini`). |
| `model` | Same, the requested model string. |
| `ttft_ms` | Milliseconds from stream start to the first `token` event; `null` if none ever arrived. `StreamSession.append()` stamps `t_first` on its first call. |
| `tokens` | Count of `token` events emitted; chunk count, not true LLM token count (providers chunk differently: word, subword, or arbitrary byte ranges), never presented as a tokenizer-accurate figure. |
| `reconnects` | `StreamSession.connect_count - 1`, floored at 0; how many times `GET /v1/stream/{id}` was called beyond the first read. |
| `dropped` | `StreamSession.dropped_count`; events evicted or discarded before a slow/reconnecting client read them, from four paths: `max_events` overflow, `ttl_s` expiry, and `pump()`'s two backpressure fallbacks (drop-newest, drop-oldest). Tokens merely delayed by a *paused* pump are queued, not dropped, and don't count here. |
| `ok` | `done_reason == "complete"`; `false` if the stream ended via `session.fail(...)` instead. |

## `GET /v1/metrics/{session_id}`; live, in-process

A smaller, different shape; no `session_id`/`provider`/`model` (the id is
already in the URL; provider/model aren't tracked on `StreamSession` itself,
only at the API layer), and `done_reason` instead of the derived `ok`
boolean:

```json
{"ttft_ms": 51.2, "tokens": 5, "done_reason": "complete"}
```

Same `ttft_ms`/`tokens` as above; `done_reason` is the raw string
(`"complete"` or whatever code `fail()` was given) rather than the JSONL
row's collapsed `ok` boolean. Callable before the stream is `done`; it just
reports whatever's accumulated so far, `done_reason: null` included.

## Not tracked anywhere, yet

`duration_ms` (wall-clock stream start → `done`/`error`) isn't computed by
either shape above; noted here so it doesn't look like an oversight in the
table rather than a known gap.

## `stream.metrics` is a different, unused-in-production layer

`stream.metrics.time_stream()`/`ttft_s()` (phase 1) time a provider
adapter's raw `TokenChunk` iterator. Nothing in `stream.api` uses it ;
`StreamSession`'s own `t_first`/`ttft_ms` is what actually feeds both
shapes above.

## A reasoning model changes what TTFT means

`qwen3.5:0.8b` (Ollama) streams a chain-of-thought through a separate
`message.thinking` field before `message.content` ever starts; confirmed
live via `stream.bench`, which first reported 14-43s TTFTs for it.
`stream.providers.ollama` only ever turns `content` into tokens, so that
14-43s was TTFT-including-reasoning-time, not a bug. Pass `think=False`
(the adapter's default is `None` = let the model decide; `stream.bench
--provider ollama` defaults to `False`) to measure TTFT-to-answer instead ;
with it, the same model reports p50 ≈ 51ms, p95 ≈ 359ms over 5 runs on this
machine's RTX 4060. Neither number is "the" TTFT; which one matters depends
on whether your UI shows the reasoning trace to the user.
