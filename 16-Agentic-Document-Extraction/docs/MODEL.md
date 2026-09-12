# Model

- Models: `gpt-5.6-terra` (default) and `gpt-5.6-luna`, selectable in the sidebar.
  Both use the existing OpenAI-compatible endpoint — this is not
  necessarily a model OpenAI itself hosts; `OPENAI_BASE_URL` is expected to
  point at the gateway serving these models.
- Modality: image in, structured JSON out. One `HumanMessage` per call with
  a text instruction block and an `image_url` content block carrying a
  `data:<mime>;base64,...` URL (the standard `langchain-openai` multimodal
  shape).
- `temperature=0`.
- Structured output via the OpenAI SDK's raw-response `chat.completions.create`
  with a strict JSON schema, followed by local Pydantic validation.
  Filtering, refusal, and incomplete output are checked before validation.

The active graph only ever sends the `ParsePage` schema (layout parsing).
`Invoice`/`Region`/the regions wrapper are shaped by the same strict-mode
constraints described below but aren't currently sent to the model —
extraction/validation is dormant, see
[docs/ARCHITECTURE.md](ARCHITECTURE.md#dormant-the-invoice-extractionvalidation-graph).

## Selection and pricing

The sidebar selection applies to the next Parse run. Every concurrent page in
that run uses the same model. Changing the dropdown preserves the completed
result and does not send API requests. The result identifies its own model.
Python parsing/graph entrypoints accept an optional `model` argument and default
to Terra. Unsupported IDs are rejected; there is no automatic model fallback.

Rates in `src/models.py` are user-supplied USD estimates per million tokens:

| Model | Input | Cached input | Output |
| --- | ---: | ---: | ---: |
| Terra | $2.00 | $0.20 | $12.00 |
| Luna | $0.20 | $0.02 | $1.20 |

Costs are summed per call using its requested model, including sessions that
use both models. The provider-returned model is retained separately in page
diagnostics. Switching models never reprices previous calls. Missing usage
remains unknown, not a claim that a failed call was free.

[Luna documentation](https://developers.openai.com/api/docs/models/gpt-5.6-luna)
lists image input, Chat Completions, and structured outputs. The configured
gateway's compatibility must be verified separately.

## Reasoning effort — a documented uncertainty

Luna always uses `reasoning_effort="high"`. Terra retains the
`REASONING_EFFORT` environment setting described below.

The installed `langchain-openai==1.6.2` declares `reasoning_effort: str | None`
as a genuine top-level field on `ChatOpenAI` (verified locally by
constructing `ChatOpenAI(..., reasoning_effort="medium")` and inspecting
`ChatOpenAI.model_fields`) — it is sent as a normal Chat Completions
parameter, not routed through OpenAI's separate Responses API. That's a
different, older mechanism (`ChatOpenAI(reasoning={"effort": ...},
output_version="responses/v1")`) that this project does not use.

Gateway support varies. `src/extract.py` reads `REASONING_EFFORT` from the
environment (default `"medium"`). An empty value omits the field. The September
12 live evaluation accepted the configured value; that verifies request
acceptance, not how the gateway implements reasoning.

## Strict `json_schema` mode constrains how the Pydantic schemas are written

A live run surfaced two real `openai.BadRequestError`s ("Invalid schema for
response_format") from OpenAI's strict `json_schema` structured-outputs mode,
which enforces a stricter subset of JSON Schema than Pydantic emits by
default:

1. **Every property must appear in `required`**, even ones that are
   conceptually optional — those must be nullable types instead of relying
   on a Python default. A Pydantic field like `vendor: str | None = None`
   generates a schema where `vendor` is *absent* from `required` (because it
   has a default), which strict mode rejects. The fix: drop the `= None`
   default so the field is `str | None` — required as a JSON key, but its
   *value* can still be `null`. `Invoice.vendor/invoice_date/currency`,
   `Region.reason`, and `ParseBlock.conf/table` all follow this pattern now.
2. **Fixed-length tuple validation (`prefixItems`) isn't supported.**
   `tuple[float, float, float, float]` (as originally specified for
   `Region.bbox_xyxy` and `BBox.xyxy`) makes Pydantic emit
   `prefixItems`/`minItems`/`maxItems`, which strict mode also rejects. The
   fix: `tuple[float, ...]` (variable-length) generates a plain
   `{"type": "array", "items": {"type": "number"}}` schema instead, with a
   `field_validator` enforcing exactly 4 values at the Python level — same
   guarantee, OpenAI-compatible schema shape.

Every schema actually sent to the model (`Invoice`, `ParsePage` — which
nests `ParseBlock`/`BBox` — and the regions wrapper schema) was re-checked
after this fix: every property required, no `prefixItems`/`minItems`/
`maxItems` anywhere in the tree, including nested `$defs`.

## Token usage and cost

Every structured-output call uses `_invoke_structured` in `src/extract.py`.
It captures reported input/output/cached usage before checking the completion.
`src/usage.py` records this in the existing process-wide accumulator, reset
for each document run. Missing input/output usage is explicitly unknown;
the UI labels incomplete totals as reported and excludes unknown usage from
the cost estimate. Rates follow the selected model's table above; these are
estimates, not gateway billing data.

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
response — for the active `ParsePage` schema, that its blocks have the
right field types — and says nothing about whether numbers agree with each
other. For the dormant `Invoice` schema, that check would have been
`src/validate.py`'s job entirely, run independently of however well-formed
the model's output was. It doesn't run today: the active graph never
extracts or validates an `Invoice`. See
[docs/ARCHITECTURE.md](ARCHITECTURE.md#dormant-the-invoice-extractionvalidation-graph).
