"""Pipeline tests against a fake complete()-based provider — no live
providers, no real Ollama. Run: uv run python tests/test_pipeline.py
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from engine.pipeline import Pipeline, PipelineFailure, ParseError, build_partial, extract_json
from providers.base import ProviderResponse
from schemas import ContactRecord, InvoiceDraft

VALID_CONTACT = '{"name": "Ada Lovelace", "email": "ada@example.com", "phone": null, "tags": []}'
VALID_INVOICE = (
    '{"vendor": "Acme", "currency": "USD", '
    '"line_items": [{"description": "Widgets", "quantity": 1, "unit_price": 2.5, "amount": 2.5}], '
    '"totals": 2.5, "invoice_date": "2026-01-15"}'
)


class FakeProvider:
    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def complete(self, messages, *, json_schema=None, temperature=0.0, max_tokens=1024) -> ProviderResponse:
        self.calls.append({"messages": messages, "temperature": temperature, "json_schema": json_schema})
        text = self.responses.pop(0)
        return ProviderResponse(text=text, model="fake-model", raw={"content": text})


class UnloadingFakeProvider(FakeProvider):
    def __init__(self, responses: list[str]):
        super().__init__(responses)
        self.unload_calls: list[str | None] = []

    def unload(self, model: str | None = None) -> None:
        self.unload_calls.append(model)


class ExtractJsonTests(unittest.TestCase):
    def test_whole_reply_is_the_object(self):
        self.assertEqual(extract_json('{"a": 1}'), '{"a": 1}')

    def test_fenced_block(self):
        raw = 'Sure, here you go:\n```json\n{"a": 1}\n```\nLet me know if you need more.'
        self.assertEqual(extract_json(raw), '{"a": 1}')

    def test_first_balanced_span_amid_prose(self):
        raw = 'The result is {"a": {"nested": 1}, "b": 2} and that is final.'
        self.assertEqual(extract_json(raw), '{"a": {"nested": 1}, "b": 2}')

    def test_no_json_raises_parse_error(self):
        with self.assertRaises(ParseError):
            extract_json("I cannot help with that request.")


class BuildPartialTests(unittest.TestCase):
    def test_keeps_valid_fills_optional_default_leaves_required_missing(self):
        # email missing (required, no default) -> stays an error, not fabricated.
        # phone missing (Optional, default=None) -> filled with None.
        # name present and valid -> kept.
        raw = '{"name": "Ada Lovelace", "tags": ["x"]}'
        data, errors = build_partial(raw, ContactRecord)

        self.assertIsInstance(data, dict)  # can't form a full instance: email still missing
        self.assertEqual(data["name"], "Ada Lovelace")
        self.assertEqual(data["tags"], ["x"])
        self.assertIsNone(data["phone"])
        self.assertNotIn("email", data)
        self.assertEqual([e.loc for e in errors], [("email",)])
        self.assertEqual(errors[0].type, "missing")

    def test_fully_reconstructable_becomes_a_real_instance(self):
        data, errors = build_partial(VALID_CONTACT, ContactRecord)
        self.assertIsInstance(data, ContactRecord)
        self.assertEqual(errors, [])


class PipelineTests(unittest.TestCase):
    def test_valid_first_pass(self):
        provider = FakeProvider([VALID_CONTACT])
        pipeline = Pipeline(provider, "fake-model", repair_provider=FakeProvider([]))

        result = pipeline.run("Ada Lovelace, ada@example.com", ContactRecord)

        self.assertTrue(result.ok)
        self.assertEqual(result.data, ContactRecord(name="Ada Lovelace", email="ada@example.com"))
        self.assertEqual(result.attempts, 1)
        self.assertEqual(len(provider.calls), 1)

    def test_broken_json_repaired_on_retry_same_provider(self):
        provider = FakeProvider(["not json at all", VALID_CONTACT])
        repair = FakeProvider([])  # must not be touched — retry stays on the same provider
        pipeline = Pipeline(provider, "fake-model", repair_provider=repair)

        result = pipeline.run("Ada Lovelace, ada@example.com", ContactRecord)

        self.assertTrue(result.ok)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(len(repair.calls), 0)
        # retry used a lower temperature than the initial pass
        self.assertLess(provider.calls[1]["temperature"], provider.calls[0]["temperature"])

    def test_enum_typo_repaired_by_switching_to_repair_provider(self):
        bad_currency = VALID_INVOICE.replace('"currency": "USD"', '"currency": "DOGE"')
        provider = FakeProvider([bad_currency, bad_currency])  # initial + retry both still wrong
        repair = FakeProvider([VALID_INVOICE])  # repair model fixes it

        pipeline = Pipeline(provider, "fake-model", repair_provider=repair, repair_model="repair-model")
        result = pipeline.run("An invoice", InvoiceDraft)

        self.assertTrue(result.ok)
        self.assertEqual(result.attempts, 3)
        self.assertEqual(result.model, "repair-model")
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(len(repair.calls), 1)

    def test_enum_typo_listed_in_errors_when_never_fixed(self):
        bad_currency = VALID_INVOICE.replace('"currency": "USD"', '"currency": "DOGE"')
        provider = FakeProvider([bad_currency, bad_currency])
        repair = FakeProvider([bad_currency])

        pipeline = Pipeline(provider, "fake-model", repair_provider=repair, fallback="empty")
        result = pipeline.run("An invoice", InvoiceDraft)

        self.assertFalse(result.ok)
        self.assertTrue(any(e.type == "enum" and e.loc == ("currency",) for e in result.errors))

    def test_max_attempts_exhausted_ok_false_no_exception(self):
        provider = FakeProvider(["still broken"] * 2)
        repair = FakeProvider(["still broken"])
        pipeline = Pipeline(provider, "fake-model", repair_provider=repair)

        result = pipeline.run("x", ContactRecord)  # no exception raised

        self.assertFalse(result.ok)
        self.assertEqual(result.attempts, 3)

    def test_pin_provider_never_switches_for_repair(self):
        provider = FakeProvider(["bad", "bad", VALID_CONTACT])
        repair = FakeProvider([])  # must never be called
        pipeline = Pipeline(provider, "fake-model", repair_provider=repair, pin_provider=True)

        result = pipeline.run("x", ContactRecord)

        self.assertTrue(result.ok)
        self.assertEqual(result.model, "fake-model")
        self.assertEqual(len(repair.calls), 0)
        self.assertEqual(len(provider.calls), 3)

    def test_unloads_initial_provider_before_switching_to_repair(self):
        provider = UnloadingFakeProvider(["bad", "bad"])
        repair = UnloadingFakeProvider([VALID_CONTACT])
        pipeline = Pipeline(provider, "initial-model", repair_provider=repair, repair_model="repair-model")

        pipeline.run("x", ContactRecord)

        self.assertEqual(provider.unload_calls, ["initial-model"])  # unloaded once, before the switch
        self.assertEqual(repair.unload_calls, [])  # never switched away from repair, nothing to unload

    def test_pin_provider_never_unloads_since_it_never_switches(self):
        provider = UnloadingFakeProvider(["bad", "bad", VALID_CONTACT])
        pipeline = Pipeline(provider, "fake-model", pin_provider=True)

        pipeline.run("x", ContactRecord)

        self.assertEqual(provider.unload_calls, [])

    def test_extra_keys_rejected_then_empty_fallback(self):
        extra = VALID_CONTACT[:-1] + ', "nickname": "not allowed"}'
        provider = FakeProvider([extra] * 2)
        repair = FakeProvider([extra])
        pipeline = Pipeline(provider, "fake-model", repair_provider=repair, fallback="empty")

        result = pipeline.run("x", ContactRecord)

        self.assertFalse(result.ok)
        self.assertIsNone(result.data)
        self.assertTrue(any(e.type == "extra_forbidden" for e in result.errors))

    def test_extra_keys_stripped_under_partial_fallback(self):
        extra = VALID_CONTACT[:-1] + ', "nickname": "not allowed"}'
        provider = FakeProvider([extra] * 2)
        repair = FakeProvider([extra])
        pipeline = Pipeline(provider, "fake-model", repair_provider=repair)  # fallback="partial" default

        result = pipeline.run("x", ContactRecord)

        self.assertFalse(result.ok)  # fallback path is always ok=False, even when fully reconstructable
        self.assertIsInstance(result.data, ContactRecord)
        self.assertNotIn("nickname", result.data.model_dump())

    def test_parse_error_when_reply_has_no_json_then_fails_gracefully(self):
        provider = FakeProvider(["I refuse.", "I refuse."])
        repair = FakeProvider(["I refuse."])
        pipeline = Pipeline(provider, "fake-model", repair_provider=repair, fallback="empty")

        result = pipeline.run("x", ContactRecord)

        self.assertFalse(result.ok)
        self.assertEqual(result.errors[0].type, "parse_error")

    def test_fallback_raise_is_caught_by_caller_not_left_uncaught(self):
        provider = FakeProvider(["bad"] * 3)
        pipeline = Pipeline(provider, "fake-model", repair_provider=FakeProvider(["bad"]), fallback="raise")

        with self.assertRaises(PipelineFailure) as ctx:
            pipeline.run("x", ContactRecord)
        self.assertEqual(ctx.exception.result.attempts, 3)


if __name__ == "__main__":
    unittest.main()
