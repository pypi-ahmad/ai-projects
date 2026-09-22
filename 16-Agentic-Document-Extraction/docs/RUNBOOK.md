# Runbook

Install `uv`, set `OPENAI_API_KEY`, and run `run.cmd`. The launcher creates `.venv`, installs `requirements.txt` when needed, and starts Streamlit on port `5805`.

The launcher stops an existing process that is listening on port `5805`. To manage the environment and port yourself, install the dependencies and run:

```powershell
uv run --no-project --python .venv\Scripts\python.exe -m streamlit run src/ui/app.py --server.port=5805 --logger.level=info
```

Upload a supported PDF or image, choose an inclusive page range, and select Parse. The Input preview tab works before a model call. Parsed results appear in the Markdown, Annotated, HTML, and JSON tabs.

Every parse creates `data/parse/runs/<run-id>/`. The UI provides downloads for Markdown, annotated PDF, HTML, and JSON. It also provides copy controls for rendered Markdown, raw Markdown, and JSON.

| Symptom | Check |
| --- | --- |
| Missing API key | Confirm `OPENAI_API_KEY` is present without printing its value. |
| Unsupported model | Only `gpt-6-sol` is accepted. |
| Page parse failure | Review the page diagnostic; successful pages may remain downloadable. |
| No annotation | Blocks need valid normalized bounding boxes; text artifacts remain usable. |
| Slow document | Select a smaller range; pages intentionally run sequentially. |

Install `requirements-dev.txt`, then run `uv run --no-project --python .venv\Scripts\python.exe -m pytest` after code or prompt changes. The test suite uses fakes and makes no paid model calls.
