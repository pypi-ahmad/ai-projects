# Sol resolution comparison: September 23, 2026

This file records the September 23 resolution experiment. The current runtime
prompt has changed since the run, but the rendering decision remains in the code.

Decision: retain 200-DPI PDF rendering capped at a 1,600-pixel long edge.
The 300-DPI, 3,200-pixel candidate failed the agreed no-regression gate.
This five-page comparison does not establish that higher-resolution input is
worse for every document.

## Run and limits

- Requested and provider-returned model: `gpt-6-sol` on all ten requests.
- Five approved pages, once per profile; the previously filtered BadgeCare page
  was excluded. All ten requests parsed successfully. No retries or fallback.
- Identical runtime prompt, strict schema, medium reasoning, and automatic image
  detail; only PDF DPI and image cap changed. Completion cap: 8,192 tokens.
- Sequential requests; ten-request limit; $2 estimated budget with a $0.20
  reservation before each next call. Unknown usage stops the evaluation.
- Reported-token cost estimate: **$0.40962**. This is an estimate, not a
  provider billing statement.
  Baseline: $0.16993; candidate: $0.23969. Elapsed: 255.31 seconds.
- Private outputs, rendered inputs, prompt snapshot, diagnostics, usage, and
  hashes: `data/parse/sol-resolution-20260923-031358/manifest.json` and adjacent
  per-page files. This directory is gitignored.

## Reference-token F1

| Document | Page | 1,600 pixels | 3,200 pixels |
| --- | ---: | ---: | ---: |
| Masked_Amerigroup_RealSolutions_1 | 1 | 100.00% | 100.00% |
| Masked_Amerigroup_RealSolutions_1 | 2 | 98.92% | 98.04% |
| Masked_Amerigroup_RealSolutions_2 | 1 | 94.13% | 91.60% |
| Masked Amerigroup_1 | 1 | 88.99% | 88.99% |
| Masked Amerigroup_1 | 2 | 95.79% | 96.48% |
| Unweighted mean | | **95.57%** | **95.02%** |

Two pages regressed, two tied, and one improved. The candidate failed
the per-page no-regression requirement and the aggregate-improvement
requirement, so it was not promoted. Visual source review was not performed after
the metric gate failed. The results do not establish verified field-level OCR
improvement. Token F1 does not establish correct identifiers, checkbox states,
reading order, or table associations.

Any future promotion also requires visual confirmation of at least one genuine
correction with no new source errors. More live experiments need separate
authorization; this run exhausted the approved ten requests.

## Verification and research

The offline suite covers the request cap, budget reservation, unknown-usage
stop, refusal handling, actual SDK retry/output settings, and promotion gate.
A saved-response replay of the first document's approved pages 1-2 verified
the full graph's Markdown, parse JSON, annotated PDF, two page PNGs, usage, and
progress events with **zero additional API calls**. UI behavior was tested with
Streamlit AppTest, not a manual browser session; clipboard JavaScript was not
browser-tested.

OpenAI recommends enlarging small text, which motivated this controlled comparison.
Its current vision sizing table does not establish Sol-specific `original`
behavior, so the comparison kept automatic detail. See the
[vision guide](https://developers.openai.com/api/docs/guides/images-vision).
Task-specific evaluation and source review are still needed alongside scores; see
[evaluation guidance](https://developers.openai.com/api/docs/guides/evaluation-best-practices).

The UI changes use [dynamic tabs](https://docs.streamlit.io/develop/api-reference/layout/st.tabs)
to defer hidden previews and keep page-progress updates on the script thread,
following [Streamlit's threading guidance](https://docs.streamlit.io/develop/concepts/design/multithreading).
Pricing follows the [Sol model page](https://developers.openai.com/api/docs/models/gpt-6-sol).

## Reproduction

Offline checks:

```powershell
uv run --no-project --python .venv\Scripts\python.exe python -X utf8 -m pytest -q
```

After authorizing a new paid comparison, choose a fresh output directory:

```powershell
uv run --no-project --python .venv\Scripts\python.exe python -X utf8 -m scripts.evaluate_resolution --live --output data/parse/sol-resolution-NEW
```

The evaluator requires the existing allowlisted PDFs and reference files at
the paths configured in `scripts/evaluate_prompts.py`. It does not overwrite
existing output directories, inject reference text into prompts, or change the
normal OCR default automatically.
