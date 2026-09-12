# Phase 10; Annotated PDF and full graph wiring

**Implement** `src/annotate.py`, then wire `parse`/`markdown`/`annotate` into the graph and the UI.

**`src/annotate.py`:**
- Input: the original PDF or images, a `ParseResult`, and an optional Invoice-field → block-id map.
- Output: `data/annotated/<doc_sha>.pdf`, drawing a rectangle plus a label (the field name if mapped, else the block type) for every block that has a bbox.
- An images-only source is built into a multi-page PDF from the page images before drawing.
- Look up a Windows-pip-installable stack for this. If overlaying onto an existing PDF proves fragile, rasterize the pages, draw with Pillow, and save as a PDF instead; document whichever choice is made.
- A block with a missing or out-of-range bbox is skipped, not guessed at; count skips in a sidecar `data/annotated/<doc_sha>.meta.json`.

**Graph wiring:**
- Right after `preprocess`: parse every page (respecting the page cap), and write the Markdown and parse JSON before `extract` runs.
- `extract_invoice` may receive the parsed Markdown alongside the original image, but must still return a structured `Invoice`.
- Both `commit` and `review` add the Markdown path and annotated-PDF path to their JSON record.
- The `Invoice` commit is still gated on `validate.ok` or an explicit human override; parsing/annotation never bypass that.
- In the crop pass, prefer a bbox the layout parser already found for a failing line item over making a second "regions only" model call, whenever such a box exists.

**Streamlit:** add tabs or expanders for Markdown preview, annotated-PDF download, parse JSON, and Invoice + validation. Leave the review queue unchanged.

**Tests:** parsing the fixture PNG produces an annotated PDF that exists and has nonzero size; a block with no bbox does not crash annotation.

**Docs:** update `README.md`, `docs/ARCHITECTURE.md`, and `docs/COMPLIANCE.md` to state that parse artifacts are always written, while the invoice commit remains gated.

**Dependencies:** pin any new ones in `requirements.txt`.

Stop with the full file tree.
