# Phase 0; Kickoff

**Implement** Agentic Document Extraction (ADE) for invoices as a LangGraph state machine, working only within this repo's project root.

**Flow:** `preprocess → extract (gpt-5.6-terra + Pydantic Invoice) → Python math validate → (optional low-confidence crop/re-read → retry extract with error text, up to N times) → commit or human review (HITL)`. The model proposes fields; Python is the only thing that commits them; no silent number fixes.

**Also required:**
- Crop low-confidence or math-failing regions when the model returns bounding boxes; if it returns none, skip cropping and retry the full page instead.
- HITL review after N failed retries.
- An audit trail as JSONL.

**Environment:** Native Windows 11 only; no WSL2, no Docker, Windows paths, one double-clickable `run.cmd`. Frontend is Streamlit.

**Model configuration (v1):**
- `ChatOpenAI(model="gpt-5.6-terra", temperature=0)`
- `OPENAI_API_KEY` from the environment; `OPENAI_BASE_URL` from the environment if set (for OpenAI-compatible gateways)
- Reasoning effort medium, only if compatible with structured output. If the installed library errors when both are set, drop reasoning effort and document that it was omitted; do not drop structured output instead.
- `with_structured_output(Invoice, method="json_schema")` when that argument exists in the installed library.

**Constraints:**
- Look up current LangGraph, `langchain-openai.ChatOpenAI`, `with_structured_output`, and multimodal `HumanMessage` image-block APIs before using them. Do not invent APIs or copy unverified sample code.
- Non-goals: LandingAI/Reducto APIs, other LLM brands, RAG, training, Docker, unrestricted multi-agent chat.

**Process:** Work one phase at a time. Each phase implements only that phase's scope, updates that phase's docs, and stops; reporting the files created and what the next phase can assume.
