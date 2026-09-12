# Luna validation — September 12, 2026

The sidebar now offers GPT-5.6 Terra (default) and GPT-5.6 Luna. A run uses
one selected model for all its pages. Changing the dropdown retains the last
result without making requests; session costs use each call's model rate.
Prompts, temperature, reasoning effort, rendering, and concurrency remain unchanged.

89 offline tests passed, including model routing, concurrent page selection,
strict-schema request settings, separate requested/returned model diagnostics,
mixed-model pricing, and Streamlit result persistence across model switches.
UI validation used Streamlit AppTest; no manual browser validation was performed.

## Approved live test

Exactly one Luna invocation per page, SDK retries disabled. Outputs are isolated
under `data/parse/luna-eval-20260912-020102/`, with a `manifest.json` containing
diagnostics, scores, and verified unchanged prompt hashes.

| Document | Page | Result |
| --- | --- | --- |
| Masked BadgeCare Plus_1 | 1 | Transport error; no HTTP status or request ID; usage/cost unknown |
| Masked_Amerigroup_RealSolutions_1 | 1 | Parsed; HTTP 200; returned model `gpt-5.6-luna` |

RealSolutions reference-token precision, recall, and F1 were each 98.20%.
Luna emitted 14 blocks and zero table blocks, with no missing or invalid bounding
boxes. This token score does not measure layout or table-structure fidelity.
Reported usage was 2,761 input and 2,393 output tokens, with zero cached input;
estimated cost at the configured Luna rates was $0.0034238.

BadgeCare's transport failure does not establish filtering, model unavailability,
or successful extraction. There was no second attempt or switch to another model.
