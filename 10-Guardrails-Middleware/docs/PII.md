# PII entity types

Rules-based, regex + validation (`src/guardrails/pii.py`, pydantic `Span`/`Finding` from
`models.py`). A `Span` never carries the raw matched text; only `start`, `end`, `type`, `score`,
and a safe `replacement` placeholder; so `Finding`/`Span` objects, and anything logged from
them, are safe even before redaction is applied to the text itself. The API's optional findings
log (`src/guardrails/api.py`, `GUARDRAILS_LOG_FINDINGS=1`, see `docs/API.md`) relies on exactly
this invariant, plus explicitly excluding `GuardDecision.text_in`.

**False-positive risk and scope.** Every detector below is a regex/heuristic, not a certified PII
scanner. Expect both false positives (flagging non-PII) and false negatives (missing real PII in
an unanticipated format); see "Known false-positive risks" below and `docs/THREAT_NOTES.md`.
**This project is not a compliance certification** (GDPR, HIPAA, PCI-DSS, DPDP, or otherwise) and
must not be represented as one; treat it as a best-effort defense-in-depth layer, not a
legal/regulatory guarantee.

## Detected, on by default

| Type | Placeholder | Notes |
|---|---|---|
| `email` | `[EMAIL]` | Standard email pattern. |
| `phone` | `[PHONE]` | Generic pattern **and** an Indian mobile pattern (`+91`-optional, 10 digits starting 6 to 9). See false-positive risk below. |
| `credit_card` | `[CARD]` | 13 to 19 digit candidate, confirmed via Luhn check. |
| `ip_address` | `[IP]` | IPv4 only. |
| `api_key` | `[API_KEY]` | AWS access-key shape, `sk-`/`api_key-`/`secret-`-prefixed secrets, **and** a generic high-entropy-token heuristic (20+ alnum/`-`/`_` chars, no spaces, mixed letters+digits, Shannon entropy ≥ 3.0 bits/char) for tokens with no recognizable prefix. |

## Detected, off by default; "possible" only

| Type | Placeholder | Notes |
|---|---|---|
| `aadhaar_possible` | `[AADHAAR_POSSIBLE]` | 12-digit shape, first digit 2 to 9, optionally grouped 4-4-4. **Shape only; no checksum, no legal validation.** A match is not a confirmation of a real Aadhaar number. |
| `pan_possible` | `[PAN_POSSIBLE]` | 5 letters + 4 digits + 1 letter shape (e.g. `AAAPZ1234C`). **Shape only; no legal validation.** |

Both are opt-in via `config/pii.yaml` precisely because the shape-only match rate against
non-PII data is unknown and likely non-trivial; see `docs/THREAT_NOTES.md`.

## Stable placeholders

The same raw value maps to the same placeholder everywhere it appears in one `detect()`/
`redact()` call. When a type has more than one *distinct* value in the text, each gets a numeric
suffix in first-seen order (`[EMAIL_1]`, `[EMAIL_2]`, ...); a single distinct value stays as the
bare tag (`[EMAIL]`). This lets a downstream model still tell "the same email, twice" from "two
different emails" without ever seeing either raw value.

## Configuration

`config/pii.yaml` toggles each type on/off (`email`, `phone`, `credit_card`, `ip_address`,
`api_key`, `aadhaar`, `pan`). Resolution order: an explicit path argument, then
`$GUARDRAILS_PII_CONFIG`, then `config/pii.yaml` relative to the working directory. A missing
file or missing key falls back to the code default (`DEFAULT_PII_CONFIG` in `pii.py`).

`detect()`/`redact()` do **not** read this file automatically; they default to
`DEFAULT_PII_CONFIG` (no I/O) unless a `config` dict is passed in. To honor `config/pii.yaml`,
callers load it once and pass it through:

```python
config = pii.load_pii_config()
finding = pii.detect(text, config)
```

## Known false-positive risks

- **Phone.** Both patterns are shape-only. The generic pattern's optional country-code group
  means it can match *any* contiguous 10 to 13 digit run (order numbers, reference codes, even
  parts of a credit-card-shaped or Aadhaar-shaped number). The Indian mobile pattern matches any
  10-digit number starting 6 to 9, which is far broader than actual assigned mobile numbers.
- **`api_key` (high-entropy heuristic).** Long tokens, hashes, UUIDs without dashes, or
  base64-ish identifiers that aren't secrets can match; conversely a short or low-entropy secret
  won't.
- **Aadhaar/PAN.** See the "possible" caveat above; false positives against other 12-digit or
  5-letter+4-digit+1-letter identifiers are expected and undocumented in magnitude.

## Not covered (rules can't do this without NER)

Freeform names, physical addresses, IBANs, passport numbers; anything that needs semantic
entity recognition rather than a structural pattern. Out of scope for the default no-GPU path;
see `docs/THREAT_NOTES.md`.
