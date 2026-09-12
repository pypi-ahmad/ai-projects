"""Golden-dataset loading and validation. Start at models.py for the Case schema,
then loader.py for how *.jsonl files are parsed into it.
"""

from .loader import DatasetError, load_file, load_suite
from .models import Case, CaseExpected, CaseInput, CaseJudge, CaseSkipIf

__all__ = [
    "Case",
    "CaseExpected",
    "CaseInput",
    "CaseJudge",
    "CaseSkipIf",
    "DatasetError",
    "load_file",
    "load_suite",
]
