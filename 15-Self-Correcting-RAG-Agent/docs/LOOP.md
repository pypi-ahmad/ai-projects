# Self-correction loop

## Parameters (`agent.schemas.LoopPolicy`)

| Parameter | Default | Meaning |
|---|---|---|
| `max_iters` | `2` | Total retrieval attempts per query: 1 initial + 1 rewrite-retry. |
| `confidence_threshold` | `0.6` | The critique's `grounded` score (below) at or above which retrieval is treated as sufficient. |
| `web_enabled` | `False` | Whether web fallback may run. Only ever `True` if `SEARCH_API_KEY` was configured at startup; see `Settings.resolve_web_enabled()`, which force-disables this regardless of what was requested when the key is unset. |
| `citation_fail_closed` | `False` | `False`: strip an illegal `[S#]`/`[W#]` citation and lower confidence. `True`: abstain outright instead of returning a partially-cleaned answer. |

Values are tunable, not hardcoded law; change them if evaluation shows a better setting.

## Critique score (`agent.schemas.CritiqueResult`)

The critique model's response is validated against this schema:

```json
{"grounded": <0.0-1.0>, "coverage": <0.0-1.0>, "missing": ["..."], "decision": "answer"|"retry"|"web"|"abstain", "rationale": "..."}
```

`grounded` estimates whether the retrieved chunks support a correct answer to the
(rewritten) query; not answer quality, and never derived from the generator's own
certainty, which would conflate "retrieval found it" with "the model feels confident," the
exact failure mode this agent exists to avoid. `coverage` is a separate signal: how much of
the query's information need the context addresses, independent of whether it's grounded.
`missing` feeds back into the next `rewrite()` call as hints on a retry.

The model's own `decision` is a recommendation only, not the source of truth; see below.

## Decision table (`agent.critique.enforce_decision`)

Define `grounded_ok` = `grounded >= confidence_threshold` **and** at least one chunk was
retrieved (a high score with zero chunks is not sufficient).

| `grounded_ok` | Retries left (`iteration < max_iters`) | `web_enabled` | Decision |
|---|---|---|---|
| true | any | any | `answer` |
| false | true | any | `retry` |
| false | false | true | `web` |
| false | false | false | `abstain` |

`enforce_decision` recomputes this table in code from the critique's scores and the policy,
every time; it does not trust the model's proposed `decision`. When they disagree, code
overrides the model and appends why to `rationale` (visible in the trace and the UI), e.g.
`"overrode model's decision 'answer' -> 'retry' (grounded=0.42, threshold=0.6, ...)"`.

## Abstain reasons

There is no single fixed abstain string. Depending on where the loop stops:

- Critique reaches `abstain` -> the reason is the critique's own `rationale` (with the
  override note above appended, if code corrected the decision).
- Web fallback is disabled or has no `WebSearch`/`WebFetch` configured -> `"web fallback is
  disabled or unconfigured; corpus was insufficient"`.
- Web fallback ran but returned nothing usable -> `"web fallback returned no usable results;
  corpus was insufficient"`.
- Citation fail-closed triggered -> `"generated answer contained an unverifiable citation
  (fail-closed policy)"`.
- An unhandled error occurred (`agent.loop.run_safe`) -> `"internal error: <message>"`.

## When web fallback is legal

Only when `enforce_decision` reaches the `web` row above: retries exhausted, still not
grounded, and `policy.web_enabled` is `True`. `agent.loop.run()` independently re-checks
`policy.web_enabled` (and that both a `WebSearch` and a `WebFetch` were actually supplied)
before ever calling out, so a misbehaving or faked critique step cannot force a live web
call on its own.

**Web results are best-effort and untrusted.** A search or fetch failure is skipped, not
treated as a hard error (see `web/fetch.py`); a page that fails to fetch simply isn't cited.
Fetched text is never executed or followed as instructions; see `docs/THREAT_NOTES.md`.
