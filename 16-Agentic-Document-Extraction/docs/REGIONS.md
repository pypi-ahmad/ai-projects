# Regions and cropping (dormant)

**Status: not wired into the active graph.** `maybe_crop` isn't a node in
`src/graph.py` anymore; see
[docs/ARCHITECTURE.md](ARCHITECTURE.md#dormant-the-invoice-extractionvalidation-graph).
The schema and trigger rule below describe `src/regions.py` and the cropping
functions in `src/extract.py` as they still exist on disk, for whoever
re-wires them.

## Region schema

```python
class Region(BaseModel):
    id: str
    field_or_line_index: str   # e.g. "grand_total" (header field) or "line_items[1]" (whole line item)
    conf: float                # model's own confidence, 0-1
    bbox_xyxy: tuple[float, ...]  # normalized 0-1, exactly 4 values: (x0, y0, x1, y1)
    reason: str | None         # required key, nullable value -- see docs/MODEL.md
```

`bbox_xyxy` is normalized to the image's own width/height so it survives the
resize done in `preprocess`; multiply by `(width, height, width, height)` to
get pixel coordinates for cropping. It's typed as a variable-length tuple
(with a validator enforcing exactly 4 values) rather than
`tuple[float, float, float, float]`; see docs/MODEL.md for why.

## Crop trigger rule

A region is cropped **only if both** hold:

1. `bbox_xyxy` is present (the model actually returned a box for it), **and**
2. either `conf < 0.6` **or** that field is one that failed a math check in
   the current `ValidationReport`.

If the model returns no bounding boxes at all, cropping is skipped entirely
and the flow falls back to a full-page retry; cropping is a best-effort
accuracy aid, never a required step.

## Why

Re-reading a tight crop of just the confusing cell (a smudged total, a
rotated line) gives the model a cleaner second look than re-reading the
whole page. It is not run when there's nothing pointing at a specific
region, since a full-page retry with the validation error as feedback is
just as likely to fix an ordinary misread.
