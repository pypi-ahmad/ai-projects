# Agentic Document Parsing

This app converts scanned PDFs and images into context-aware, layout-aware Markdown with `gpt-6-sol`.

The app transcribes document structure and content without extracting business fields, applying a domain schema, correcting values, or summarizing the source. It keeps an internal page, block, and bounding-box representation for reading order, annotations, and JSON output.

## Outputs

- Input preview shows the selected source pages before processing.
- Markdown has rendered and raw views, plus copy and download controls.
- Annotated shows grounded block overlays and provides a PDF download.
- HTML shows the self-contained rendered output and provides a download.
- JSON shows the internal layout data with copy and download controls.

Each run writes artifacts beneath `data/parse/runs/<run-id>/`.

## How it works

The app sends pages to `gpt-6-sol` in source order. Each request includes up to 12,000 characters from previously parsed pages to help with continued headings, tables, and reading order. Python renders Markdown, HTML, JSON, and annotations from the returned layout blocks.

The pipeline follows the parse-first approach described by [LlamaParse](https://developers.llamaindex.ai/llamaparse/parse/getting_started/) and the grounded Markdown and annotation workflow shown by [LandingAI ADE](https://docs.landing.ai/ade/ade-parse-visualize-sample). The official [GPT-6 Sol page](https://developers.openai.com/api/docs/models/gpt-6-sol) documents the model capabilities and pricing.

## Setup

1. Install `uv` and set `OPENAI_API_KEY`. Optional endpoint settings are listed in `.env.example`.
2. Run `run.cmd`.

The launcher creates `.venv`, installs `requirements.txt` when it changes, and starts Streamlit on port `5805`. If you manage the environment yourself, start the app with `streamlit run src/ui/app.py`.

Supported inputs are PDF, PNG, JPEG, TIFF, and WebP. The app rejects any model name other than `gpt-6-sol` before preprocessing or an API request.

For development, install the test dependency and run the suite through uv:

```powershell
uv pip install --python .venv\Scripts\python.exe -r requirements-dev.txt
uv run --no-project --python .venv\Scripts\python.exe -m pytest
```

See [Architecture](docs/ARCHITECTURE.md), [Model](docs/MODEL.md), [Prompts](docs/PROMPTS.md), and the [Runbook](docs/RUNBOOK.md).
