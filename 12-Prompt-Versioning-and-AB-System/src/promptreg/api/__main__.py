"""Run the API: `uv run python -m promptreg.api` (binds 127.0.0.1:8000).

Override with `PROMPTREG_API_PORT` if 8000 is already taken by something
else on the machine (a plain port conflict, not Windows-specific).
"""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    port = int(os.environ.get("PROMPTREG_API_PORT", "8000"))
    uvicorn.run("promptreg.api.app:app", host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
