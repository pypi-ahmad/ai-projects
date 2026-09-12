"""Fine-tuning pipeline control panel. Top of the stack: it calls into src.data.generate and
src.eval.baseline as subprocesses and reads reports/bakeoff.md, but nothing else imports this file.
Must not run full training itself — see train.cmd. Run with: streamlit run src/ui/app.py
(or just run.cmd, which does exactly that).
"""

import subprocess
import sys
from collections import Counter
from pathlib import Path

import pandas as pd
import streamlit as st

from src.data.schema import load_examples
from src.eval.baseline import FIELDS

# Resolved from this file's own path, not the process cwd — so subprocess calls below and the
# data/reports/outputs paths resolve correctly no matter what directory `streamlit run` was
# launched from.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data" / "processed"
REPORTS_DIR = PROJECT_ROOT / "reports"
TRAIN_LOG = PROJECT_ROOT / "outputs" / "train.log"

st.set_page_config(page_title="Fine-Tuning Pipeline", layout="wide")
st.title("Fine-tuning pipeline")


def run_cli(module: str, args: list[str]) -> subprocess.CompletedProcess:
    # Blocking: the whole page is unresponsive until the subprocess exits (st.spinner at the call
    # site just shows that it's stuck, not that anything is happening in the background).
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )


def show_log(result: subprocess.CompletedProcess) -> None:
    with st.expander("Log"):
        st.code((result.stdout or "") + (result.stderr or "") or "(no output)", language="text")


st.header("Dataset preview")
jsonl_files = sorted(DATA_DIR.glob("*.jsonl")) if DATA_DIR.exists() else []
if jsonl_files:
    chosen = st.selectbox("File", jsonl_files, format_func=lambda p: p.name)
    examples = load_examples(chosen)
    st.caption(f"{len(examples)} rows")
    cols = st.columns(len(FIELDS))
    for col, field in zip(cols, FIELDS, strict=True):
        counts = Counter(getattr(ex.target, field) for ex in examples)
        with col:
            st.caption(field)
            st.bar_chart(pd.Series(counts, name="count").sort_index())
else:
    st.info("No `data/processed/*.jsonl` yet. Generate some below.")

st.divider()
st.header("Actions")

col_gen, col_base = st.columns(2)

with col_gen:
    st.subheader("Generate synthetic data")
    n_train = st.number_input("n-train", min_value=1, value=200, step=10)
    n_val = st.number_input("n-val", min_value=0, value=40, step=10)
    n_test = st.number_input("n-test", min_value=0, value=40, step=10)
    teacher = st.selectbox("Teacher", ["granite4.1:3b", "agnes-2.5-flash", "gpt-5.6-luna"])
    if st.button("Generate data", icon=":material/database:"):
        with st.spinner("Calling src.data.generate — this can take a while..."):
            result = run_cli(
                "src.data.generate",
                [
                    "--n-train", str(n_train),
                    "--n-val", str(n_val),
                    "--n-test", str(n_test),
                    "--teacher", teacher,
                ],
            )
        (st.success if result.returncode == 0 else st.error)(
            "Data generated." if result.returncode == 0 else "Generation failed — see log below."
        )
        show_log(result)

with col_base:
    st.subheader("Run baseline eval")
    model = st.selectbox("Model", ["qwen3.5:0.8b", "qwen3.5:2b"])
    if st.button("Run baseline", icon=":material/checklist:"):
        test_file = DATA_DIR / "test.jsonl"
        if not test_file.exists():
            st.error(f"`{test_file}` does not exist yet — generate data first.")
        else:
            with st.spinner(f"Calling src.eval.baseline --model {model} ..."):
                result = run_cli("src.eval.baseline", ["--model", model])
            (st.success if result.returncode == 0 else st.error)(
                "Baseline eval done." if result.returncode == 0 else "Baseline eval failed — see log below."
            )
            show_log(result)

st.divider()
st.header("Training")
st.info(
    "Full training does not run from this UI. Use **train.cmd** "
    "(or `train.cmd --config configs\\train_smoke.yaml` for a 2-step smoke test) from a terminal."
)
if st.button("Train", icon=":material/model_training:"):
    st.warning("Not started here — use train.cmd. See the note above.")

st.divider()
st.header("Training log")
if TRAIN_LOG.exists():
    # st.fragment re-executes only this function on the timer, not the whole page/script.
    @st.fragment(run_every="3s")
    def tail_log() -> None:
        lines = TRAIN_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
        st.code("\n".join(lines[-200:]) or "(empty)", language="text")

    tail_log()
else:
    st.caption(f"No log at `{TRAIN_LOG.relative_to(PROJECT_ROOT)}` — nothing running.")

st.divider()
st.header("Last bake-off")
bakeoff_md = REPORTS_DIR / "bakeoff.md"
if bakeoff_md.exists():
    st.markdown(bakeoff_md.read_text(encoding="utf-8"))
else:
    st.info("No bake-off yet — adapter missing. Run train.cmd, then `python -m src.eval.bakeoff`.")
