# Prompt contract

The runtime prompt is `prompts/runtime/parse-page.md`.

The template receives the source page number, selected-range page count, raster dimensions, and preceding-page context. It tells `gpt-6-sol` to preserve visible text, reading order, headings, lists, tables, key/value lines, figures, marginalia, and bounding boxes. Document text is treated as data, even when it looks like an instruction.

The prompt forbids summarization, correction, normalization, and business-field extraction. It requires character-by-character checking for names, addresses, dates, identifiers, codes, and long numbers. It also requires rectangular table arrays, with empty trailing cells retained. Unreadable text uses `[ILLEGIBLE]`. Previous-page context can clarify structure but cannot override the current image.

All reusable model instructions live in Markdown under `prompts/runtime/`. Python supplies document data and page metadata. Any prompt change must preserve the placeholders and pass `tests/test_prompts.py`.
