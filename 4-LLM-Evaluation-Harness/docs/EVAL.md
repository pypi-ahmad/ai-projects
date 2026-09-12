# Eval (meta)

This repository evaluates *other* models (candidates). Its metric, judge, and gate code still
need self-tests so a failure cannot silently pass everything.

This file's original intent was a dedicated set of harness self-tests: fixed inputs with
a known correct metric/gate output. In practice that role is filled by the regular pytest
suite instead -- `tests/test_metrics_rules.py` and `tests/test_metrics_aggregate.py`
(canned candidate text -> known metric result), `tests/test_judge_pipeline.py` (canned
judge JSON -> known verdict, including the malformed-JSON-repair path), and
`tests/test_gate_evaluate.py` (a known summary + config -> known pass/fail) all exercise
exactly this "known input, known correct harness output" contract, run via `pytest`. No
separate self-test file or command exists beyond that.
