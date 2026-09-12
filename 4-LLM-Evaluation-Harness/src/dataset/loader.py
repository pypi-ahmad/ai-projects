"""Parses and validates `datasets/golden/*.jsonl` into `Case` objects (schema in
models.py). Used by `python -m src.dataset validate` (__main__.py) and by
src/runners/candidate.py before a run starts.
"""

import json
from pathlib import Path

from pydantic import ValidationError

from .models import Case


class DatasetError(Exception):
    """Raised when a dataset file or suite fails validation."""


def load_file(path: Path) -> list[Case]:
    # Collects every line error instead of raising on the first one, so a
    # `validate` run reports all bad lines in a file in one pass rather than
    # requiring one fix-and-rerun cycle per error.
    cases = []
    errors = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{path}:{lineno}: invalid JSON ({exc})")
            continue
        try:
            cases.append(Case.model_validate(raw))
        except ValidationError as exc:
            errors.append(f"{path}:{lineno}: {exc}")
    if errors:
        raise DatasetError("\n".join(errors))
    return cases


def load_suite(directory: Path) -> list[Case]:
    # Case ids must be unique across every file in the directory, not just within
    # one file -- `seen` tracks id -> the file it first appeared in so a duplicate
    # error can point back at both locations. A file that fails to load at all
    # doesn't stop the others: its error is recorded and the loop continues.
    all_cases: list[Case] = []
    errors: list[str] = []
    seen: dict[str, Path] = {}
    for file_path in sorted(Path(directory).glob("*.jsonl")):
        try:
            file_cases = load_file(file_path)
        except DatasetError as exc:
            errors.append(str(exc))
            continue
        for case in file_cases:
            if case.id in seen:
                errors.append(
                    f"duplicate case id '{case.id}' in {file_path} (first seen in {seen[case.id]})"
                )
                continue
            seen[case.id] = file_path
            all_cases.append(case)
    if errors:
        raise DatasetError("\n".join(errors))
    return all_cases
