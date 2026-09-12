"""CLI entry point.

    python -m src.engine --schema invoice --text-file tests/fixtures/invoice.txt \
        --provider ollama --model granite4.1:3b

(Run from the project root so `src` resolves; `uv run python -m src.engine ...`
works the same way.) `--schema` accepts a full registry name or any
unambiguous prefix (`invoice` -> `invoice_draft`). Use `--file` instead of
`--text`/`--text-file` to read an image or scanned PDF page (OCR'd first)
in addition to plain text/md/json.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from pydantic import BaseModel

from providers import AgnesProvider, GeminiProvider, OllamaProvider, OpenAICompatibleProvider
from providers.base import Provider
from schemas import registry

from .file_input import FALLBACK_VL_MODEL, PADDLEOCR_MODEL, OcrError, load_text_from_file
from .pipeline import Pipeline, PipelineFailure
from .result import StructuredResult, ValidationIssue

PROVIDER_FACTORIES: dict[str, type[Provider]] = {
    "ollama": OllamaProvider,
    "agnes": AgnesProvider,
    "openai": OpenAICompatibleProvider,
    "gemini": GeminiProvider,
}


def resolve_schema_name(name: str) -> str:
    names = registry.names()
    if name in names:
        return name
    matches = [n for n in names if n.startswith(name)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise SystemExit(f"Unknown schema {name!r}. Available: {', '.join(names)}")
    raise SystemExit(f"Ambiguous schema {name!r} — matches: {', '.join(matches)}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.engine", description="Run the structured-output pipeline once."
    )
    parser.add_argument("--schema", required=True, help="Registry name or unambiguous prefix.")
    text_source = parser.add_mutually_exclusive_group(required=True)
    text_source.add_argument("--text-file", type=Path, help="Plain text/md/json file, read as-is.")
    text_source.add_argument("--text")
    text_source.add_argument(
        "--file", type=Path,
        help="Text/md/json file (read directly) or image/scanned PDF page (OCR'd first: "
        f"{PADDLEOCR_MODEL} primary, {FALLBACK_VL_MODEL} via Ollama fallback).",
    )
    parser.add_argument("--provider", required=True, choices=sorted(PROVIDER_FACTORIES))
    parser.add_argument("--model", required=True)
    parser.add_argument(
        "--repair-provider",
        choices=sorted(PROVIDER_FACTORIES),
        default=None,
        help="Default: local Ollama (see --repair-model). Use --pin-provider instead to reuse --provider/--model.",
    )
    parser.add_argument("--repair-model", default="qwen3.5:0.8b")
    parser.add_argument(
        "--pin-provider", action="store_true",
        help="Repair with the same provider/model as the initial pass instead of switching.",
    )
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--fallback", choices=["partial", "empty", "raise"], default="partial")
    parser.add_argument("--strict", action="store_true", help="Shortcut for --fallback raise.")
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--log-level", default="INFO")
    return parser


def _print_errors(errors: list[ValidationIssue]) -> None:
    for e in errors:
        print(f"  {'.'.join(map(str, e.loc)) or '(root)'}: {e.msg} [{e.type}]", file=sys.stderr)


def _print_data(data: BaseModel | dict) -> None:
    if isinstance(data, BaseModel):
        print(data.model_dump_json(indent=2))
    else:
        print(json.dumps(data, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(), format="%(message)s")

    schema_name = resolve_schema_name(args.schema)
    schema = registry.get(schema_name)

    if args.file is not None:
        try:
            text = load_text_from_file(args.file)
        except OcrError as exc:
            print(f"OCR failed [{exc.code}]: {exc.message}", file=sys.stderr)
            return 1
    elif args.text is not None:
        text = args.text
    else:
        text = args.text_file.read_text(encoding="utf-8")

    provider = PROVIDER_FACTORIES[args.provider](args.model)
    repair_provider = (
        PROVIDER_FACTORIES[args.repair_provider](args.repair_model)
        if args.repair_provider is not None
        else None
    )

    pipeline = Pipeline(
        provider,
        args.model,
        repair_provider=repair_provider,
        repair_model=args.repair_model,
        pin_provider=args.pin_provider,
        max_attempts=args.max_attempts,
        fallback="raise" if args.strict else args.fallback,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
    )

    try:
        result: StructuredResult = pipeline.run(text, schema)
    except PipelineFailure as exc:
        print(f"FAILED after {exc.result.attempts} attempt(s):", file=sys.stderr)
        _print_errors(exc.result.errors)
        return 1

    if result.ok:
        _print_data(result.data)
        return 0

    print(f"ok=False after {result.attempts} attempt(s):", file=sys.stderr)
    _print_errors(result.errors)
    if result.data is not None:
        print("Partial data:", file=sys.stderr)
        _print_data(result.data)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
