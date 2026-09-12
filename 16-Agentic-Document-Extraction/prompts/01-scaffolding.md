# Phase 1; Scaffolding

**Implement** the project's documentation and file scaffolding only. No model calls in this phase.

**Docs and config:**
- `README.md`: what this is, what it isn't (not LandingAI ADE / Reducto), env vars, `run.cmd`, graph steps, the 0.05 tolerance.
- `docs/ARCHITECTURE.md`: a Mermaid diagram for `preprocess → extract → validate → (regions/crop → validate) → extract | commit | review`.
- `docs/VALIDATE.md`: `|qty*unit_price - amount| <= 0.05`; `|sum(amounts) - subtotal| <= 0.05`; `|subtotal + tax - grand_total| <= 0.05`.
- `docs/REGIONS.md`: `Region {id, field_or_line_index, conf, bbox_xyxy}` (bbox normalized 0-1); crop only if a bbox is present **and** (`conf < 0.6` **or** that field failed math).
- `docs/COMPLIANCE.md`: audit fields, `human_override`, no silent fixes, images stay under `data/inbox`, what `.gitignore` excludes.
- `docs/MODEL.md`: `gpt-5.6-terra`, image in / text out, structured outputs; and that a structured output is not the same as a mathematically correct one.
- `.env.example`: `OPENAI_API_KEY=` and `OPENAI_BASE_URL=` (empty).
- `.gitignore`: `.venv`, `.env`, `data/inbox/*`, `data/crops/*`, `__pycache__`.
- `requirements.txt` stub: `langchain-openai`, `langchain-core`, `langgraph`, `pydantic`, `python-dotenv`, `pillow`, `streamlit`, plus a Windows-native PDF page renderer to verify in Phase 3 (e.g. `pypdfium2`, if it installs).

**Code and directories:**
- Empty placeholders: `src/schema.py`, `src/validate.py`, `src/preprocess.py`, `src/extract.py`, `src/regions.py`, `src/graph.py`, `src/audit.py`, `src/ui/app.py`.
- Directories: `data/inbox`, `data/committed`, `data/review`, `data/crops`, `data/audit`, `tests/fixtures`.
- `run.cmd`: a stub that just prints `not wired`.

**Verification:** all listed files and directories exist.

Stop after this phase.
