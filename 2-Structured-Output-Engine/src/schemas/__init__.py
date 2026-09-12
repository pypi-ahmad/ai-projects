"""Public surface of the schemas package: imports every built-in schema and
registers each in the module-level `registry` (registry.py) by name.
Registering a schema here is what makes it resolvable via
`SchemaRegistry.get()`/`names()`, and visible to the CLI, the Streamlit
sidebar, and the eval harness — see docs/SCHEMAS.md "Adding a fifth
schema"."""

from .classification_result import CLASSIFICATION_RESULT_EXAMPLE, ClassificationResult, Label
from .contact_record import CONTACT_RECORD_EXAMPLE, ContactRecord
from .dynamic import SchemaConversionError, model_from_json_schema
from .invoice_draft import INVOICE_DRAFT_EXAMPLE, Currency, InvoiceDraft, LineItem
from .meeting_notes import MEETING_NOTES_EXAMPLE, ActionItem, MeetingNotes
from .registry import RegisteredSchema, SchemaRegistry

registry = SchemaRegistry()
registry.register("contact_record", ContactRecord, CONTACT_RECORD_EXAMPLE)
registry.register("invoice_draft", InvoiceDraft, INVOICE_DRAFT_EXAMPLE)
registry.register("meeting_notes", MeetingNotes, MEETING_NOTES_EXAMPLE)
registry.register("classification_result", ClassificationResult, CLASSIFICATION_RESULT_EXAMPLE)

__all__ = [
    "SchemaRegistry",
    "RegisteredSchema",
    "registry",
    "ContactRecord",
    "Currency",
    "LineItem",
    "InvoiceDraft",
    "ActionItem",
    "MeetingNotes",
    "Label",
    "ClassificationResult",
    "model_from_json_schema",
    "SchemaConversionError",
]
