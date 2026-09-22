"""Active layout-parsing entry point. `parse_document` processes a page range
in source order and calls `parse_page` (a thin wrapper over
src/llm.py's `_invoke_structured`/`ParsePage`) once per page, then writes
`<output_dir>/<doc_sha>.json` itself -- this is the only unconditionally-called
consumer of src/llm.py's model-call plumbing in the active graph (see
src/graph.py).

Must not: let one page's failure abort the others, or let a failure escape
as anything other than a `PageDiagnostic` entry (see `parse_payload`'s
exception handling below) -- the active graph's contract is that a partial
or fully-failed parse is reported, never raised.

Next: src/markdown.py, which renders whatever `ParseResult` this produces.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path

from openai import ContentFilterFinishReasonError

from src.llm import _build_llm, _image_message, _invoke_structured
from src.preprocess import preprocess_pages
from src.prompts import render_prompt
from src.models import DEFAULT_MODEL, MODEL_RATES
from src.layout import ParsePage, ParseResult
from src.diagnostics import ExtractionCallError, PageDiagnostic

# Pages are parsed in order so each call can use preceding-page context.
MAX_PARALLEL_PAGES = 1


def _page_context(page: ParsePage) -> str:
    parts = []
    for block in page.blocks:
        if block.type == "table" and block.table:
            parts.extend(" | ".join(row) for row in block.table)
        elif block.text:
            parts.append(block.text)
    return "\n".join(parts)


def parse_page(
    image_b64: str, mime: str, page_number: int, width_px: int, height_px: int,
    *, diagnostics: list[PageDiagnostic] | None = None, model: str = DEFAULT_MODEL,
    usage_entries: list[dict] | None = None,
    document_context: str = "", total_pages: int = 1,
) -> ParsePage:
    llm = _build_llm(model=model)
    text = render_prompt(
        "parse-page", page_number=page_number, total_pages=total_pages,
        width_px=width_px, height_px=height_px, document_context=document_context,
    )
    result = _invoke_structured(
        llm, ParsePage, [_image_message(text, image_b64, mime)], call_name="parse_page",
        diagnostics=diagnostics, usage_entries=usage_entries,
    )
    # We already know the true page/geometry from preprocessing; only the
    # model's `blocks` are worth trusting.
    return result.model_copy(update={"page": page_number, "width_px": width_px, "height_px": height_px})


def parse_document(
    path: str | Path, *, start_page: int = 1, end_page: int | None = None,
    model: str = DEFAULT_MODEL,
    usage_entries: list[dict] | None = None,
    on_progress: Callable[[dict], None] | None = None,
    output_dir: str | Path = "data/parse",
) -> ParseResult:
    """Layout-parse every page in [start_page, end_page] (1-based, inclusive;
    end_page=None means through the last page -- there is no page cap).

    Pages are parsed sequentially. Each successful page contributes bounded
    context to the next page so headings and continued structures remain
    coherent across the document.
    """
    if model not in MODEL_RATES:
        raise ValueError("Unsupported model")
    pages_payload = preprocess_pages(path, start_page=start_page, end_page=end_page)
    if not pages_payload:
        raise ValueError("Page range contains no pages")
    doc_sha = pages_payload[0]["doc_sha256"]

    context_parts: list[str] = []

    def parse_payload(payload: dict) -> tuple[ParsePage | None, PageDiagnostic]:
        diagnostics = []
        try:
            page = parse_page(
                payload["base64"],
                payload["mime"],
                payload["page"],
                payload["width"],
                payload["height"],
                diagnostics=diagnostics,
                model=model,
                usage_entries=usage_entries,
                document_context="\n\n".join(context_parts)[-12000:],
                total_pages=len(pages_payload),
            )
            diagnostic = diagnostics[-1] if diagnostics else PageDiagnostic(outcome="parsed")
            return page, diagnostic.model_copy(update={"page": payload["page"]})
        except ExtractionCallError as exc:
            return None, exc.diagnostic.model_copy(update={"page": payload["page"]})
        except ContentFilterFinishReasonError:
            return None, PageDiagnostic(page=payload["page"], outcome="content_filtered", requested_model=model)
        except Exception:
            return None, PageDiagnostic(page=payload["page"], outcome="invalid_response", requested_model=model)

    outcomes = []
    successful = 0
    for payload in pages_payload:
        outcome = parse_payload(payload)
        outcomes.append(outcome)
        if outcome[0] is not None:
            successful += 1
            context_parts.append(_page_context(outcome[0]))
        if on_progress:
            on_progress({"completed": len(outcomes), "total": len(pages_payload),
                         "successful": successful, "failed": len(outcomes) - successful})

    pages = [page for page, _ in outcomes if page is not None]
    content_filtered_pages = [
        diagnostic.page for _, diagnostic in outcomes if diagnostic.outcome == "content_filtered"
    ]
    result = ParseResult(
        doc_sha=doc_sha,
        pages=pages,
        content_filtered_pages=content_filtered_pages,
        page_diagnostics=[diagnostic for _, diagnostic in outcomes],
    )

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{doc_sha}.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")

    return result


def _main() -> None:
    parser = argparse.ArgumentParser(description="Parse a document's pages into layout blocks.")
    parser.add_argument("--path", required=True, help="Path to a scanned image or PDF")
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument("--end-page", type=int, default=None, help="Omit for through the last page")
    args = parser.parse_args()

    result = parse_document(args.path, start_page=args.start_page, end_page=args.end_page)
    print(f"doc_sha: {result.doc_sha}")
    print(f"pages parsed: {len(result.pages)}")
    print(f"written to data/parse/{result.doc_sha}.json")


if __name__ == "__main__":
    _main()
