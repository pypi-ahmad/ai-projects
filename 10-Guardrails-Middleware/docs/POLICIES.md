# Policies

Three named policies (`src/guardrails/policies.py` — `Policy` type, `DEFAULT_POLICY =
"standard"`). `Pipeline`/`Guard` (Phase 2) wire in the pipeline-level concern — whether a
`block`-severity finding actually blocks. *Which* severity a given category gets is a
detector-level, config-driven decision — `pii.py` hardcodes PII to `warn` (it's never worth
blocking a whole request over), `rules.py` reads severity per category from
`config/rules.yaml` (see `docs/phase-4-rules-engine.md`). `policies.py`'s `strict`/`standard`/
`observe` *names* aren't yet read by either detector module — there's no code path that swaps
`config/rules.yaml` based on the active `Policy` string. Getting real `strict`-vs-`standard`
behavior today means pointing `Guard`/`rules.py` at a different `config/rules.yaml` (e.g. one
where `blocklist` severity is `block` at "standard" and additionally `denied_topics` is `block`
at "strict") — the `Policy` type and this doc describe the intended shape; a later phase would
wire selecting a policy to actually swapping which config loads.

## `strict`

Intended: lower tolerance than `standard` — e.g. blocking on `denied_topics`/`leak_pattern`
output matches instead of just transforming, or blocking medium-confidence injection matches.
Not yet distinguished from `standard` in the shipped `config/rules.yaml`.

## `standard` (default)

What's actually shipped: `Pipeline`'s "first block finding wins" (see `docs/ARCHITECTURE.md`)
combined with `rules.py`'s default config — input categories (`max_chars`, `blocklist`,
`control_char`, `encoding_evasion`) at `severity="block"`, output categories (`leak_pattern`,
`denied_topics`) at `severity="warn"`. PII is always `severity="warn"` on both sides
(`pii.py`). Proven end-to-end in
`tests/test_rules.py::test_standard_policy_via_guard`.

The optional LLM classifier (`providers.py`, Phase 5) has its own two knobs, off by default and
independent of the `strict`/`standard`/`observe` names: `use_llm_classifier` (run it at all) and
`require_classifier` (whether "provider unreachable" counts as a detector failure at all).
`require_classifier=True` + provider down raises, and `fail_mode` — not `policy` — decides
block-vs-continue from there, same as any other detector crash. `require_classifier=False` +
provider down is not a failure: it returns an info-severity `classifier_unavailable` finding
regardless of `fail_mode`. See `docs/phase-5-llm-classifier.md`.

## `observe`

Never blocks. A `block`-severity finding is still recorded in `findings`, but the pipeline keeps
running every remaining detector and the decision's `action` never becomes `"block"`. For
rolling out detection in front of traffic before turning on enforcement.

Note: this is independent of `fail_mode`. A detector *crashing* still blocks under
`fail_mode="closed"` even when `policy="observe"` — that's an infrastructure safety net, not a
policy-controlled finding.
