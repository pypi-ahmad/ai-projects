"""Dormant audit-trail writer for the invoice control plane (see
docs/ARCHITECTURE.md, docs/COMPLIANCE.md): `write_audit_line` would append
one JSON line per commit/review/human_override decision, but no node in the
active graph calls it today -- nothing is logged per run beyond what the UI
shows in-session.

Must not: be wired up on its own without also restoring the commit/review
split it was designed to log against (see docs/ARCHITECTURE.md's dormant
routing table) -- an audit line with no corresponding gated decision would
misrepresent what the active graph actually checked.

Next: docs/COMPLIANCE.md for the audit-line schema this writes.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

# Relative to the process's current working directory (the project root when
# launched via run.cmd, or via pytest from the repo root); tests isolate this
# with monkeypatch.chdir(tmp_path) rather than the module taking a base-dir
# argument. Every other module that writes under data/ (parse.py, markdown.py,
# annotate.py, extract.py's crop_and_extract) follows the same convention.
AUDIT_DIR = Path("data/audit")


def write_audit_line(
    *, doc_sha: str, node: str, retry_count: int, error_codes: list[str], model: str
) -> None:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    path = AUDIT_DIR / f"{now:%Y%m%d}.jsonl"
    line = {
        "ts": now.isoformat(),
        "doc_sha": doc_sha,
        "node": node,
        "retry_count": retry_count,
        "error_codes": error_codes,
        "model": model,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line) + "\n")
