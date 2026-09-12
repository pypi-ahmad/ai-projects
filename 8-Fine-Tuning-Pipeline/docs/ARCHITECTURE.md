# Architecture

This describes the pipeline as it exists in `src/`, not an intended future design.

## Data/process flow

```mermaid
flowchart TD
    Teacher["Teacher model<br/>(src/providers: OllamaTeacher or OpenAICompatTeacher)"]
    Gen["src/data/generate.py<br/>generate_rows / parse_generated_row"]
    Data["data/processed/train.jsonl, val.jsonl, test.jsonl<br/>(TicketExample rows)"]

    Teacher --> Gen --> Data

    Prompt["configs/baseline_prompt.txt"]

    subgraph Baseline["src/eval/baseline.py"]
        BEval["run_baseline / score_one<br/>OllamaTeacher.chat, temperature 0"]
        BParse["parse_ticket_target"]
        BReport["reports/baseline_MODEL.json<br/>+ _errors.csv"]
        BEval --> BParse --> BReport
    end
    Data --> BEval
    Prompt --> BEval

    subgraph Train["src/train/run.py"]
        Load["AutoModelForCausalLM + BitsAndBytesConfig<br/>base_model_id from configs/train.yaml"]
        Lora["peft LoraConfig + TRL SFTTrainer<br/>completion_only_loss"]
        Adapter["outputs/adapters/RUN_ID/<br/>adapter_model.safetensors + train_meta.json"]
        Load --> Lora --> Adapter
    end
    Data --> Load
    Prompt --> Lora

    subgraph Bakeoff["src/eval/bakeoff.py"]
        LAM["LocalAdapterModel.chat<br/>(base model + PeftModel.from_pretrained)"]
        BOReport["reports/lora_RUN_ID.json"]
        BOmd["write_bakeoff_md<br/>reports/bakeoff.md"]
        LAM --> BOReport --> BOmd
    end
    Adapter --> LAM
    Data --> LAM
    Prompt --> LAM
    BReport --> BOmd

    subgraph UI["src/ui/app.py (Streamlit)"]
        Preview["dataset histogram"]
        BtnGen["Generate data button<br/>subprocess -m src.data.generate"]
        BtnBase["Run baseline button<br/>subprocess -m src.eval.baseline"]
        LogTail["st.fragment log tail"]
        BOView["Last bake-off view"]
    end
    Data --> Preview
    BtnGen -.spawns.-> Gen
    BtnBase -.spawns.-> BEval
    BOmd --> BOView

    Ollama[("Ollama HTTP API<br/>localhost:11434")]
    HFHub[("Hugging Face Hub")]
    Cloud[("Agnes AI / OpenAI HTTP APIs<br/>optional")]

    Ollama --> Teacher
    Ollama --> BEval
    HFHub --> Load
    Cloud -.optional teacher/judge.-> Teacher
```

## Main types/state, and where they live

- **Pydantic models** — `src/data/schema.py`: `TicketTarget` (the 4-field label enum),
  `GeneratedRow` (ticket text + label, as produced by the teacher), `TicketExample` (input, target,
  split, source, teacher_model — the persisted row shape). `load_examples` reads a jsonl file into
  a `list[TicketExample]`.
- **Provider clients** — `src/providers/base.py` defines two `Protocol`s: `TeacherClient`
  (`.complete(prompt)`) and `ChatClient` (`.chat(system, user, temperature)`). `OllamaTeacher`
  (`src/providers/ollama.py`) and `OpenAICompatTeacher` (`src/providers/cloud.py`) implement both;
  `LocalAdapterModel` in `src/eval/bakeoff.py` implements `ChatClient` only, so it can be scored by
  the same `run_baseline` function as the Ollama-backed baseline.
- **On-disk state:**
  - `data/processed/*.jsonl` — one `TicketExample` per line.
  - `outputs/adapters/<run_id>/` — `adapter_model.safetensors`, `adapter_config.json`,
    tokenizer files, and `train_meta.json` (the training config actually used, VRAM peak, steps,
    final loss — see `src/train/run.py`'s `meta` dict).
  - `reports/baseline_<model>.json` / `lora_<run_id>.json` — output of `aggregate_metrics` in
    `src/eval/baseline.py`, plus a `_errors.csv` of the non-exact-match rows.
  - `reports/bakeoff.md` — human-readable comparison table and verdict text
    (`write_bakeoff_md`/`write_adapter_missing_md` in `src/eval/bakeoff.py`).
  - `outputs/train.log` — written by `train.cmd`'s `Tee-Object`, read by the Streamlit UI's log
    tail. Not written by any Python code in this repo — only by the batch script.

## External systems the code calls

- **Ollama's local HTTP API** (`http://localhost:11434`, the default in
  `src/providers/ollama.py`) — `/api/generate` (`OllamaTeacher.complete`) and `/api/chat`
  (`OllamaTeacher.chat`). Used for the teacher (data generation), the prompt-only baseline, and the
  repair pass.
- **Hugging Face Hub** — `AutoModelForCausalLM.from_pretrained` / `AutoTokenizer.from_pretrained`
  in `src/train/run.py` and `src/eval/bakeoff.py` download the base model
  (`base_model_id` in `configs/train.yaml`) from `huggingface.co` over the network the first time
  it's used (then cached locally by `huggingface_hub`).
- **Agnes AI / OpenAI HTTP APIs** (`https://apihub.agnes-ai.com/v1`, `https://api.openai.com/v1` —
  both literal URLs in `src/providers/__init__.py`) — only called if a teacher/judge argument
  selects `agnes-2.5-flash` or `gpt-5.6-luna`; not used by any default flag value in this repo.
