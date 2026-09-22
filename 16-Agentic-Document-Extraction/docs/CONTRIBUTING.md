# Contributing

Keep changes within the parse-only product boundary: scanned PDF or image to grounded Markdown, HTML, JSON, and annotations. Adding a business-field schema requires an explicit product decision.

Route `gpt-6-sol` calls through `src/llm.py`. Preserve page order and keep the page image authoritative when preceding-page context disagrees with it.

Before submitting a change:

1. Add or update focused tests.
2. Install `requirements-dev.txt`, then run `uv run --no-project --python .venv\Scripts\python.exe -m pytest`.
3. Run `git diff --check`.
4. Update current documentation when behavior changes.

Never commit credentials, uploaded documents, or generated run artifacts.
