# Architecture

```text
scanned PDF/image -> render pages -> sequential visual parse -> deterministic artifacts
```

`src/graph.py` coordinates preprocessing and parsing. Its first node validates the source and computes the document hash. `src/parse.py` then uses `src/preprocess.py` to rasterize the selected pages and processes them in source order with `gpt-6-sol`. Each request can include up to 12,000 characters from earlier successful pages. The pipeline has no document-wide second model pass.

`src/layout.py` defines the internal grounding contract for documents, pages, blocks, table rows, reading order, and normalized bounding boxes. This contract supports rendering, downloadable JSON, and visual annotations. It contains no business-field schema.

| Module | Responsibility |
| --- | --- |
| `src/llm.py` | Configure the single supported model and invoke structured visual parsing. |
| `src/markdown.py` | Render layout blocks into Markdown and self-contained HTML. |
| `src/annotate.py` | Draw valid model-provided block boxes on source pages. |
| `src/ui/app.py` | Present input, Markdown, annotated, HTML, and JSON views. |

Diagnostics record filtered and failed pages. Successful pages still produce text artifacts when another page fails. An annotation error does not discard parsed text.

Each run writes to `data/parse/runs/<run-id>/`. A successful parse produces Markdown, HTML, and layout JSON. When annotation also succeeds, the run includes an annotated PDF, page PNGs, and annotation metadata.
