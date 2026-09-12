"""Seed demo: calc + write_note against the running API.

Start the API first (`run.cmd`, or `uv run --python .venv python -m
uvicorn src.tools.api:app --host 127.0.0.1 --port 8765`), then:

    uv run --python .venv python scripts/seed_demo.py
"""

from __future__ import annotations

import sys
import uuid
from typing import Any

import requests

API_BASE_URL = "http://127.0.0.1:8765"


def call(name: str, args: dict[str, Any], run_id: str) -> dict[str, Any]:
    resp = requests.post(
        f"{API_BASE_URL}/v1/call", json={"name": name, "args": args, "run_id": run_id}, timeout=30
    )
    resp.raise_for_status()
    return resp.json()


def main() -> int:
    run_id = f"seed-demo-{uuid.uuid4().hex[:8]}"

    try:
        requests.get(f"{API_BASE_URL}/v1/tools", timeout=5).raise_for_status()
    except requests.exceptions.RequestException as exc:
        print(f"Can't reach the API at {API_BASE_URL}: {exc}")
        print("Start it first: run.cmd (or see README.md).")
        return 1

    print(f"run_id: {run_id}\n")

    calc_result = call("calc", {"expression": "17*19"}, run_id)
    print(f"calc(17*19) -> {calc_result}")
    if not calc_result["ok"]:
        print("calc failed, stopping.")
        return 1

    value = calc_result["value"]["value"]
    note_result = call("write_note", {"text": f"17*19 = {value}"}, run_id)
    print(f"write_note -> {note_result}")
    if not note_result["ok"]:
        print("write_note failed, stopping.")
        return 1

    note_name = note_result["value"]["name"]
    print(f"\nNote written: data/sandbox/{run_id}/{note_name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
