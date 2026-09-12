# Design Notes

Same harness/conventions as the Structured Output Engine project: native
Windows 11, no WSL2, no Docker.

## Model map (4060 8 GB)

| Job | Model |
|---|---|
| Query + cached-key embeddings | `qwen3-embedding:0.6b` (default) |
| Higher-quality embed (rebuild cache) | `qwen3-embedding:4b` |
| Optional "should we cache this?" filter | `qwen3.5:0.8b` |
| Generate on miss | not this repo's job; return a miss and let the caller generate |

## Vector store

Qdrant embedded: `QdrantClient(path=...)` (same as the RAG decision; no
separate server/Docker container).

Payload fields: answer, model id, prompt hash, created_at, hit_count.

`QdrantClient(path="data/cache/qdrant")`; no Chroma, no Docker Qdrant.

## Product

Semantic Cache Layer embeds the incoming query, finds the nearest stored
query, and returns the stored answer on a hit. It tracks hits, misses,
latency, and savings through semantic (embedding-similarity) matching.

Non-goals: full RAG, judge harness, Docker.

Generate-on-miss is out of scope for this repo's core job (return a miss,
let the caller generate); the 4 LLM providers below are only for an
*optional* generate-on-miss demo, not the cache itself.

## Hardware discipline

- Unload the embed model when idle if anything else gets loaded.
- Never load `granite4.1:3b` unless a debug path is explicitly invoked.

## LLM providers (optional generate-on-miss demo only)

1. Ollama; detect installed models.
2. Agnes AI: `agnes-2.5-flash`, `https://apihub.agnes-ai.com/v1`, `AGNES_API_KEY`.
3. OpenAI-compatible: `gpt-5.6-luna`, `gpt-5.6-terra`, medium effort. `OPENAI_API_KEY` + `OPENAI_BASE_URL`.
4. Gemini: `GOOGLE_API_KEY`. `gemini-3.5-flash-lite`, `gemini-3.7-flash`.

## Frontend

Streamlit. Native Windows 11 only; no WSL2, no Docker. One `run.cmd`.

## Process

Each phase: only that phase, update its docs, stop with files created.
