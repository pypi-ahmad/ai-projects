# Phase 9; Layout-aware Markdown

**Implement** `src/markdown.py`: `parse_to_markdown(ParseResult) -> str`.

**Rendering rules:**
- Sort blocks by page, then bbox top, then left; a block with no bbox keeps its place in the model's own order.
- `title` → `#`, `heading` → `##`.
- `text` → a plain paragraph.
- `key_value` → `**key:** value` if the text splits on its first colon, otherwise the raw text.
- `table` → a GitHub-style pipe table built from `table[][]`; if `table` is `None`, render the block's raw text as a fenced code block instead.
- `figure` → `[figure] <caption text>`.
- Never invent cells that aren't present in the data.

**Output:** write `data/parse/<doc_sha>.md` next to the parse JSON, and attach the rendered Markdown to the graph state once parsing has run.

**Tests:** a handmade `ParseResult` with a heading, a 2x2 table, and a paragraph renders to a stable, snapshotted Markdown string.

**CLI:** `python -m src.markdown --parse data/parse/<sha>.json`

Stop after this phase; no PDF drawing yet.
