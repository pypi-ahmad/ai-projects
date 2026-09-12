"""Eval harness: JSONL loading + metric computation, against a fake
complete()-based provider. Run: uv run python tests/test_eval.py
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from engine.pipeline import Pipeline
from eval import load_cases, run_eval
from providers.base import ProviderResponse
from schemas import registry

CASES_PATH = Path(__file__).resolve().parent / "eval" / "cases.jsonl"

VALID_CONTACT = '{"name": "Ada Lovelace", "email": "ada@example.com", "phone": null, "tags": []}'


class FakeProvider:
    def __init__(self, responses: list[str]):
        self.responses = list(responses)

    def complete(self, messages, *, json_schema=None, temperature=0.0, max_tokens=1024) -> ProviderResponse:
        return ProviderResponse(text=self.responses.pop(0), model="fake-model", raw={})


class LoadCasesTests(unittest.TestCase):
    def test_real_cases_file_has_at_least_12_across_all_four_schemas(self):
        cases = load_cases(CASES_PATH)
        self.assertGreaterEqual(len(cases), 12)
        schemas_seen = {c["schema"] for c in cases}
        self.assertEqual(schemas_seen, set(registry.names()))
        for case in cases:
            self.assertIn("text", case)
            self.assertIn("category", case)


class RunEvalTests(unittest.TestCase):
    def test_metrics_across_valid_repaired_and_failed_cases(self):
        cases = [
            {"id": "a", "schema": "contact_record", "category": "clean", "text": "x"},  # valid first try
            {"id": "b", "schema": "contact_record", "category": "messy", "text": "x"},  # repaired
            {"id": "c", "schema": "contact_record", "category": "missing_fields", "text": "x"},  # fails
        ]
        provider = FakeProvider(
            [
                VALID_CONTACT,  # case a, attempt 1
                "not json",  # case b, attempt 1
                VALID_CONTACT,  # case b, attempt 2 (retry)
                "still not json",  # case c, attempt 1
                "still not json",  # case c, attempt 2
                "still not json",  # case c, attempt 3
            ]
        )
        pipeline = Pipeline(provider, "fake-model", repair_provider=FakeProvider(["still not json"]))

        summary = run_eval(pipeline, cases)

        self.assertEqual(summary.total, 3)
        self.assertAlmostEqual(summary.valid_rate, 1 / 3)
        self.assertAlmostEqual(summary.repair_rate, 1 / 3)
        self.assertAlmostEqual(summary.failure_rate, 1 / 3)
        self.assertAlmostEqual(summary.mean_attempts, (1 + 2 + 3) / 3)
        self.assertIsInstance(summary.mean_latency_ms, float)
        self.assertEqual(len(summary.results), 3)
        self.assertEqual(summary.results[0].ok, True)
        self.assertEqual(summary.results[2].ok, False)
        # default fallback="partial" re-derives errors via build_partial, so
        # a parse failure surfaces as "missing" for each unfillable required
        # field (name, email) rather than the original "parse_error" type.
        self.assertEqual(summary.results[2].error_types, ["missing", "missing"])

    def test_empty_cases_is_zero_not_a_crash(self):
        pipeline = Pipeline(FakeProvider([]), "fake-model", repair_provider=FakeProvider([]))
        summary = run_eval(pipeline, [])
        self.assertEqual(summary.total, 0)
        self.assertEqual(summary.valid_rate, 0.0)
        self.assertEqual(summary.mean_attempts, 0.0)


if __name__ == "__main__":
    unittest.main()
