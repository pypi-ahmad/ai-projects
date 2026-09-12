# Context Assembly Service

Receives a **token budget** and candidate blocks from three families; **memory**, **docs**, **tools**; and returns a packed context that fits, plus a decision report explaining every kept, compressed, or dropped block.

Context engineering is the point. Every decision is visible.

---

## 30-second demo

```cmd
:: 1. Clone / enter the project
cd D:\ai-projects\3-Context-Assembly-Service

:: 2. Launch the UI (creates venv + installs deps automatically)
run.cmd
```

The browser opens at `http://localhost:8501`.

1. Click **Load sample**; loads `tests/fixtures/sample_request.json` (400-token window, oversized docs).
2. Click **▶ Assemble**; packs blocks, drops what doesn't fit.
3. Read the results: token bars per family, packed messages, dropped-block table.
4. Click **⬇ Export pack.json**; download the full payload for your API call.

---

## CLI

```cmd
uv run python -m src.assembly ^
    --request tests/fixtures/sample_request.json ^
    --policy  balanced ^
    --out     out/pack.json
```

Output:
```
packed  258/400 tokens  (142 leftover | 2 dropped | 0 compress jobs)
  dropped  tool-2  [OVER_FAMILY_CAP]
  dropped  doc-2   [OVER_FAMILY_CAP]
```

---

## What it packs

| Family | Examples |
|--------|----------|
| `memory` | conversation turns, user profile, retrieved memories |
| `docs`   | reference documents, chunked source material |
| `tools`  | tool schemas, tool call results |

Each block carries: `id`, `text`, `family`, `priority` (higher = keep first),
`droppable`, `compressible`.

---

## How the packing works

```
context_window
├── output_reserve   (default 20%)  — never packed
├── system_reserve   (default 8%)   — never packed
├── user message                    — never packed
└── usable budget
    ├── Pass A  force-keep highest-priority block per family
    ├── Pass B  fill within per-family soft caps
    └── Pass C  borrow surplus across families
        └── overflow → compress job (if compressible) or drop
```

Policy files in `config/policies/` control family caps.
Four built-in policies: `balanced`, `docs_heavy`, `tools_heavy`, `memory_heavy`.

---

## Eval

```cmd
uv run python tests/eval/run_eval.py
```

Runs 6 built-in cases; `overflow_count` must be 0.

```
------------------------------------------------------------------------
  ID                      PASS  DROPS  CMPR  LFTOVR
------------------------------------------------------------------------
  all-fit-small           PASS      0     0    3226
  doc-overflow            PASS      0     0       6
  ...
------------------------------------------------------------------------
  overflow_count : 0  <- must be 0
  drop_rate      : 0.0%
  compress_rate  : 8.7%
  avg_leftover   : 826 tokens
------------------------------------------------------------------------
```

---

## Providers (optional; compression only)

| Provider | Env var(s) | Model |
|----------|-----------|-------|
| Ollama (local) | `OLLAMA_HOST` (default `localhost:11434`) | `qwen3.5:2b` → `qwen3.5:0.8b` |
| Agnes AI | `AGNES_API_KEY` | `agnes-2.5-flash` |
| OpenAI-compatible | `OPENAI_API_KEY` + `OPENAI_BASE_URL` | `gpt-5.6-luna` |
| Gemini | `GOOGLE_API_KEY` | `gemini-3.5-flash-lite` |

There is no `.env.example` in this repo. Create a `.env` file yourself with any of the
variables above (see `run.cmd`, which loads `.env` if present). All providers are optional;
packing works fully offline with no keys set.

---

## Requirements

- Python 3.11+
- `uv`; `winget install astral-sh.uv`
- No GPU needed for packing; RTX 4060 8 GB used only for optional Ollama compression

---

## Known limitations

- `src/eval/__init__.py` and `src/providers/__init__.py` are empty stubs (one comment each,
  no code). Eval logic actually lives in `tests/eval/run_eval.py`; provider logic lives in the
  root-level `providers.py`.
- No `.env.example` file; see Providers section above.
- Compression quality (fact preservation, coherence) is not evaluated beyond the
  `TRIMMED` / `COMPRESS_FAILED` length safeguards in `src/compress/compressor.py`.
- No retrieval or RAG index; the caller must supply already-selected, already-ranked blocks.
- `docs/CONTRIBUTING.md` is omitted: this directory is not a git repository and has no CI
  configuration (no `.github/`), so there are no branch or test-gate conventions to document.

---

## Project layout

```
context_assembly.py        legacy flat API (Block, assemble)
providers.py               compress chain (Ollama → Agnes → OpenAI → Gemini)
src/
  blocks/                  ContextBlock, ContextRequest, TokenCounter
  budget/                  BudgetPolicy, allocate()
  assembly/                pack(), BudgetReport, CLI (__main__.py)
  compress/                compress_one(), run_compress_jobs()
  ui/                      Streamlit app
config/policies/           balanced, docs_heavy, tools_heavy, memory_heavy
data/model_windows.yaml    verified context windows per model
tests/
  test_blocks.py           16 checks
  test_budget.py           15 checks
  test_packer.py           19 checks
  test_compress.py         19 checks
  eval/cases.jsonl         6 eval cases
  eval/run_eval.py         eval runner + metrics
docs/
  ARCHITECTURE.md  BUDGET.md  RUNBOOK.md  TECHNICAL.md  EVAL.md
```

---

<p align="center">Made with ❤️ by Ahmad Mujtaba</p>
