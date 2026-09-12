# Adding a Schema

A schema is a `pydantic.BaseModel` subclass, registered by name in the
`SchemaRegistry` (`src/schemas/registry.py`) so it
can be looked up, listed, and exported without importing every schema
module by hand.

## Adding a fifth schema

The model itself lives in one new file. Registering it needs two lines in
`src/schemas/__init__.py`; this project doesn't auto-discover schema
files, so that step is unavoidable, but it's the only other change needed:
the CLI's `--schema` prefix matching, the Streamlit sidebar dropdown, and
`docs/EVAL.md`'s eval harness all key off `registry.names()`, so a
correctly-registered schema shows up everywhere automatically.

**1. `src/schemas/support_ticket.py`**; the model, `ConfigDict(extra="forbid")`, a `Field(description=...)` on every field the model needs to understand, and one canonical example instance:

```python
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SupportTicket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(description="One-line summary of the issue.")
    priority: Priority = Field(description="Urgency of the ticket.")
    description: str = Field(description="Full description of the problem.")


SUPPORT_TICKET_EXAMPLE = SupportTicket(
    subject="Login page returns 500",
    priority=Priority.HIGH,
    description="Users report a server error when submitting the login form since this morning.",
)
```

**2. `src/schemas/__init__.py`**; one import line, one `registry.register(...)` call, plus adding the new names to `__all__`:

```python
from .support_ticket import SUPPORT_TICKET_EXAMPLE, Priority, SupportTicket
# ...
registry.register("support_ticket", SupportTicket, SUPPORT_TICKET_EXAMPLE)
```

That's it; `registry.names()` now includes `"support_ticket"`,
`python -m src.engine --schema support --file ...` resolves via prefix
match, and it appears in the Streamlit sidebar's schema dropdown with no
further changes.

## Built-in schemas

| Name | Model | Covers |
|---|---|---|
| `contact_record` | `ContactRecord` | optional field (`phone`), `EmailStr` validation, `tags: list[str]` |
| `invoice_draft` | `InvoiceDraft` | enum (`Currency`), nested list (`line_items: list[LineItem]`), `date` |
| `meeting_notes` | `MeetingNotes` | two independent lists (`attendees`, `decisions`) plus a nested list of sub-models (`action_items: list[ActionItem]`) |
| `classification_result` | `ClassificationResult` | enum (`Label`, placeholder values), bounded float (`confidence`, 0 to 1), length-capped string (`rationale`) |

```python
from schemas import registry

registry.names()                        # ['classification_result', 'contact_record', ...]
registry.get("contact_record")          # -> ContactRecord (the class)
registry.json_schema("contact_record")  # -> dict, model_json_schema()
registry.example("contact_record")      # -> ContactRecord(name='Ada Lovelace', ...)
```

## 1. Python class

```python
from pydantic import BaseModel

class Person(BaseModel):
    name: str
    age: int
```

(This exact class is used as the test fixture in `tests/test_engine.py`.)

## 2. JSON Schema it exports

`schema.model_json_schema()` is what actually gets sent to the provider as
the `format`/response-schema argument; this is what constrains generation,
not the Python class itself:

```json
{
  "properties": {
    "name": {"title": "Name", "type": "string"},
    "age": {"title": "Age", "type": "integer"}
  },
  "required": ["name", "age"],
  "title": "Person",
  "type": "object"
}
```

## 3. Example input/output

Validation doesn't need a provider; `StructuredResult.from_raw_text` parses
and validates in one step, which is exactly what `tests/test_schemas.py`
exercises with hand-written JSON:

```python
from engine import StructuredResult

result = StructuredResult.from_raw_text('{"name": "Ada Lovelace", "age": 36}', Person)
# StructuredResult(ok=True, data=Person(name='Ada Lovelace', age=36), errors=[], attempts=1, ...)
```

Getting that JSON text from a real model; with retry, cross-model repair,
and graceful fallback if it never validates; is `engine.pipeline.Pipeline`
(Phase 4). See the README's Example section and `docs/ARCHITECTURE.md`.

## Guidelines

- Use field types Pydantic can validate directly (`str`, `int`, `float`,
  `bool`, `Enum`, nested `BaseModel`, `list[...]`); the tighter the type,
  the more the repair pass has to work with when it fails (the validation
  error message names the exact field and constraint).
- Prefer required fields over `Optional[...]` where the data should always
  be present; `Optional` widens the exported JSON Schema (`anyOf` with
  `null`) which some hosted providers handle less strictly than others.
  See `docs/TECHNICAL.md` JSON Schema export caveats.
- Keep field descriptions short via `Field(description=...)` when the name
  alone is ambiguous; it becomes part of the schema the model sees.
