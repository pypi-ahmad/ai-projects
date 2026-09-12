# parse_generated_row: JSON-fence stripping and schema validation only. No model or network calls.
import pytest

from src.data.schema import parse_generated_row

VALID = (
    '{"ticket": "My invoice is wrong.", "priority": "high", "product": "billing", '
    '"sentiment": "negative", "next_action": "escalate"}'
)


def test_parse_valid_row():
    row = parse_generated_row(VALID)
    assert row.priority == "high"
    assert row.product == "billing"


def test_parse_strips_markdown_fence():
    row = parse_generated_row("```json\n" + VALID + "\n```")
    assert row.priority == "high"


def test_parse_rejects_bad_json():
    with pytest.raises(ValueError):
        parse_generated_row("not json at all")


def test_parse_rejects_bad_enum_value():
    bad = VALID.replace('"high"', '"super-urgent"')
    with pytest.raises(ValueError):
        parse_generated_row(bad)


def test_parse_rejects_missing_field():
    bad = VALID.replace('"next_action": "escalate", ', "").replace(
        ', "next_action": "escalate"', ""
    )
    with pytest.raises(ValueError):
        parse_generated_row(bad)
