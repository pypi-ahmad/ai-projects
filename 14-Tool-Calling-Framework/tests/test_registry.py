"""Schema export: registered tools produce valid OpenAI-style and generic JSON schemas."""

from tools.builtins import register_builtins
from tools.registry import Registry


def test_schema_export():
    registry = Registry()
    register_builtins(registry)

    openai_schemas = registry.list()
    assert openai_schemas
    for entry in openai_schemas:
        assert entry["type"] == "function"
        fn = entry["function"]
        assert isinstance(fn["name"], str)
        assert isinstance(fn["description"], str)
        assert fn["parameters"]["type"] == "object"

    generic_schemas = registry.list_schemas()
    names = {entry["name"] for entry in generic_schemas}
    assert names == {"calc", "now", "json_query", "write_note", "read_note"}
    for entry in generic_schemas:
        assert "type" not in entry
        assert entry["parameters"]["type"] == "object"
