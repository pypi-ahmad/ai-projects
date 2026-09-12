# LLM Engineering Projects

A tutorial monorepo of 16 independent Python projects covering retrieval, structured output, context
management, evaluation, caching, routing, agents, and document parsing. Each numbered folder has its own
code, dependencies, environment, launcher, and README. Study one component or follow the full path; these
projects are not wired together into one application.

## Suggested order

Follow **1 → 16**: start with RAG, explore the components around an LLM call, then build toward tool use,
a RAG agent, and document parsing. This is a learning path, not an installation dependency.

| If you only want… | Start here |
| --- | --- |
| A demo without a model service or API key | [3 — Context Assembly](3-Context-Assembly-Service/README.md) |
| Questions answered from documents | [1 — RAG](1-Production-RAG-Pipeline/README.md), then [15 — RAG Agent](15-Self-Correcting-RAG-Agent/README.md) |
| Validated JSON from text | [2 — Structured Output](2-Structured-Output-Engine/README.md) |
| Quality evaluation or prompt experiments | [4 — Evaluation](4-LLM-Evaluation-Harness/README.md) or [12 — Prompt Versioning](12-Prompt-Versioning-and-AB-System/README.md) |
| Cost, latency, and serving | [5 — Cache](5-Semantic-Cache-Layer/README.md), [6 — Routing](6-Model-Routing-Gateway/README.md), or [11 — Streaming](11-Streaming-Response-Infrastructure/README.md) |
| Agent memory or tool use | [9 — Memory](9-Agent-Memory-System/README.md) or [14 — Tools](14-Tool-Calling-Framework/README.md) |
| Fine-tuning | [8 — Fine-Tuning](8-Fine-Tuning-Pipeline/README.md) |
| PDF/image parsing | [16 — Document Extraction](16-Agentic-Document-Extraction/README.md) |

## Run one project

Use a native Windows terminal. Install [uv](https://docs.astral.sh/uv/) and check the chosen child's
Python requirement before setup. Launchers that call `python` directly also need a compatible Python on
`PATH`. Python versions differ between children; there is no root environment or root dependency-install
command.

From your clone's root, try the context-packing demo:

```powershell
Set-Location .\3-Context-Assembly-Service
.\run.cmd
```

This installs only project 3's dependencies and opens its Streamlit UI. Click **Load sample**, leave
compression **off**, and click **Assemble**. Packing needs no GPU, Ollama, or API key; initial
dependency/tokenizer downloads can still need internet access.

For another project, enter its numbered folder and follow its start line below. Always launch from inside
that folder: some scripts rely on the current directory. Keep each child's `.venv` separate. Project 8
needs `uv sync` before its launcher; the other launchers include dependency setup. Many apps share port
`8501` or `8000`, so start with one project at a time.

## Shared conventions and exceptions

- **Native Windows:** all 16 folders contain `run.cmd`. Some launchers use uv; others use plain Python/venv/pip. Follow the chosen child's setup instead of combining dependency files. No child requires WSL2 for this local path; consult its own documentation for any alternative platform.
- **Hardware:** there is no monorepo-wide GPU requirement. Project 8's documented training setup uses an NVIDIA CUDA GPU. Several local-model projects target an 8 GB GPU, while packing, rule checks, registry operations, and synthetic demos can run without one.
- **Ollama:** needed only for features that call it. Start the service and pull the selected project's models; `ollama list` checks reachability and installed tags. A cloud generation option does not remove a separate local embedding dependency.
- **Credentials:** configure only the provider or service you use. Every child has an empty-value `.env.example`; the [root catalog](.env.example) lists the union and project references, not a shared configuration to load. Follow each template's loading notes and remove unused empty assignments to preserve defaults. There is no shared root `.env` loader. Projects **2, 8, 9, 10, 11, 12, 13, and 14 do not automatically load `.env`**: use their process/shell environment. Project 2 can copy a template without loading its values.

### Ollama model selection

There is **no single allowlist enforced across all projects**. Several children reuse this catalogue;
others use smaller registries or a configurable model name. The selected child's provider/config code
determines what each operation accepts. Pull only what you need.

| Model tag | Role where implemented |
| --- | --- |
| `granite4.1:3b` | Chat/generation |
| `qwen3.5:2b` | Chat, compression, or judging |
| `qwen3.5:0.8b` | Small chat model, repair, compression, or reranking |
| `qwen3-vl:2b` | Vision/OCR |
| `qwen3-embedding:0.6b` | Default local embeddings |
| `qwen3-embedding:4b` | Alternative embeddings; existing indexes may need rebuilding |
| `translategemma:4b` | Translation |
| `AuditAid/PaddleOCR-VL-1.6-0.9B` | OCR in projects that wire it in |

See [project 1's catalogue](1-Production-RAG-Pipeline/src/rag_pipeline/config.py) for one concrete
definition. A listed embedding or OCR model is not automatically a chat model for every project.

### Environment-variable names

| Setting | Applies to |
| --- | --- |
| `OPENAI_API_KEY` and usually `OPENAI_BASE_URL` | Children with an OpenAI-compatible provider; project 16 allows the default OpenAI URL |
| `GOOGLE_API_KEY` | Children with a Gemini implementation; check whether that provider is enabled |
| `AGNES_API_KEY` or `AGNESAI_API_KEY` | Name varies by child; these are not universally interchangeable |
| `ADMIN_TOKEN`, `PROMPTREG_ADMIN_TOKEN`, `OBS_ADMIN_TOKEN` | App-specific administration in projects 7, 12, and 13 respectively |

Use the child's configuration section for exact names, defaults, and `.env` support. No cloud key is
needed for local Ollama calls.

## Projects

Run each start command **inside the linked numbered folder**. Each child README contains the longer
walkthrough, configuration, tests, and limitations.

### 1. [Production RAG Pipeline](1-Production-RAG-Pipeline/README.md)

Build a document-to-answer pipeline: ingest mixed files, chunk them, combine dense and BM25 retrieval,
rerank, and generate cited answers. Start with `data/raw/sample/`, run ingestion/indexing, then ask a
question. Ollama is needed for local embeddings and reranking even with cloud answer generation; the
documented local setup targets an 8 GB NVIDIA GPU. Cloud keys are optional. Inspect sources rather than
assuming citations prove correctness.

Start: `.\run.cmd` — Streamlit UI.

### 2. [Structured Output Engine](2-Structured-Output-Engine/README.md)

Build a text-to-schema pipeline with JSON extraction, Pydantic validation, retries, model-based repair,
and typed failures. Try `invoice_draft` with pasted text. The default generation and repair paths need
Ollama; a cloud provider needs its environment credentials. Repair still defaults to local `qwen3.5:0.8b`
unless you pin the provider. Image/PDF OCR is optional and requires additional dependencies.

Start: `.\run.cmd` — Streamlit UI.

### 3. [Context Assembly Service](3-Context-Assembly-Service/README.md)

Build a token-budgeted packer for supplied memory, document, and tool blocks, with a report of what was
kept, marked for compression, or dropped. Load the sample and export the packed messages as JSON. Packing
needs no GPU, Ollama, or API credentials. Optional model-based compression uses Ollama or a configured
cloud provider; the caller supplies the blocks rather than this service retrieving them.

Start: `.\run.cmd` — Streamlit UI.

### 4. [LLM Evaluation Harness](4-LLM-Evaluation-Harness/README.md)

Build a quality-checking workflow using fixed datasets, deterministic metrics, an optional validated LLM
judge, baselines, and regression gates. Live candidates/judges need Ollama or the chosen cloud provider's
credentials. Scoring frozen candidate fixtures needs neither a GPU nor a live model. The root [evaluation
workflow](.github/workflows/llm-eval.yml) uses that fixture path when cloud secrets are absent.

Start: `.\run.cmd` — Streamlit UI; CLI stages are documented in the child README.

### 5. [Semantic Cache Layer](5-Semantic-Cache-Layer/README.md)

Build a similarity cache for query/answer pairs with Ollama embeddings and embedded Qdrant, inspecting
hits, misses, scores, and metrics. Every lookup needs Ollama with `qwen3-embedding:0.6b` pulled. The
documented setup uses an 8 GB GPU; Qdrant needs no separate server. Cloud keys are only for an optional
generate-on-miss demo. Changing the embedding model requires rebuilding the cache.

Start: `.\run.cmd` — Streamlit UI. After setup, the child's seed script supplies demo FAQs.

### 6. [Model Routing Gateway](6-Model-Routing-Gateway/README.md)

Build a router that chooses a cost tier, tries eligible targets, promotes after failures, and records
latency and estimated token cost. Live requests need Ollama or configured cloud credentials; unavailable
providers are skipped. Routing logic and its decision-only evaluation need no GPU. The UI shows requests,
routing results, and usage; cost figures are configuration estimates, not provider bills.

Start: `.\run.cmd` — Streamlit UI.

### 7. [Multi-Tenant LLM API](7-Multi-Tenant-LLM-API/README.md)

Build tenant authentication, rate limits, monthly token budgets, provider forwarding, and usage records,
with an admin UI for tenants and keys. Set `ADMIN_TOKEN` before starting and enter it in the UI for admin
operations. Services can start without Ollama, but real chat needs a reachable local model or configured
cloud provider. SQLite quota enforcement is not designed for multiple API processes.

Start: `.\run.cmd` — API on `8000`, admin UI on `7011`.

### 8. [Fine-Tuning Pipeline](8-Fine-Tuning-Pipeline/README.md)

Build synthetic support-ticket data, fine-tune `Qwen/Qwen3.5-0.8B` with LoRA/QLoRA, and compare the
adapter with an Ollama prompt-only baseline. The documented training path needs an NVIDIA CUDA GPU;
fallback paths are unverified. Ollama supports local generation/baselines; cloud teacher/judge options
need their keys. Generate data before training: datasets, adapters, and reports are excluded from a fresh
clone. The UI does not start training.

Start: `uv sync`, then `.\run.cmd` for the UI. After dataset preparation, use `.\train.cmd` for training.

### 9. [Agent Memory System](9-Agent-Memory-System/README.md)

Build working, episodic, and semantic memory with eviction, compression, fact distillation, and
token-budgeted recall. Full memory flows need Ollama with `qwen3-embedding:0.6b` and `qwen3.5:0.8b`; the
UI can still expose working/episodic memory when Ollama is unavailable. No cloud credentials are needed:
that provider module is a stub. Your caller must trigger maintenance; this library is not an autonomous
agent or scheduler.

Start: `.\run.cmd` — Streamlit inspector on `7013`.

### 10. [Guardrails Middleware](10-Guardrails-Middleware/README.md)

Build input/output checks for PII and prompt-injection patterns, inspect allow/transform/block decisions,
and wrap a caller-supplied model function. Default rule checks need no GPU, Ollama, or API keys. Optional
local-model classification and embedding checks need Ollama when enabled. The bundled HTTP wrapper uses
an echo provider by default. These heuristic checks can produce false positives and false negatives.

Start: `.\run.cmd` — API on `8000`, playground UI on `7014`.

### 11. [Streaming Response Infrastructure](11-Streaming-Response-Infrastructure/README.md)

Build an SSE service with backpressure, buffered reconnects through `Last-Event-ID`, and
time-to-first-token metrics. The fake provider needs no GPU, Ollama, or API keys; live providers need
their service or credentials. Try the browser demo at `http://127.0.0.1:8000/client.html`. Sessions are
in-process and lost on restart. Gemini's adapter exists but is disabled in the current provider
configuration.

Start: `.\run.cmd` — API only. For the optional UI, run `uv run streamlit run src/stream/ui.py` in a second terminal in the same folder.

### 12. [Prompt Versioning and A/B System](12-Prompt-Versioning-and-AB-System/README.md)

Build a SQLite-backed prompt registry with immutable versions, environment pointers, rollback, sticky
weighted experiments, and outcome tracking. No GPU, Ollama, or model API keys are needed: execution is
dry until a completer is registered, and none is wired in by default. The API generates an admin token
unless `PROMPTREG_ADMIN_TOKEN` is set; the UI accesses the stores directly.

Start: `.\run.cmd` — API on `8000`, UI on `7016`.

### 13. [LLM Observability Stack](13-LLM-Observability-Stack/README.md)

Build local trace storage and inspection for latency, token usage, cost, and alerts with SQLite/JSONL,
FastAPI, and a Streamlit viewer. Seed synthetic traces to explore without a model service or API key.
Only the optional traced-completion demo needs Ollama. Alert evaluation is a one-shot command, not a
scheduler. Prompt previews are stored; full-prompt storage is opt-in.

Start: `.\run.cmd` — API on `8000`, viewer on `7017`.

### 14. [Tool-Calling Framework](14-Tool-Calling-Framework/README.md)

Build a registry of typed Python tools and an LLM loop that parses arguments, validates them, checks
permissions, and executes calls. Manual calculator, clock, JSON-query, and note-tool calls need no model;
chat needs Ollama or a configured cloud provider. The guards support local demonstrations, not hostile
multi-tenant isolation, and a timed-out thread can keep running.

Start: `.\run.cmd` — API on `8765`, UI on `7018`.

### 15. [Self-Correcting RAG Agent](15-Self-Correcting-RAG-Agent/README.md)

Build a loop that rewrites questions, retrieves dense/lexical evidence, critiques it, and answers with
citations, retries, searches the web, or abstains. The launcher indexes the bundled wiki on first run.
The default path needs Ollama for models and embeddings; cloud generation is optional. Web fallback
additionally needs `SEARCH_API_KEY` and `SEARCH_BASE_URL`. Current ingestion skips scanned pages rather
than OCRing them.

Start: `.\run.cmd` — builds the demo index if absent, then opens the UI on `7019`.

### 16. [Agentic Document Extraction](16-Agentic-Document-Extraction/README.md)

Build a vision-model parser producing layout-aware Markdown/HTML and annotated PDF/PNG outputs for human
review. The active graph is preprocess → parse; the older invoice-validation and commit/review flow is
disconnected. Parsing needs `OPENAI_API_KEY` and access to a configured Terra/Luna model; set
`OPENAI_BASE_URL` for a compatible gateway. No Ollama or local GPU is required. The launcher stops any
process already listening on `5805`, so free that port first.

Start: `.\run.cmd` — UI on `5805`; upload a document and click **Parse**.

## Security

Treat this as a public repository. Never commit `.env`, real keys, private documents, or runtime dumps
containing prompts/responses. Keep credentials in the shell environment or an ignored child `.env` where
supported; use empty placeholders in `.env.example`. Indexes, databases, model weights, caches, and
generated document outputs stay outside the publication candidate. See [.gitignore](.gitignore) and
[SECRET_SCAN.md](SECRET_SCAN.md).

Public source does not mean the demo servers are safe to expose publicly. Read each child's security and
limitations notes before changing its bind address or using sensitive input.

## License

The root [LICENSE](LICENSE) contains the MIT License. External model weights and dependencies retain
their own licenses.
