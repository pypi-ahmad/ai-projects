"""Schema registry + validation-to-StructuredResult behavior. No LLM calls:
these exercise pydantic validation directly against hand-written JSON.
Run: uv run python tests/test_schemas.py
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from engine import StructuredResult
from schemas import ContactRecord, InvoiceDraft, MeetingNotes, registry


class SchemaRegistryTests(unittest.TestCase):
    def test_lists_all_four_built_ins(self):
        self.assertEqual(
            registry.names(),
            ["classification_result", "contact_record", "invoice_draft", "meeting_notes"],
        )

    def test_get_returns_the_model_class(self):
        self.assertIs(registry.get("contact_record"), ContactRecord)

    def test_json_schema_export(self):
        schema = registry.json_schema("contact_record")
        self.assertEqual(schema["title"], "ContactRecord")
        self.assertIn("email", schema["properties"])
        self.assertEqual(schema["properties"]["email"]["description"], "Contact's email address.")

    def test_example_instance_is_valid(self):
        for name in registry.names():
            model = registry.get(name)
            example = registry.example(name)
            with self.subTest(schema=name):
                self.assertIsInstance(example, model)


class ValidationTests(unittest.TestCase):
    def test_good_json_parses_for_every_built_in_schema(self):
        for name in registry.names():
            model = registry.get(name)
            raw = registry.example(name).model_dump_json()
            with self.subTest(schema=name):
                result = StructuredResult.from_raw_text(raw, model)
                self.assertTrue(result.ok, result.errors)
                self.assertEqual(result.data, registry.example(name))
                self.assertEqual(result.errors, [])

    def test_extra_field_rejected(self):
        payload = json.dumps(
            {"name": "Ada", "email": "ada@example.com", "tags": [], "nickname": "not allowed"}
        )
        result = StructuredResult.from_raw_text(payload, ContactRecord)
        self.assertFalse(result.ok)
        self.assertEqual(result.errors[0].type, "extra_forbidden")
        self.assertEqual(result.errors[0].loc, ("nickname",))

    def test_enum_mismatch(self):
        example = registry.example("invoice_draft").model_dump(mode="json")
        example["currency"] = "DOGE"
        result = StructuredResult.from_raw_text(json.dumps(example), InvoiceDraft)
        self.assertFalse(result.ok)
        self.assertEqual(result.errors[0].type, "enum")
        self.assertEqual(result.errors[0].loc, ("currency",))

    def test_missing_required_field(self):
        payload = json.dumps({"name": "Ada", "tags": []})  # no email
        result = StructuredResult.from_raw_text(payload, ContactRecord)
        self.assertFalse(result.ok)
        self.assertEqual(result.errors[0].type, "missing")
        self.assertEqual(result.errors[0].loc, ("email",))

    def test_nested_list_error_location(self):
        example = registry.example("meeting_notes").model_dump(mode="json")
        del example["action_items"][0]["due"]  # nested list item, missing required field
        result = StructuredResult.from_raw_text(json.dumps(example), MeetingNotes)
        self.assertFalse(result.ok)
        self.assertEqual(result.errors[0].type, "missing")
        self.assertEqual(result.errors[0].loc, ("action_items", 0, "due"))

    def test_nested_list_success(self):
        example = registry.example("meeting_notes")
        result = StructuredResult.from_raw_text(example.model_dump_json(), MeetingNotes)
        self.assertTrue(result.ok)
        self.assertEqual(len(result.data.action_items), 1)
        self.assertEqual(result.data.action_items[0].owner, "Ada Lovelace")


if __name__ == "__main__":
    unittest.main()
