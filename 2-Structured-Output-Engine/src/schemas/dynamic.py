"""Best-effort JSON Schema -> pydantic model, for the UI's "paste JSON
Schema" option (src/ui/app.py). Supports the common subset: object type,
properties, required, enum (as Literal), array items, nested objects.
Does not resolve $ref/$defs/anyOf/oneOf/allOf — a schema using those raises
SchemaConversionError with a clear message rather than silently building
the wrong model.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, create_model

_PRIMITIVE_TYPES = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
}

_UNSUPPORTED_KEYWORDS = ("$ref", "$defs", "anyOf", "oneOf", "allOf")


class SchemaConversionError(Exception):
    pass


def model_from_json_schema(schema: dict, name: str = "PastedSchema") -> type[BaseModel]:
    unsupported = [kw for kw in _UNSUPPORTED_KEYWORDS if kw in schema]
    if unsupported:
        raise SchemaConversionError(
            f"This schema uses {', '.join(unsupported)}, which this best-effort "
            "converter doesn't support — try a flatter schema."
        )
    if schema.get("type", "object") != "object" or "properties" not in schema:
        raise SchemaConversionError("Top-level schema must be a JSON object with 'properties'.")

    required = set(schema.get("required", []))
    fields = {
        field_name: _field_definition(field_name, field_schema, field_name in required)
        for field_name, field_schema in schema["properties"].items()
    }

    config = ConfigDict(extra="forbid") if schema.get("additionalProperties") is False else ConfigDict()
    return create_model(name, __config__=config, **fields)


def _field_definition(field_name: str, field_schema: dict, required: bool) -> tuple:
    py_type = _python_type(field_name, field_schema)
    if required:
        return (py_type, ...)
    return (py_type | None, field_schema.get("default"))


def _python_type(field_name: str, field_schema: dict):
    if "enum" in field_schema:
        return Literal[tuple(field_schema["enum"])]

    json_type = field_schema.get("type")
    if json_type == "array":
        item_type = _python_type(f"{field_name}[]", field_schema.get("items", {}))
        return list[item_type]
    if json_type == "object":
        nested_name = "".join(part.capitalize() for part in field_name.split("_")) or "Nested"
        return model_from_json_schema(field_schema, name=nested_name)
    if json_type in _PRIMITIVE_TYPES:
        return _PRIMITIVE_TYPES[json_type]
    raise SchemaConversionError(f"Unsupported or missing 'type' for field {field_name!r}: {field_schema!r}")
