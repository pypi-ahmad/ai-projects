# Phases 8-10: Overview

**Implement**, across three phases, a document-parsing pipeline layered on top of the existing invoice graph: `parse → layout-aware Markdown → annotated PDF`.

**Constraints:**
- Do not remove or weaken the invoice graph; math validation and human review remain required before an `Invoice` commits.
- Model stays `gpt-6-sol`, configured from `OPENAI_API_KEY` and optional `OPENAI_BASE_URL`, exactly as in Phase 0.
- Look up how to draw on PDFs on native Windows (`pypdf` + Pillow, and/or `reportlab`); no Poppler, no Docker. If a candidate library won't install, pick another and document the choice.
- The model may not return accurate bounding boxes: if a box is missing or off-page, skip drawing that field rather than inventing coordinates. Markdown output without boxes is still required (best-effort reading order).

**Process:** each of Phases 8, 9, and 10 implements only its own scope.
