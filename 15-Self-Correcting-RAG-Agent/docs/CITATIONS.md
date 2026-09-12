# Citation tagging

Two tag families, never conflated:

- `[S#]` -- a chunk from the local corpus (Qdrant + BM25 hybrid retrieval). `S` = source.
- `[W#]` -- a result from the web fallback. `W` = web.

Numbering restarts at `1` per tag family per answer, in the order chunks/results were
retrieved (`[S1]`, `[S2]`, ... ; `[W1]`, `[W2]`, ...).

## Rules

1. Every factual sentence in the answer carries at least one tag. No tag -> the sentence is
   not a factual claim (e.g. "I don't have enough information to answer that").
2. `[S#]` and `[W#]` may both appear in one answer (corpus + web fallback ran), but never as
   an unlabeled blend -- a sentence sourced from the web must carry a `[W#]`, never borrow an
   `[S#]`'s label or go untagged because "the corpus almost said the same thing."
3. The answer never states corpus-only content as if it were web-verified, or vice versa. The
   tag is the reader's signal for how much to trust a claim; a wrong tag is worse than no tag.
4. Web citations must be evaluated by the same untrusted-input rules as retrieved corpus text
   -- see `docs/THREAT_NOTES.md`. A citation is a source pointer, not a license to repeat
   whatever the source page claims about itself.
5. If retrieval (corpus or web) came back empty or below the confidence threshold with no
   fallback available, the answer abstains per `docs/LOOP.md` instead of inventing a tag.

## What's actually code-checked (`agent.citations.check_citations`)

Only rule 1's converse, mechanically: every `[S#]`/`[W#]` tag in the generated text is
checked against the count of chunks actually supplied (`n_source`, `n_web`). A tag whose
number exceeds what was supplied is stripped (along with one preceding space) and reported
as an illegal citation, dropping answer confidence -- or the whole answer is replaced with an
abstain, if `LoopPolicy.citation_fail_closed` is set. This confirms a citation's *number*
is legitimate; it does not and cannot verify that a claim is *semantically* supported by the
chunk its tag points to -- rules 1-3 remain prompt-level instructions to the answer model
(`agent/generate.py`'s system prompt), not a code-enforced invariant.
