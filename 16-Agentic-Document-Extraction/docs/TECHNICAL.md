# Technical reference

The application is a Python and Streamlit interface over a small LangGraph pipeline. `pypdfium2` renders PDF pages. Pillow handles raster images and writes annotated output. Pydantic defines the internal layout response. The pipeline saves layout JSON, while local renderers write Markdown, HTML, annotated page PNGs, and an annotated PDF.

Runtime rules:

- `gpt-6-sol` is the only accepted model.
- Pages are parsed sequentially in source order.
- Preceding context is bounded to 12,000 characters.
- The source image is authoritative.
- Layout JSON is an internal grounding artifact, not a domain schema.
- Table rows are padded with empty trailing cells when needed so saved arrays remain rectangular.
- Missing or invalid bounding boxes are skipped rather than invented.
- Each run has an isolated artifact directory.

The production prompt lives in `prompts/runtime/parse-page.md`; no reusable model instruction is stored in Python. `src/layout.py` owns response types, `src/llm.py` owns model calls, and `src/graph.py` owns orchestration.
