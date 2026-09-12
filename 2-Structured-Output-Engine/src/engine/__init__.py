"""Public surface of the engine package. `Pipeline` (pipeline.py) is the
actual product — text + schema in, `StructuredResult` out; `result.py`
defines that envelope and `file_input.py` is the optional OCR-based text
extraction that runs ahead of it. Start at pipeline.py."""

from .file_input import OcrError, is_text_file, load_text_from_file
from .pipeline import ParseError, Pipeline, PipelineFailure, build_partial, extract_json
from .result import StructuredResult, ValidationIssue

__all__ = [
    "StructuredResult",
    "ValidationIssue",
    "Pipeline",
    "PipelineFailure",
    "ParseError",
    "extract_json",
    "build_partial",
    "load_text_from_file",
    "is_text_file",
    "OcrError",
]
