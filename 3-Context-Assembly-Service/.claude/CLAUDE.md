# Context Assembly Service

Windows 11 native. No WSL2. No Docker. Use `uv` for Python.

## Constraints

- Default path requires no Ollama model. `tiktoken cl100k_base` does all token counting.
- RTX 4060 8 GB: no embed/OCR model unless a later phase adds retrieval. See NOTES.md.
- Models load on demand via Ollama HTTP (`OLLAMA_HOST` or `localhost:11434`).
  Never load two 3B+ models simultaneously.
- `use_compress=False` / `compress_mode=off` is the default. All tests must pass with no Ollama running and no env keys set.
- This is a budgeter, not a chatbot. No conversational loop, no streaming.

## Layout

```
context_assembly.py          Legacy flat API — Block, Decision, AssemblyResult, assemble()
providers.py                 compress() provider chain + ollama_unload()
test_context_assembly.py     assert-based self-check; run with `python test_context_assembly.py`
run.cmd                      One-shot launcher: uv sync → .env load → streamlit run
pyproject.toml               uv project; deps: tiktoken, PyYAML, streamlit>=1.35
NOTES.md                     Model map quick reference (RTX 4060 8 GB)

src/
  blocks/
    models.py                ContextBlock · ContextRequest · Family
    tokenizer.py             TokenCounter (tiktoken cl100k_base)
  budget/
    policy.py                BudgetPolicy · FamilyCaps · load_policy()
    allocator.py             AllocationPlan · allocate() · DropReason (3-pass engine)
  assembly/
    packer.py                PackResult · BudgetReport · pack()
    __main__.py              CLI: python -m src.assembly --request FILE --out FILE
  compress/
    compressor.py            CompressResult · compress_one() · run_compress_jobs()
  ui/
    app.py                   Streamlit front-end

config/policies/             balanced · docs_heavy · tools_heavy · memory_heavy (YAML)
data/model_windows.yaml      per-model context window lookup table

tests/
  test_blocks.py             16 checks
  test_budget.py             15 checks
  test_packer.py             19 checks
  test_compress.py           19 checks
  eval/cases.jsonl           6 eval cases
  eval/run_eval.py           eval runner + metrics
  fixtures/                  sample_request.json, example_request.json

docs/                        ARCHITECTURE.md  BUDGET.md  EVAL.md  RUNBOOK.md  TECHNICAL.md
```

## Phases complete

**Phase 1** — Core tokenizer + priority packing + drop (offline, `context_assembly.py`).

**Phase 2** — `Block(name, text, family, priority, compress)` families: `memory | docs | tools`.
`Decision` per block carries `action`, `reason`, `tokens_original`, `tokens_used`.
`providers.py` — compress chain, all providers optional, offline-safe.

**Phase 3** — `src/` package: 3-pass allocator (A force-keep / B soft-cap / C borrow),
`BudgetPolicy` + four YAML policies, `pack()` → chat messages, `run_compress_jobs()`,
CLI (`python -m src.assembly`), Streamlit UI (`src/ui/app.py`), `run.cmd`.

## Run

```cmd
run.cmd            # Streamlit UI at http://localhost:8501
uv run python -m src.assembly --request tests/fixtures/sample_request.json --policy balanced --out out/pack.json
uv run python test_context_assembly.py   # legacy self-check
uv run pytest                            # full suite (69 checks)
uv run python tests/eval/run_eval.py     # 6 eval cases; overflow_count must be 0
```
