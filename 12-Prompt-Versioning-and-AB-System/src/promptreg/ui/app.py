"""Streamlit registry UI.

Talks directly to Registry/ExperimentStore/OutcomeStore (no HTTP) against
the same data/ paths the API and CLI use (override via PROMPTREG_DB_PATH /
PROMPTREG_PROMPTS_DIR / PROMPTREG_OUTCOMES_JSONL).
"""

from __future__ import annotations

import os

import streamlit as st

from promptreg.outcomes.storage import OutcomeStore
from promptreg.registry.models import PromptConfig
from promptreg.registry.storage import Registry
from promptreg.split.models import Arm
from promptreg.split.storage import ExperimentStore

MIN_ARMS = 2
MAX_ARMS = 6


@st.cache_resource
def get_stores() -> tuple[Registry, ExperimentStore, OutcomeStore]:
    db_path = os.environ.get("PROMPTREG_DB_PATH", "data/registry.db")
    prompts_dir = os.environ.get("PROMPTREG_PROMPTS_DIR", "data/prompts")
    outcomes_jsonl = os.environ.get("PROMPTREG_OUTCOMES_JSONL", "data/outcomes.jsonl")
    registry = Registry(db_path, prompts_dir)
    experiments = ExperimentStore(db_path)
    outcomes = OutcomeStore(db_path, outcomes_jsonl)
    return registry, experiments, outcomes


def _flash(key: str) -> None:
    """Show a message queued by a mutating action right before its `st.rerun()`."""
    if key in st.session_state:
        message, kind = st.session_state.pop(key)
        getattr(st, kind)(message)


def _set_flash(key: str, message: str, kind: str = "success") -> None:
    st.session_state[key] = (message, kind)


def render_versions_tab(registry: Registry, prompt_name: str) -> None:
    versions = registry.list_versions(prompt_name)
    if not versions:
        st.info("No versions yet — publish one in the Publish tab.")
        return

    rows = [
        {
            "version": v.version,
            "label": v.label or "",
            "author": v.author,
            "changelog": v.changelog,
            "created_at": v.created_at,
            "sha256": v.sha256[:12],
        }
        for v in versions
    ]
    st.dataframe(rows, width="stretch", hide_index=True)

    col1, col2 = st.columns(2)
    for col, env in ((col1, "prod"), (col2, "staging")):
        pointer = registry.get_pointer(prompt_name, env)
        col.metric(env, f"v{pointer.version}" if pointer else "(unset)")


def render_publish_tab(registry: Registry, prompt_name: str) -> None:
    flash_key = f"publish_flash::{prompt_name}"
    _flash(flash_key)

    st.caption("Publishing always creates a new version — nothing is edited in place.")
    with st.form(f"publish_form::{prompt_name}", clear_on_submit=True):
        body = st.text_area("Body", height=200, placeholder="Hello, {name}!")
        col1, col2 = st.columns(2)
        model = col1.text_input("Model", value="stub")
        provider = col2.text_input("Provider", value="stub")
        col3, col4 = st.columns(2)
        temperature = col3.number_input("Temperature", value=0.0, step=0.1)
        max_tokens = col4.number_input("Max tokens", value=0, step=1, min_value=0)
        author = st.text_input("Author")
        changelog = st.text_input("Changelog")
        label = st.text_input("Label (optional)")
        description = st.text_input("Description (optional, used on first publish only)")
        submitted = st.form_submit_button("Publish new version")

    if not submitted:
        return
    if not body or not author or not changelog:
        st.error("Body, author, and changelog are required.")
        return

    config = PromptConfig(
        model=model,
        provider=provider,
        temperature=temperature or None,
        max_tokens=int(max_tokens) or None,
    )
    version = registry.publish(
        prompt_name,
        body,
        config,
        changelog,
        author,
        description=description or None,
        label=label or None,
    )
    _set_flash(flash_key, f"Published v{version.version}.")
    st.rerun()


def render_pointer_tab(registry: Registry, prompt_name: str) -> None:
    flash_key = f"pointer_flash::{prompt_name}"
    _flash(flash_key)

    versions = registry.list_versions(prompt_name)
    if not versions:
        st.info("No versions yet.")
        return
    version_numbers = [v.version for v in versions]

    for env in ("prod", "staging"):
        st.subheader(env)
        pointer = registry.get_pointer(prompt_name, env)
        st.write(f"Current: v{pointer.version}" if pointer else "Current: (unset)")

        col1, col2, col3 = st.columns([2, 1, 1])
        target = col1.selectbox(
            "Version", options=version_numbers, key=f"ptr_target::{prompt_name}::{env}"
        )
        if col2.button("Set pointer", key=f"ptr_set::{prompt_name}::{env}"):
            registry.set_pointer(prompt_name, env, target)
            _set_flash(flash_key, f"{env}: pointer set to v{target}.")
            st.rerun()
        if col3.button("Roll back", key=f"ptr_rollback::{prompt_name}::{env}"):
            try:
                rolled = registry.rollback(prompt_name, env)
            except ValueError as exc:
                st.error(str(exc))
            else:
                _set_flash(flash_key, f"{env}: rolled back to v{rolled.version}.")
                st.rerun()


def _render_experiment_create_form(
    experiments: ExperimentStore, prompt_name: str, version_numbers: list[int], flash_key: str
) -> None:
    st.subheader("Create experiment")
    num_arms = int(
        st.number_input(
            "Number of arms",
            min_value=MIN_ARMS,
            max_value=MAX_ARMS,
            value=MIN_ARMS,
            step=1,
            key=f"num_arms::{prompt_name}",
        )
    )
    with st.form(f"exp_form::{prompt_name}", clear_on_submit=True):
        exp_name = st.text_input("Experiment name")
        arm_inputs = []
        for i in range(num_arms):
            col1, col2, col3 = st.columns(3)
            arm_name = col1.text_input(
                "Arm name", value=f"arm_{i + 1}", key=f"arm_name::{prompt_name}::{i}"
            )
            arm_version = col2.selectbox(
                "Version", options=version_numbers, key=f"arm_version::{prompt_name}::{i}"
            )
            arm_weight = col3.number_input(
                "Weight",
                min_value=0,
                max_value=100,
                value=100 // num_arms,
                key=f"arm_weight::{prompt_name}::{i}",
            )
            arm_inputs.append((arm_name, arm_version, arm_weight))
        st.caption("Weights across all arms must sum to exactly 100.")
        submitted = st.form_submit_button("Create experiment (draft)")

    if not submitted:
        return
    if not exp_name:
        st.error("Experiment name is required.")
        return
    try:
        arms = [
            Arm(name=name, version=version, weight=int(weight))
            for name, version, weight in arm_inputs
        ]
        experiment = experiments.create_experiment(exp_name, prompt_name, arms)
    except ValueError as exc:
        st.error(str(exc))
        return
    _set_flash(flash_key, f"Created experiment #{experiment.id} (draft).")
    st.rerun()


def _render_experiment_list(experiments: ExperimentStore, prompt_name: str, flash_key: str) -> None:
    st.subheader("Existing experiments")
    existing = experiments.list_experiments(prompt_name)
    if not existing:
        st.info("None yet.")
        return
    for exp in existing:
        with st.container(border=True):
            st.write(f"#{exp.id} **{exp.name}** — {exp.status}")
            st.caption(", ".join(f"{a.name}={a.weight} (v{a.version})" for a in exp.arms))
            col1, col2 = st.columns(2)
            if col1.button("Start", key=f"start::{exp.id}", disabled=exp.status == "running"):
                try:
                    experiments.set_status(exp.id, "running")
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    _set_flash(flash_key, f"Experiment #{exp.id} started.")
                    st.rerun()
            if col2.button("Stop", key=f"stop::{exp.id}", disabled=exp.status == "stopped"):
                experiments.set_status(exp.id, "stopped")
                _set_flash(flash_key, f"Experiment #{exp.id} stopped.")
                st.rerun()


def render_experiments_tab(
    registry: Registry, experiments: ExperimentStore, prompt_name: str
) -> None:
    flash_key = f"exp_flash::{prompt_name}"
    _flash(flash_key)

    versions = registry.list_versions(prompt_name)
    if not versions:
        st.info("Publish at least one version before creating an experiment.")
        return
    version_numbers = [v.version for v in versions]

    _render_experiment_create_form(experiments, prompt_name, version_numbers, flash_key)
    _render_experiment_list(experiments, prompt_name, flash_key)


def render_outcomes_tab(
    experiments: ExperimentStore, outcomes: OutcomeStore, prompt_name: str
) -> None:
    existing = experiments.list_experiments(prompt_name)
    if not existing:
        st.info("No experiments for this prompt yet.")
        return

    options = {f"#{e.id} {e.name} ({e.status})": e.id for e in existing}
    choice = st.selectbox(
        "Experiment", options=list(options.keys()), key=f"outcomes_exp::{prompt_name}"
    )
    experiment_id = options[choice]

    summary = outcomes.summary(experiment_id)
    if not summary:
        st.info("No outcomes recorded for this experiment yet.")
        return

    rows = [
        {
            "arm": arm,
            "n": stats["count"],
            "ok_rate": round(stats["ok_rate"], 3),
            "thumbs_net": stats["thumbs_net"],
            "p50_latency_ms": round(stats["p50_latency_ms"], 2),
        }
        for arm, stats in sorted(summary.items())
    ]
    st.dataframe(rows, width="stretch", hide_index=True)
    st.caption(
        "Descriptive counts only — no significance testing or Bayesian claims. "
        "Small n means these numbers can swing a lot; don't over-read them."
    )


st.set_page_config(page_title="promptreg", page_icon="📋", layout="wide")

registry, experiments, outcomes = get_stores()

st.title("promptreg")

with st.sidebar:
    st.header("Prompt")
    prompt_names = registry.list_prompts()
    choice = st.selectbox(
        "Select or create", options=["+ new prompt", *prompt_names], key="prompt_choice"
    )
    prompt_name = (
        st.text_input("New prompt name (slug)", key="new_prompt_name")
        if choice == "+ new prompt"
        else choice
    )

if not prompt_name:
    st.info("Pick or create a prompt to continue.")
    st.stop()

tab_versions, tab_publish, tab_pointer, tab_experiments, tab_outcomes = st.tabs(
    ["Versions", "Publish", "Pointer & rollback", "Experiments", "Outcomes"]
)

with tab_versions:
    render_versions_tab(registry, prompt_name)

with tab_publish:
    render_publish_tab(registry, prompt_name)

with tab_pointer:
    render_pointer_tab(registry, prompt_name)

with tab_experiments:
    render_experiments_tab(registry, experiments, prompt_name)

with tab_outcomes:
    render_outcomes_tab(experiments, outcomes, prompt_name)
