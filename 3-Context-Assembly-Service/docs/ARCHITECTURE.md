# Architecture

## What this service is — and is not

The Context Assembly Service is a **token budgeter and packer**. It receives a list of candidate
blocks that the *caller* has already selected and ranked, fits them into a token window, and
returns chat-ready messages plus a decision report.

**It does not retrieve documents.** There is no embedding model, no vector store, and no RAG
index. The caller is responsible for selecting candidate blocks and assigning priorities before
calling the assembler.

## Request flow

```
ContextRequest
  blocks: list[ContextBlock]   ← caller-supplied; already fetched/selected
  user_message: str
  context_window / model_name
  reserve_output_tokens
  policy
        │
        ▼
  TokenCounter.count_request()    tiktoken cl100k_base; pure offline
        │
        ▼
  allocate(request, policy)       3-pass allocation engine
  ┌────────────────────────────────────────────────────────────┐
  │ Pass A  force-keep highest-priority block per family       │
  │ Pass B  fill remaining within per-family soft caps         │
  │ Pass C  borrow surplus across families                     │
  │         overflow + compressible → CompressJob              │
  │         overflow + not compressible → DropRecord           │
  └────────────────────────────────────────────────────────────┘
        │  AllocationPlan
        │    .kept           list[ContextBlock]
        │    .compress_jobs  list[CompressJob]
        │    .dropped        list[DropRecord]
        │
        ▼  (optional)
  run_compress_jobs(plan, provider_fn)
    provider chain: Ollama → Agnes AI → OpenAI-compat → Gemini
    OK / TRIMMED   → block moves to kept with updated text
    UNAVAILABLE / FAILED → block moves to dropped
        │
        ▼
  pack(request, plan, policy)
        │  PackResult
        │    .messages     [{role, content}]   chat-API ready
        │    .packed_text  str                 flat single-string view
        │    .report       BudgetReport        window / reserves / per-family stats
        ▼
  caller → LLM API
```

## Module map

```
context_assembly.py          Legacy flat API (Block, Decision, AssemblyResult, assemble())
providers.py                 compress() provider chain; ollama_unload()
src/
  blocks/
    models.py                ContextBlock · ContextRequest · Family
    tokenizer.py             TokenCounter (tiktoken cl100k_base)
  budget/
    policy.py                BudgetPolicy · FamilyCaps · load_policy()
    allocator.py             AllocationPlan · allocate() · DropReason
  assembly/
    packer.py                PackResult · BudgetReport · pack()
    __main__.py              CLI:  python -m src.assembly --request … --out …
  compress/
    compressor.py            CompressResult · compress_one() · run_compress_jobs()
  ui/
    app.py                   Streamlit front-end
  eval/                      stub (__init__.py with one comment; no implementation)
  providers/                 stub (__init__.py with one comment; no implementation)
config/policies/             balanced · docs_heavy · tools_heavy · memory_heavy (YAML)
data/model_windows.yaml      per-model context window lookup table
tests/
  test_blocks.py             16 checks
  test_budget.py             15 checks
  test_packer.py             19 checks
  test_compress.py           19 checks
  eval/cases.jsonl           6 eval cases
  eval/run_eval.py           eval runner + metrics
```

## Key constraints

- Offline path: tiktoken only; zero network calls; no env vars required.
- One Ollama model at a time (RTX 4060 8 GB VRAM ceiling).
- No RAG index, no agent runtime, no training. Caller supplies candidate blocks.
