"""Best-effort JSON Schema -> pydantic model builder (the UI's "paste JSON
Schema" option). Run: uv run python tests/test_dynamic_schema.py
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pydantic import ValidationError

from schemas.dynamic import SchemaConversionError, model_from_json_schema


class ModelFromJsonSchemaTests(unittest.TestCase):
    def test_flat_required_and_optional_fields(self):
        model = model_from_json_schema(
            {
                "type": "object",
                "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
                "required": ["name"],
            }
        )
        instance = model(name="Ada")
        self.assertEqual(instance.name, "Ada")
        self.assertIsNone(instance.age)
        with self.assertRaises(ValidationError):
            model()  # name is required

    def test_enum_becomes_literal(self):
        model = model_from_json_schema(
            {
                "type": "object",
                "properties": {"status": {"enum": ["open", "closed"]}},
                "required": ["status"],
            }
        )
        self.assertEqual(model(status="open").status, "open")
        with self.assertRaises(ValidationError):
            model(status="pending")

    def test_array_of_primitives(self):
        model = model_from_json_schema(
            {
                "type": "object",
                "properties": {"tags": {"type": "array", "items": {"type": "string"}}},
                "required": ["tags"],
            }
        )
        self.assertEqual(model(tags=["a", "b"]).tags, ["a", "b"])

    def test_nested_object(self):
        model = model_from_json_schema(
            {
                "type": "object",
                "properties": {
                    "owner": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                        "required": ["name"],
                    }
                },
                "required": ["owner"],
            }
        )
        instance = model(owner={"name": "Ada"})
        self.assertEqual(instance.owner.name, "Ada")

    def test_additional_properties_false_forbids_extra(self):
        model = model_from_json_schema(
            {"type": "object", "properties": {"name": {"type": "string"}}, "additionalProperties": False}
        )
        with self.assertRaises(ValidationError):
            model(name="Ada", extra="nope")

    def test_ref_raises_clear_conversion_error(self):
        with self.assertRaises(SchemaConversionError):
            model_from_json_schema({"type": "object", "properties": {"a": {"$ref": "#/$defs/Foo"}}})


if __name__ == "__main__":
    unittest.main()
