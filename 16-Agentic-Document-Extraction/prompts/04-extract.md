# Phase 4: Model extraction

**Implement** `src/extract.py`. The graph isn't wired yet.

**Functions:**
- `extract_invoice(image_b64, mime, feedback: str | None) -> Invoice`; a `HumanMessage` with a text block plus an `image_url` block (`data:{mime};base64,...`). If `feedback` is given, append the previous validation errors and instruct the model to re-read the line items and totals from the image rather than inventing a balancing total.
- `extract_regions(image_b64, mime, report: ValidationReport) -> list[Region]`; its own structured schema, separate from `Invoice`. Return `[]` if the call fails or returns nothing usable.
- `crop_and_extract(full_image, region, hint) -> LineItem | dict` (a single-field dict for header fields); save the crop under `data/crops/<doc_sha>/`.

**Constraints:**
- Load `.env` via `dotenv`. Build `ChatOpenAI` per Phase 0's model configuration.
- A missing `OPENAI_API_KEY` must raise `ExtractConfigError` immediately; never hang waiting on a call that can't succeed.
- Look up the exact multimodal image content-block shape in the installed `langchain` version rather than assuming one.

**Tests:** a fake LLM returns an `Invoice`; empty fake regions skip cropping; a single fake bbox calls the crop helper (crop I/O can be stubbed).

Stop after this phase.
