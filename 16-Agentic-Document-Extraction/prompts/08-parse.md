# Phase 8: Layout parsing

**Implement** `src/parse.py` and its schemas. Do not change the invoice commit rules in this phase.

**Schemas** (Pydantic, `extra` forbidden):

```python
class BBox(BaseModel):
    page: int  # 1-based
    xyxy: tuple[float, float, float, float]  # normalized 0-1

class ParseBlock(BaseModel):
    id: str
    type: Literal["title","heading","text","table","key_value","figure","line_item","other"]
    text: str
    bbox: BBox | None
    conf: float | None = None
    table: list[list[str]] | None = None  # rows, only when type == "table"

class ParsePage(BaseModel):
    page: int
    width_px: int
    height_px: int
    blocks: list[ParseBlock]

class ParseResult(BaseModel):
    doc_sha: str
    pages: list[ParsePage]
    model: str = "gpt-6-sol"
```

**Requirements:**
- For every page image, reuse `preprocess`; for a PDF, render every page; look up `pypdfium2`'s page-loop API rather than assuming one.
- Call the model with `with_structured_output(ParsePage)` (or a wrapper returning that page's blocks). Prompt it to identify visual regions in reading order, return tables as 2D arrays, normalize boxes to the image it sees, and omit `bbox` when it isn't confident of one.
- Cap the number of pages parsed (config, default 10) so a large document can't blow up cost.
- Save the result to `data/parse/<doc_sha>.json`.

**Tests:** parsing the fixture PNG yields a `ParseResult` with at least one block (a live model-backed test is optional, not required). A fake client returning two blocks results in that JSON being written.

**CLI:** `python -m src.parse --path tests/fixtures/invoice.png`

Stop after this phase; no Markdown renderer yet.
