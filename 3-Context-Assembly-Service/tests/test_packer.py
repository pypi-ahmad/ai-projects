"""Tests for Phase 4: Packer + BudgetReport + CLI."""
import sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from src.blocks.models import ContextBlock, ContextRequest
from src.blocks.tokenizer import TokenCounter
from src.budget.allocator import allocate
from src.budget.policy import load_policy
from src.assembly.packer import pack, BudgetReport, PackResult

_COUNTER = TokenCounter()
_FIXTURE = Path(__file__).parent / "fixtures" / "sample_request.json"


def _load_fixture() -> tuple[ContextRequest, dict]:
    from src.assembly.__main__ import _block_from_dict, _request_from_dict
    data = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    return _request_from_dict(data, None), data


def _run(request=None, policy_name="balanced"):
    if request is None:
        request, _ = _load_fixture()
    policy = load_policy(policy_name)
    plan   = allocate(request, policy)
    result = pack(request, plan, policy)
    return result, plan


# ── fixture sanity ────────────────────────────────────────────────────────────

def test_fixture_loads():
    request, data = _load_fixture()
    assert len(request.blocks) == 6
    assert request.context_window == 400
    assert request.user_message


def test_fixture_forces_at_least_one_drop():
    result, plan = _run()
    assert len(plan.dropped) >= 1, "fixture must cause at least one drop"


# ── core invariants ───────────────────────────────────────────────────────────

def test_plan_fits():
    _, plan = _run()
    assert plan.fits, f"total_tokens={plan.total_tokens} > context_window={plan.context_window}"


def test_packed_tokens_plus_reserves_le_window():
    """Token count of all message content + reserves must not exceed the window."""
    result, plan = _run()
    content_tokens = sum(
        _COUNTER.count(m["content"]) for m in result.messages
    )
    assert content_tokens + plan.reserve_tokens <= plan.context_window, (
        f"content={content_tokens} + reserves={plan.reserve_tokens} "
        f"> window={plan.context_window}"
    )


def test_report_token_total_within_window():
    result, _ = _run()
    r = result.report
    assert r.token_total <= r.context_window


def test_usable_equals_window_minus_reserves():
    result, plan = _run()
    r = result.report
    assert r.usable == r.context_window - r.reserve_tokens


def test_leftover_is_non_negative():
    result, _ = _run()
    assert result.report.leftover >= 0


# ── message structure ─────────────────────────────────────────────────────────

def test_user_message_is_last():
    result, _ = _run()
    assert result.messages[-1]["role"] == "user"
    request, _ = _load_fixture()
    assert result.messages[-1]["content"] == request.user_message


def test_system_message_is_first_when_present():
    result, _ = _run()
    roles = [m["role"] for m in result.messages]
    if "system" in roles:
        assert roles[0] == "system"


def test_messages_have_role_and_content():
    result, _ = _run()
    for msg in result.messages:
        assert "role" in msg and "content" in msg
        assert msg["role"] in ("system", "user", "assistant")
        assert isinstance(msg["content"], str)


def test_packed_text_is_string():
    result, _ = _run()
    assert isinstance(result.packed_text, str)
    assert len(result.packed_text) > 0


# ── report id consistency ─────────────────────────────────────────────────────

def test_report_kept_ids_match_plan():
    result, plan = _run()
    assert set(result.report.kept_ids) == {b.id for b in plan.kept}


def test_report_dropped_ids_match_plan():
    result, plan = _run()
    report_dropped_ids = {d["id"] for d in result.report.dropped}
    plan_dropped_ids   = {r.block.id for r in plan.dropped}
    assert report_dropped_ids == plan_dropped_ids


def test_report_kept_and_dropped_do_not_overlap():
    result, _ = _run()
    r = result.report
    kept_set    = set(r.kept_ids)
    dropped_set = {d["id"] for d in r.dropped}
    assert kept_set.isdisjoint(dropped_set)


def test_all_block_ids_accounted_for():
    """Every block id ends up in kept, dropped, or compress_jobs."""
    request, _ = _load_fixture()
    result, plan = _run(request)
    r = result.report
    all_input_ids = {b.id for b in request.blocks}
    accounted = (
        set(r.kept_ids)
        | {d["id"] for d in r.dropped}
        | set(r.compress_ids)
    )
    assert all_input_ids == accounted


# ── determinism ───────────────────────────────────────────────────────────────

def test_rerun_produces_identical_messages():
    r1, _ = _run()
    r2, _ = _run()
    assert r1.messages == r2.messages


def test_rerun_produces_identical_report():
    r1, _ = _run()
    r2, _ = _run()
    assert r1.report.as_dict() == r2.report.as_dict()


# ── drop note option ──────────────────────────────────────────────────────────

def test_drop_note_appears_when_enabled():
    request, _ = _load_fixture()
    policy = load_policy("balanced")
    plan   = allocate(request, policy)
    result = pack(request, plan, policy, include_drop_note=True)
    if plan.dropped:
        sys_msgs = [m for m in result.messages if m["role"] == "system"]
        assert sys_msgs, "system message required when drop_note is on"
        assert "Packing note" in sys_msgs[0]["content"]


# ── as_dict serialisability ───────────────────────────────────────────────────

def test_report_as_dict_is_json_serialisable():
    result, _ = _run()
    raw = result.report.as_dict()
    text = json.dumps(raw)
    recovered = json.loads(text)
    assert recovered["context_window"] == result.report.context_window
    assert isinstance(recovered["per_family"], dict)
    assert isinstance(recovered["dropped"], list)
