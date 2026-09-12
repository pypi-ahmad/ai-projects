# Threat notes; what this layer does not catch

Rules-based detection is pattern-matching, not understanding. This is a best-effort
defense-in-depth layer with known, real false-positive and false-negative rates; **it is not a
compliance certification** (GDPR, HIPAA, PCI-DSS, DPDP, or otherwise) and must not be presented
as one. Known gaps:

- **Paraphrased injection.** Any instruction-override or exfiltration request that doesn't match
  a known phrasing in `docs/DETECTORS.md`'s blocklists (or Phase 1's `detectors.py` regexes)
  slips through. This is the gap the optional LLM classifier (Phase 5, off by default) targets
  for ambiguous cases; but it's a small local model with its own false-positive/negative rate,
  not a guarantee, and does nothing when disabled.
- **Multi-turn / slow-drip attacks.** Each `check_input()` call sees one message in isolation;
  an attack spread across several benign-looking turns isn't detected.
- **Obfuscated payloads, partially.** `rules.py`'s `encoding_evasion` (Phase 4) catches fullwidth
  Latin letters and a handful of common Cyrillic/Greek lookalikes via NFKC + a small homoglyph
  table; not zero-width characters, less-common homoglyphs, RTL override tricks, other scripts,
  or translation-based injection. See `docs/DETECTORS.md`'s "Encoding evasion; limits".
- **Freeform PII.** Names, physical addresses, and other entities that need NER rather than a
  structural regex are not detected (see `docs/PII.md`).
- **Output-side leaks beyond known phrasings.** `rules.py`'s `blocklist_leak_phrases` (Phase 4)
  catches output that matches its short, generic phrase list (e.g. "here is your system
  prompt"); not a system prompt leaked in different words, or any leak that isn't a recognized
  PII or leak-phrase pattern.

## What this layer is not

- Not a substitute for model-level safety training or RLHF; it's a defense-in-depth filter in
  front of and behind the call, not a property of the model itself.
- Not a network-layer control (WAF, rate limiter, auth). Those are separate concerns.
- Not a jailbreak-technique reference; this repo documents detector *categories*, never
  working attack payloads (see the non-goals in `docs/DETECTORS.md` and `docs/PHASES.md`).
