"""Opt-in live evaluation restricted to the six approved document pages."""

from __future__ import annotations

import argparse
import base64
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time

from openai import ContentFilterFinishReasonError

from src.extract import MODEL_NAME, _build_llm, _image_message, _invoke_structured
from src.diagnostics import ExtractionCallError
from src.parse import MAX_PARALLEL_PAGES
from src.preprocess import preprocess_pages
from src.schema import ParsePage

ROOT = Path(__file__).resolve().parents[1]
REFERENCES = Path(r"D:\AI\Github\OpenAI-Agentic-Document_extraction\data\GroundTruths")
SAMPLES = (
    ("Masked BadgeCare Plus_1", 1),
    ("Masked_Amerigroup_RealSolutions_1", 2),
    ("Masked_Amerigroup_RealSolutions_2", 1),
    ("Masked Amerigroup_1", 2),
)


class _PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def plain_text(value: str) -> str:
    parser = _PlainText()
    parser.feed(value)
    return " ".join(parser.parts)


def tokens(value: str) -> Counter:
    return Counter(re.findall(r"\w+", value.casefold()))


def score_page(page: ParsePage, reference: dict) -> dict:
    source = reference["markdown"]
    ref_page = next(p for p in reference["structure"]["children"] if p["grounding"]["page"] == page.page)
    span = ref_page["grounding"]["range"]
    expected = tokens(plain_text(source[span["start"]:span["end"]]))
    actual = tokens(" ".join(
        " ".join(cell for row in b.table for cell in row) if b.type == "table" and b.table else b.text
        for b in page.blocks
    ))
    overlap = sum((expected & actual).values())
    precision = overlap / max(sum(actual.values()), 1)
    recall = overlap / max(sum(expected.values()), 1)
    boxes = [b.bbox for b in page.blocks if b.bbox]
    tables = [b.table for b in page.blocks if b.type == "table" and b.table]
    return {
        "reference_token_precision": precision,
        "reference_token_recall": recall,
        "reference_token_f1": 2 * precision * recall / (precision + recall) if precision + recall else 0,
        "blocks": len(page.blocks), "tables": len(tables),
        "ragged_tables": sum(len({len(row) for row in table}) > 1 for table in tables),
        "invalid_boxes": sum(not (b.page == page.page and 0 <= b.xyxy[0] < b.xyxy[2] <= 1 and 0 <= b.xyxy[1] < b.xyxy[3] <= 1) for b in boxes),
        "null_boxes": sum(b.bbox is None for b in page.blocks),
        "duplicate_ids": len(page.blocks) - len({b.id for b in page.blocks}),
    }


def run_page(payload: dict, prompt: str) -> dict:
    started = time.perf_counter()
    outcome = {"page": payload["page"], "document_sha256": payload["doc_sha256"]}
    diagnostics = []
    try:
        llm = _build_llm()
        llm.root_client = llm.root_client.with_options(max_retries=0, timeout=180)
        text = prompt.format(page_number=payload["page"], width_px=payload["width"], height_px=payload["height"])
        page = _invoke_structured(
            llm, ParsePage, [_image_message(text, payload["base64"], payload["mime"])],
            call_name="parse_page", diagnostics=diagnostics,
        )
        page = page.model_copy(update={"page": payload["page"], "width_px": payload["width"], "height_px": payload["height"]})
        outcome.update(status="parsed", result=page.model_dump())
    except ExtractionCallError as exc:
        outcome["status"] = exc.diagnostic.outcome
    except ContentFilterFinishReasonError:
        outcome["status"] = "content_filtered"
    except Exception as exc:
        outcome.update(status="error", error_type=type(exc).__name__)
    outcome["seconds"] = time.perf_counter() - started
    if diagnostics:
        diagnostic = diagnostics[-1].model_copy(update={"page": payload["page"]})
        outcome["diagnostics"] = diagnostic.model_dump()
        outcome["usage"] = ({"input_tokens": diagnostic.input_tokens, "output_tokens": diagnostic.output_tokens,
                             "input_token_details": {"cache_read": diagnostic.cached_tokens}} if diagnostic.usage_known else None)
    return outcome


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live", action="store_true", help="Send the six allowlisted pages to the configured model")
    parser.add_argument("--skip-filtered-from", type=Path, help="Previous manifest whose content-filtered pages must not be sent again")
    args = parser.parse_args()
    if not args.live:
        parser.error("Explicit --live is required; no model calls were made")
    skipped = set()
    if args.skip_filtered_from:
        previous = json.loads(args.skip_filtered_from.read_text(encoding="utf-8"))
        skipped = {(p["document"], p["page"]) for p in previous["pages"] if p["status"] == "content_filtered"}
    prompt_files = sorted(args.prompts.glob("*.md"))
    prompt = (args.prompts / "parse-page.md").read_text(encoding="utf-8").rstrip("\r\n")
    args.output.mkdir(parents=True, exist_ok=False)
    manifest = {"model": MODEL_NAME, "temperature": 0, "reasoning": _build_llm().reasoning_effort,
                "max_parallel_pages": MAX_PARALLEL_PAGES, "max_retries": 0,
                "prompts": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in prompt_files},
                "skipped_content_filtered": sorted(skipped), "pages": []}
    (args.output / "prompts").mkdir()
    for file in prompt_files:
        (args.output / "prompts" / file.name).write_bytes(file.read_bytes())
    started = time.perf_counter()
    for name, end in SAMPLES:
        if all((name, page) in skipped for page in range(1, end + 1)):
            continue
        payloads = preprocess_pages(ROOT / "data" / "inbox" / f"{name}.pdf", start_page=1, end_page=end)
        payloads = [p for p in payloads if (name, p["page"]) not in skipped]
        reference = json.loads((REFERENCES / f"{name}.parse.json").read_text(encoding="utf-8"))
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_PAGES) as pool:
            outcomes = list(pool.map(lambda payload: run_page(payload, prompt), payloads))
        for payload, outcome in zip(payloads, outcomes):
            filename = f"{name}.page-{payload['page']}"
            outcome["document"] = name
            if outcome["status"] == "parsed":
                outcome["metrics"] = score_page(ParsePage.model_validate(outcome["result"]), reference)
            (args.output / f"{filename}.json").write_text(json.dumps(outcome, indent=2, ensure_ascii=False), encoding="utf-8")
            (args.output / f"{filename}.png").write_bytes(base64.b64decode(payload["base64"]))
            manifest["pages"].append({k: v for k, v in outcome.items() if k != "result"})
            print(json.dumps({k: v for k, v in outcome.items() if k not in ("result", "document_sha256")}), flush=True)
        manifest["seconds"] = time.perf_counter() - started
        (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    manifest["seconds"] = time.perf_counter() - started
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
