# Model

- Model: `gpt-6-sol` only. Uses the existing OpenAI-compatible endpoint:
  `OPENAI_BASE_URL` selects a gateway; omit it to use api.openai.com.
- Each request contains an image and returns structured JSON. It uses one
  `HumanMessage` with a text instruction block and an `image_url` block carrying
  a `data:<mime>;base64,...` URL, the `langchain-openai` multimodal shape.
- `temperature` is omitted by the shared client and raw request builder.
- Structured output via the OpenAI SDK's raw-response `chat.completions.create`
  with a strict JSON schema, followed by local Pydantic validation.
  Filtering, refusal, and incomplete output are checked before validation.

The active graph sends only the `ParsePage` schema for layout parsing.
`Invoice`/`Region`/the regions wrapper are shaped by the same strict-mode
constraints described below but aren't currently sent to the model ;
extraction/validation is dormant, see
[docs/ARCHITECTURE.md](ARCHITECTURE.md#dormant-the-invoice-extractionvalidation-graph).

## Model and pricing

The UI has no model selector or automatic fallback. Python entrypoints retain
the optional `model` argument for compatibility and reject values other than
`gpt-6-sol` before API calls. Sol extracts page structure and text. Python renders
Markdown, HTML, and annotations.

Rates in `src/models.py` are USD estimates per million tokens from the linked
OpenAI model pages:

| Model | Input | Cached input | Cache writes | Output |
| --- | ---: | ---: | ---: | ---: |
| GPT-6 Sol | $2.00 | $0.20 | $2.50 | $10.00 |

Costs are summed from the explicit per-run ledger. The provider-returned model
is retained separately in diagnostics; an alias never changes pricing. Missing
usage remains unknown; a failed call is not assumed free. On upgrading,
the UI starts a fresh Sol session ledger rather than repricing legacy calls.

[GPT-6 Sol](https://developers.openai.com/api/docs/models/gpt-6-sol) supports
image input, Chat Completions, structured outputs, and prompt caching. These
base-rate estimates exclude long-context, regional, Batch/Flex, Fast-mode, and
gateway-specific adjustments. They are not billing records.

## Reasoning effort and observed gateway support

Sol uses the `REASONING_EFFORT` environment setting described below.

The installed `langchain-openai==1.6.2` declares `reasoning_effort: str | None`
as a genuine top-level field on `ChatOpenAI` (verified locally by
constructing `ChatOpenAI(..., reasoning_effort="medium")` and inspecting
`ChatOpenAI.model_fields`); it is sent as a normal Chat Completions
parameter, not routed through OpenAI's separate Responses API. That's a
different, older mechanism (`ChatOpenAI(reasoning={"effort": ...},
output_version="responses/v1")`) that this project does not use.

OpenAI documents `reasoning_effort` for Chat Completions. Gateway support can
still vary. `src/extract.py` reads `REASONING_EFFORT` from the
environment (default `"medium"`). An empty value omits the field. The September
23 Sol comparison sent `medium` with strict structured output: all ten requests
returned HTTP 200 and the model identifier `gpt-6-sol`. This verifies acceptance
for those calls only. It does not establish the gateway's internal reasoning
behavior or support for other effort settings. See
[the current evaluation](SOL-RESOLUTION-EVALUATION.md).

## Strict `json_schema` mode constrains how the Pydantic schemas are written

A live run surfaced two real `openai.BadRequestError`s ("Invalid schema for
response_format") from OpenAI's strict `json_schema` structured-outputs mode,
which enforces a stricter subset of JSON Schema than Pydantic emits by
default:

1. **Every property must appear in `required`**, even ones that are
   conceptually optional; those must be nullable types instead of relying
   on a Python default. A Pydantic field like `vendor: str | None = None`
   generates a schema where `vendor` is *absent* from `required` (because it
   has a default), which strict mode rejects. The fix: drop the `= None`
   default so the field is `str | None`; required as a JSON key, but its
   *value* can still be `null`. `Invoice.vendor/invoice_date/currency`,
   `Region.reason`, and `ParseBlock.conf/table` all follow this pattern now.
2. **Fixed-length tuple validation (`prefixItems`) isn't supported.**
   `tuple[float, float, float, float]` (as originally specified for
   `Region.bbox_xyxy` and `BBox.xyxy`) makes Pydantic emit
   `prefixItems`/`minItems`/`maxItems`, which strict mode also rejects. The
   fix: `tuple[float, ...]` (variable-length) generates a plain
   `{"type": "array", "items": {"type": "number"}}` schema instead, with a
   `field_validator` enforcing exactly 4 values at the Python level; same
   guarantee, OpenAI-compatible schema shape.

Every schema actually sent to the model (`Invoice`, `ParsePage`; which
nests `ParseBlock`/`BBox`; and the regions wrapper schema) was re-checked
after this fix: every property required, no `prefixItems`/`minItems`/
`maxItems` anywhere in the tree, including nested `$defs`.

## Token usage and cost

Every structured-output call uses `_invoke_structured` in `src/extract.py`.
It captures reported input/output/cached/cache-write usage before checking the
completion.
The graph allocates a ledger and explicitly passes it through page calls.
`src/usage.py` has no shared accumulator or reset operation. Failed calls retain
reported usage even if artifact writing fails. Streamlit accumulates completed
runs in session state. Missing input/output usage stays unknown and is excluded
from the reported cost estimate. Input totals already include cached and
cache-write tokens: ordinary input is `max(input - cached - cache_write, 0)`.
Each category uses the corresponding Sol rate above.

## Page diagnostics

Parse JSON includes `page_diagnostics`, also shown in a collapsed UI expander.
Each entry contains the page, classified outcome, HTTP status, sanitized
request/model identifiers, finish reason, reported token counts, and recognized
filter categories/flags/severities when available. Provider text, refusal text,
response bodies, request headers, credentials, and image data are excluded
from diagnostics. Successful extraction content remains in the normal result.

Failed pages do not discard successful pages. Even an all-failed run saves
diagnostics JSON, but produces no Markdown or annotated PDF. Absent filter
annotations mean the category is unknown. This change preserves evidence;
it does not disable filtering or retry rejected content. The live evaluator
sets `max_retries=0` on the actual SDK client; normal runtime retains SDK
defaults for transient HTTP/transport failures.

## Structured output ≠ math correctness

Strict JSON schema plus Pydantic validation checks the *shape* of a
response; for the active `ParsePage` schema, that its blocks have the
right field types; and says nothing about whether numbers agree with each
other. For the dormant `Invoice` schema, that check would have been
`src/validate.py`'s job entirely, run independently of however well-formed
the model's output was. It doesn't run today: the active graph never
extracts or validates an `Invoice`. See
[docs/ARCHITECTURE.md](ARCHITECTURE.md#dormant-the-invoice-extractionvalidation-graph).
