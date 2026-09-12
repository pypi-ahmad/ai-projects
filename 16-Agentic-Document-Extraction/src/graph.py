"""Defines and runs the active LangGraph pipeline: `preprocess -> parse ->
END` (see docs/ARCHITECTURE.md). `build_graph`/`run_graph` are the only
supported entry points for running a document through this project --
src/ui/app.py and this module's own `_main` both go through `run_graph`.

Must not: re-add the removed `extract -> validate -> maybe_crop ->
commit`/`review` nodes to `build_graph()` without re-reading
docs/ADR-0001-UNWIRE-INVOICE-PIPELINE.md first -- that path assumed an
invoice's arithmetic could be checked, which doesn't hold for prior-auth
documents. The code for it (src/extract.py, src/validate.py, src/regions.py)
is intentionally left in place, just unwired.

Next: src/parse.py, where the actual per-page work happens.
"""

from __future__ import annotations

import argparse
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from src import usage
from src.models import DEFAULT_MODEL
from src.annotate import annotate_document
from src.markdown import save_markdown_for_doc
from src.parse import parse_document
from src.preprocess import preprocess
from src.schema import ParseResult

# Invoice extraction/validation/crop-retry/commit/review was removed from the
# active graph (real prior-auth documents have no arithmetic to validate --
# the Invoice schema doesn't fit them). src/extract.py, src/validate.py,
# src/regions.py, and the Invoice/Region/ValidationReport schemas in
# src/schema.py are untouched on disk (not deleted, just unwired) for when a
# replacement schema/validation model is defined. See docs/ARCHITECTURE.md.


class GraphState(TypedDict, total=False):
    image_path: str
    start_page: int
    end_page: int | None
    model: str
    doc_sha: str
    base64_image: str
    mime: str
    parse_result: ParseResult | None
    markdown: str | None
    parse_error: str | None
    annotated_pdf_path: str | None
    status: str


def node_preprocess(state: GraphState) -> dict:
    print(f"[ADE] preprocess: {state['image_path']}")
    result = preprocess(state["image_path"])
    return {
        "doc_sha": result["doc_sha256"],
        "base64_image": result["base64"],
        "mime": result["mime"],
    }


def node_parse(state: GraphState) -> dict:
    # Best-effort: a parse failure is reported, not raised -- the caller can
    # still see doc_sha/status even if layout parsing didn't work.
    try:
        result = parse_document(
            state["image_path"],
            start_page=state.get("start_page", 1),
            end_page=state.get("end_page"),
            model=state.get("model", DEFAULT_MODEL),
        )
        filtered_pages = ", ".join(str(page) for page in result.content_filtered_pages)
        parse_error = (
            f"Pages rejected by content filter: {filtered_pages}"
            if result.content_filtered_pages
            else None
        )
        other_failures = [d for d in result.page_diagnostics if d.outcome not in ("parsed", "content_filtered")]
        if other_failures:
            summary = "; ".join(f"Page {d.page}: {d.outcome}" for d in other_failures)
            parse_error = f"{parse_error}; {summary}" if parse_error else summary
        if not result.pages:
            return {
                "parse_result": result,
                "markdown": None,
                "parse_error": parse_error,
                "annotated_pdf_path": None,
                "status": "parse_failed",
            }

        md_path = save_markdown_for_doc(result)
        parse_status = "partial" if parse_error else "ok"
        print(f"[ADE] parse: {parse_status}, {len(result.pages)} page(s) -> {md_path}")

        annotated_pdf_path = None
        try:
            # Annotation is a secondary, human-facing overlay on top of an
            # already-successful parse; a failure here (e.g. a Pillow/font
            # issue) must not discard the parse result that's already in hand.
            pdf_path, _meta_path = annotate_document(state["image_path"], result)
            annotated_pdf_path = str(pdf_path)
        except Exception as exc:
            print(f"[ADE] annotate: skipped ({exc})")

        return {
            "parse_result": result,
            "markdown": md_path.read_text(encoding="utf-8"),
            "parse_error": parse_error,
            "annotated_pdf_path": annotated_pdf_path,
            "status": "parsed_partial" if parse_error else "parsed",
        }
    except Exception as exc:
        print(f"[ADE] parse: skipped ({exc})")
        return {
            "parse_result": None,
            "markdown": None,
            "parse_error": str(exc),
            "annotated_pdf_path": None,
            "status": "parse_failed",
        }


def build_graph():
    graph = StateGraph(GraphState)
    graph.add_node("preprocess", node_preprocess)
    graph.add_node("parse", node_parse)

    graph.add_edge(START, "preprocess")
    graph.add_edge("preprocess", "parse")
    graph.add_edge("parse", END)

    return graph.compile()


def run_graph(image_path: str, *, start_page: int = 1, end_page: int | None = None,
              model: str = DEFAULT_MODEL) -> dict:
    usage.reset()
    app = build_graph()
    initial_state: GraphState = {
        "image_path": image_path,
        "start_page": start_page,
        "end_page": end_page,
        "model": model,
    }
    result = app.invoke(initial_state)
    result["token_usage"] = usage.get_all()
    return result


def _main() -> None:
    parser = argparse.ArgumentParser(description="Parse a document into Markdown + an annotated PDF.")
    parser.add_argument("--path", required=True, help="Path to a document image or PDF")
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument("--end-page", type=int, default=None, help="Omit for through the last page")
    args = parser.parse_args()

    result = run_graph(args.path, start_page=args.start_page, end_page=args.end_page)

    print(f"status: {result.get('status')}")
    print(f"doc_sha: {result.get('doc_sha')}")
    if result.get("parse_error"):
        print(f"parse_error: {result['parse_error']}")
    totals = usage.totals(result.get("token_usage", []))
    print(f"tokens: input={totals['input_tokens']} cached={totals['cached_tokens']} output={totals['output_tokens']}")


if __name__ == "__main__":
    _main()
