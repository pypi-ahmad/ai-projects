# Stack (Phase 1)

All facts below came from live lookups on 2026-09-12 (HF Hub REST API, PyPI JSON API, or a runtime check in this project's `.venv`) — none invented. Full commands are in scrollback; only the results are recorded here.

## Train base model

- **HF id:** `Qwen/Qwen3.5-0.8B`
- **License:** apache-2.0
- **Params:** 873,438,784 (873.4M) — matches the locally-pulled `ollama show qwen3.5:0.8b` param count (873.44M) exactly, confirming this is the correct twin.
- **Page dates:** created 2026-02-28, last modified 2026-03-02
- **Not gated.**
- **Instruct, not base:** tagged `conversational`, `base_model:finetune:Qwen/Qwen3.5-0.8B-Base` — this repo is the finetuned chat model built on top of the separate `Qwen/Qwen3.5-0.8B-Base` raw checkpoint. We want this one, not `-Base`.
- **Architecture:** `qwen3_5` (`Qwen3_5ForConditionalGeneration`). Confirmed loadable today: `transformers==5.17.0`'s `AutoConfig.from_pretrained("Qwen/Qwen3.5-0.8B")` succeeded live (config.json only, no weights fetched).

## Teacher / judge candidates

- **Local teacher:** `ibm-granite/granite-4.1-3b` — apache-2.0, 3,402,836,480 params, last modified 2026-05-04. Already pulled locally as Ollama `granite4.1:3b`.
- **Cloud alt:** `agnes-2.5-flash` (`AGNESAI_API_KEY`) or `gpt-5.6-luna` (`OPENAI_API_KEY`) — both keys present in this environment, so the cloud path is available for teacher/judge instead of falling back to granite.

## Install verification — native Win11, CUDA, no WSL2/Docker

Actually installed and runtime-tested in this project's `.venv` (Python 3.13.15):

- `torch==2.14.0+cu130` — ran a real matmul on the RTX 4060 Laptop GPU; `torch.cuda.is_available()` is `True`.
- `bitsandbytes==0.50.2` — ran a real `bnb.nn.Linear4bit` forward pass on CUDA. This was the actual Windows risk point; it works.
- `transformers==5.17.0` — loaded the live `Qwen/Qwen3.5-0.8B` config from the Hub (architecture `qwen3_5`).
- `peft==0.20.0`, `trl==1.13.0`, `accelerate==1.15.0` — installed clean; pure-Python wheels, no OS-specific build step.

Two things caught during setup:

1. `uv add torch` alone resolves PyPI's win_amd64 wheel, which is **CPU-only** — PyPI does not host CUDA wheels for Windows. `--torch-backend` only affects `uv pip install`, not project `uv add`/`uv sync`. Fix: added an explicit `[[tool.uv.index]]` for `https://download.pytorch.org/whl/cu130` plus `[tool.uv.sources]` entries for `torch`/`torchvision` gated on `sys_platform == 'win32'`.
2. HF Hub's local cache falls back to full-copy instead of symlinks because Windows Developer Mode isn't enabled — functional, just uses more disk per cached model.

## Unsloth — not used

- PyPI `unsloth==2026.9.4` does declare native Windows markers (`triton-windows; sys_platform == "win32"`, `xformers ...` gated on `linux or win32`), so a Windows install is nominally possible today.
- But it pins `torch<2.13.0,>=2.4.0`, which conflicts with the `torch==2.14.0+cu130` already verified above, and pulls in `triton-windows` (community fork) and `xformers`, historically the two flakiest pieces of the Windows CUDA stack.
- Decision: **do not use it.** transformers + peft + trl + bitsandbytes is already verified end-to-end on this GPU; there's no reason to take on Unsloth's fragility/downgrade for an 873M-parameter model.

## GGUF vs HF PEFT — important

The `qwen3.5:0.8b` / `qwen3.5:2b` Ollama tags are **GGUF**, a quantized *inference* format for
`llama.cpp`/Ollama. **You cannot LoRA/PEFT-train a GGUF file in this repo.** Training
(`src/train/run.py`) loads the separate Hugging Face safetensors checkpoint (`Qwen/Qwen3.5-0.8B`,
see above) and produces a standard Hugging Face **PEFT adapter** (`adapter_model.safetensors` +
`adapter_config.json`). Ollama is used only as the prompt-only baseline and the local teacher —
never as a training target. There is no conversion step in this repo from the trained PEFT
adapter back into a GGUF; merging + reconverting for Ollama serving is out of scope here (see
`RUNBOOK.md` "Known gaps").

## Chosen stack (pinned, as installed — see `requirements.txt` for the full pinned list)

| package | version | added in |
|---|---|---|
| python | 3.13.15 | Phase 1 |
| torch | 2.14.0+cu130 | Phase 1 |
| torchvision | 0.29.0+cu130 | Phase 1 |
| transformers | 5.17.0 | Phase 1 |
| peft | 0.20.0 | Phase 1 |
| trl | 1.13.0 | Phase 1 |
| accelerate | 1.15.0 | Phase 1 |
| bitsandbytes | 0.50.2 | Phase 1 |
| datasets | 5.0.1 | Phase 1 |
| huggingface_hub | 1.31.0 | Phase 1 |
| pydantic | 2.13.5 | Phase 2 |
| requests | 2.34.2 | Phase 2 |
| pyyaml | 6.0.3 | Phase 4 |
| streamlit | 1.63.0 | Phase 6 |
| pandas | 3.0.5 | Phase 6 |
| pytest | 9.1.1 (dev group) | Phase 2 |
