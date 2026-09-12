# Evaluation

Both are covered now that every store is real -- no longer stubs.

## 1. Planted-fact recall

Plant a known fact directly into semantic memory. Run `recall(query)` with
a query that should match it. Pass: the planted fact appears in the
result set.

Covered by: `tests/test_semantic.py::test_paraphrase_retrieves_fact` (a
single planted fact, a paraphrased query, real embeddings) and
`scripts/seed_demo.py` end-to-end (12 turns → overflow → distill → a
planted codename recalled across all three stores, including after a real
process restart via `--recall-only`).

## 2. Working overflow never exceeds the token cap

Feed items into working memory past its configured token budget. After
every insert, measure the buffer's token count. Pass: it never exceeds the
cap -- overflow always leaves via `compress.py`, it never silently
accumulates past the limit.

Covered by: `tests/test_working.py::test_cap_honored` (working memory's
own cap) and `tests/test_recall.py::test_token_budget_never_exceeded`
(recall's separate, caller-supplied `token_budget`, not the same cap).
