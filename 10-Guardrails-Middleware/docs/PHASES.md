# Phases

Guardrails Middleware ships in phases. Each phase is scoped, tested, and stopped on its own —
no phase reaches ahead into the next one's surface.

| Phase | Scope | Status |
|---|---|---|
| 1 | Project scaffold, docs, rules-only prototype (PII redaction, injection heuristics, a fixed two-detector pipeline with fail-open/closed) | done — superseded core, kept for its regex logic (see below) |
| 2 | Typed core: pydantic `Span`/`Finding`/`GuardContext`/`GuardDecision`, an ordered-detector `Pipeline`, and the `Guard` library facade (`check_input`/`check_output`). No regex pack — stub detectors only | done |
| 3 | PII redaction rebuilt on the typed core: config-driven per-type toggle (`config/pii.yaml`), stable per-request placeholders, email/phone(+IN)/credit-card/IPv4/API-key/Aadhaar-PAN("possible") detectors | done |
| 4 | Rules-only input/output filtering (`rules.py`): `max_chars`, config-driven blocklists, control-char, encoding-evasion re-check on input; leak-phrase and denied-topics blocklists on output. Config-driven severity. `PiiDetector`, `InputRulesDetector`, `OutputRulesDetector` registered with `Guard`, proving the "standard" policy end-to-end | done |
| 5 | Optional LLM classifier (`providers.py`), off by default: `LlmClassifierDetector` (Ollama `qwen3.5:0.8b`, `{injection,exfil,benign}` scores via pydantic, one JSON-repair attempt, block above threshold) and `EmbeddingSimilarityDetector` (cosine vs. 10 fixed reference phrases, plain Python, no vector DB). Both registrable with `Guard` | done |
| 6 | HTTP surface (`api.py`, FastAPI, 127.0.0.1) — `/v1/check_input`, `/v1/check_output`, `/v1/wrap_chat` (400 `GUARD_BLOCK` on a blocked last user message, provider never called). Library `Guard.wrap_call` context manager. Streamlit playground (`ui.py`). `run.cmd` starts both in separate windows. Optional redacted-only JSONL log, `text_in` always excluded | done |
| 7 | Docs-match-code audit (`API.md`, `DETECTORS.md`, `PII.md`, `POLICIES.md`, `THREAT_NOTES.md`), pinned `requirements.txt`, a 10-line `wrap_call` README example, explicit false-positive/non-certification disclaimer, Streamlit port `7014` + dark theme (`.streamlit/config.toml`). No behavior changes — all 88 tests already passed going in | done |

Phase 2 replaced Phase 1's `GuardrailsPipeline` (dataclass-based) with `Guard`/`Pipeline`
(pydantic-based) as the library surface — see `docs/phase-2-guard-pipeline.md`. Phase 3 rebuilt
`pii.py` on that typed core (pydantic `Span`/`Finding`) — see `docs/phase-3-pii-redaction.md`.
Phase 4 built a second, independent detector family (`rules.py`) and wired *both* `pii.py` and
`rules.py` into `Guard` — see `docs/phase-4-rules-engine.md`. Phase 5 added a third, fully
optional detector family for ambiguous cases the first two families' regexes miss — see
`docs/phase-5-llm-classifier.md`. Phase 6 put all of it behind an HTTP surface and a Streamlit
UI, and added `Guard.wrap_call` to the library itself — see `docs/phase-6-http-and-ui.md`.
`detectors.py` (Phase 1's dataclass-based injection regex) is still untouched, still not on the
typed core, still not wired into `Guard` or the API; its categories still substantially overlap
with `rules.py`'s config-driven blocklists, so its future (retire vs. keep as a second opinion)
remains an open question. Phase 7 touched no detector logic — it caught two places where the
docs had drifted from the code (see `docs/phase-7-polish.md`) and made deployment/demo
polish (pinned deps, a fixed Streamlit port/theme, a tighter README example).

## Constraints that apply across every phase

- Native Windows 11. No WSL2, no Docker.
- CPU-first. The RTX 4060 is only ever touched by Phase 5's optional classifier/embedding lane,
  one Ollama model loaded at a time, and only when explicitly enabled — off by default.
- Non-goals: full auth product, multi-tenant billing, training a safety model, publishing a
  jailbreak corpus.
- Detectors are defensive pattern-matches, not an attack cookbook. Phase 5's embedding-lane
  reference set is 10 fixed generic phrases, not a growing dataset.
- No persistent store of raw input, anywhere (Phase 6) — see `docs/API.md`.

See `docs/phase-1-core-detectors.md`, `docs/phase-2-guard-pipeline.md`,
`docs/phase-3-pii-redaction.md`, `docs/phase-4-rules-engine.md`, `docs/phase-5-llm-classifier.md`,
`docs/phase-6-http-and-ui.md`, and `docs/phase-7-polish.md` for what each phase actually built.
