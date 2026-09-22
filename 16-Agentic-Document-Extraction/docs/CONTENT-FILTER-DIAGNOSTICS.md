# Content-filter diagnostics: September 12, 2026

The diagnostic fix is implemented. Five of six approved pages parsed; BadgeCare
page 1 returned `finish_reason=content_filter`. Capturing the raw response keeps
metadata that automatic structured parsing had discarded. The provider still
rejected the page.

## Live evidence

Artifacts: `data/parse/diagnostics-20260912/manifest.json`, separate per-page JSON
and rendered images, and an exact prompt snapshot. Earlier runs were preserved.

| Document | Page | Outcome | HTTP | Finish reason |
| --- | --- | --- | --- | --- |
| Masked BadgeCare Plus_1 | 1 | content_filtered | 200 | content_filter |
| Masked_Amerigroup_RealSolutions_1 | 1 | parsed | 200 | stop |
| Masked_Amerigroup_RealSolutions_1 | 2 | parsed | 200 | stop |
| Masked_Amerigroup_RealSolutions_2 | 1 | parsed | 200 | stop |
| Masked Amerigroup_1 | 1 | parsed | 200 | stop |
| Masked Amerigroup_1 | 2 | parsed | 200 | stop |

Only these pages were submitted, once each by the evaluator, with one image per
call and the actual SDK client's retries set to zero. Six distinct request IDs
were captured. This does not establish whether the gateway retries internally.
Model, temperature, reasoning setting, image rendering, and prompts were unchanged.
The layout prompt also matches the original baseline byte for byte.

BadgeCare evidence:

- Request ID: `req_bd16f3fb6b954ec8a7cbbedc6bf4182f`.
- Returned model: the pre-migration default, not the current `gpt-6-sol`.
- Reported tokens: 2,701 input, 2,216 output, 0 cached.
- No recognized prompt/completion filter annotations were returned.
- No rejected completion or refusal text was saved.

HTTP 200 with `content_filter` differs from a request-time HTTP 400 rejection.
The category and underlying reason are unknown. Provider review would need the
request ID and timestamp; no provider message was sent.

## Validation and limits

82 offline tests passed, including actual SDK calls against an HTTP mock,
strict-schema request compatibility, filtered/refused/truncated/malformed output,
HTTP errors, timeout sanitization, unknown usage, retry disabling, parallel page
isolation, all-failed JSON persistence, and Streamlit diagnostics/stale-output checks.
The UI was exercised through Streamlit AppTest, not a manual browser review.

GroundTruth scoring remains in the manifest. It measures reference-token overlap,
not semantic correctness. Two successful pages contained ragged tables, and the
display padding remains. This diagnostic work does not show an accuracy improvement
or resolve the table structures.

## References

- [OpenAI SDK structured parsing behavior](https://github.com/openai/openai-python/blob/main/src/openai/lib/_parsing/_completions.py)
- [Differences between parse and create](https://github.com/openai/openai-python/blob/main/helpers.md#differences-from-create)
- [Azure content filtering and annotations](https://learn.microsoft.com/en-us/azure/foundry-classic/foundry-models/concepts/content-filter)

Azure documentation explains supported metadata shapes; it does not establish
which filtering service this configured gateway uses.
