"""Synthetic support-ticket dataset generator. Must not itself score or judge model quality —
that starts at src/eval/baseline.py, which reads the jsonl files this module writes.

CLI: uv run python -m src.data.generate --n-train 200 --n-val 40 --n-test 40
"""

import argparse
import logging
import random
from collections import Counter
from pathlib import Path

from src.data.schema import GeneratedRow, TicketExample, parse_generated_row
from src.providers import get_teacher
from src.providers.base import TeacherClient

logger = logging.getLogger(__name__)

DEFAULT_OUT_DIR = Path("data/processed")

_PRODUCTS = ["billing", "account", "mobile_app", "web_app", "api", "integrations"]
_TONES = ["frustrated", "confused", "polite but urgent", "calm", "angry", "worried", "apologetic"]

SYSTEM_PROMPT = """You write one realistic customer support ticket for a SaaS product.
Return ONLY a single JSON object, no markdown, no commentary, with exactly these keys:
{{
  "ticket": "<2-5 sentence support ticket text, first person, varied wording>",
  "priority": "<one of: low, medium, high, urgent>",
  "product": "<one of: billing, account, mobile_app, web_app, api, integrations>",
  "sentiment": "<one of: positive, neutral, negative>",
  "next_action": "<one of: escalate, request_info, resolve, refund, schedule_callback>"
}}
The four label values must genuinely match the ticket text you write.
This is ticket #{index} of a diverse batch: use a fresh scenario and opening sentence, do not
reuse a template from earlier tickets. Suggestion (you may deviate if it fits better): {hint}"""

REPAIR_PROMPT = """The text below was supposed to be a single JSON object with exactly these keys:
ticket (string), priority (one of low/medium/high/urgent), product (one of billing/account/
mobile_app/web_app/api/integrations), sentiment (one of positive/neutral/negative), next_action
(one of escalate/request_info/resolve/refund/schedule_callback). It failed to parse. Return ONLY
the corrected JSON object, nothing else.

--- broken text ---
{broken}"""


# product cycles deterministically by index (so a full batch covers all products roughly evenly)
# while tone is random (so same-product tickets still read differently); it's a suggestion in the
# prompt, not a constraint — the teacher's actual label can disagree.
def _hint(i: int) -> str:
    product = _PRODUCTS[i % len(_PRODUCTS)]
    tone = random.choice(_TONES)
    return f"a '{product}' issue, written in a {tone} tone"


# Cheap proxy for "the teacher is repeating a template": compares only the first 20 characters,
# not full ticket text. Cheap and order-independent, but two different tickets that happen to
# open identically would also count as a duplicate here.
def _dup_ratio(rows: list[GeneratedRow]) -> float:
    if not rows:
        return 0.0
    prefixes = [r.ticket[:20] for r in rows]
    return 1 - (len(set(prefixes)) / len(prefixes))


def _histogram(rows: list[GeneratedRow]) -> dict[str, Counter]:
    return {
        field: Counter(getattr(r, field) for r in rows)
        for field in ("priority", "product", "sentiment", "next_action")
    }


def generate_rows(
    n: int,
    teacher: TeacherClient,
    repair_teacher: TeacherClient | None = None,
    max_dup_ratio: float = 0.4,
) -> list[GeneratedRow]:
    """Call `teacher` n times, validate each response, repair-once on failure, drop the rest."""
    rows: list[GeneratedRow] = []
    dropped = 0
    for i in range(n):
        raw = teacher.complete(SYSTEM_PROMPT.format(index=i + 1, hint=_hint(i)))
        try:
            row = parse_generated_row(raw)
        except ValueError:
            row = None
            # Exactly one repair attempt, not a retry loop — a row that fails repair is dropped,
            # never resubmitted to `teacher`.
            if repair_teacher is not None:
                fixed = repair_teacher.complete(REPAIR_PROMPT.format(broken=raw))
                try:
                    row = parse_generated_row(fixed)
                except ValueError:
                    row = None
        if row is None:
            dropped += 1
            continue
        rows.append(row)

    # Checked after generation completes, not per-row — so a bad batch still costs the full n
    # teacher calls before this raises.
    ratio = _dup_ratio(rows)
    if ratio > max_dup_ratio:
        raise RuntimeError(
            f"diversity check failed: {ratio:.0%} duplicate first-20-chars ticket prefixes "
            f"(max allowed {max_dup_ratio:.0%}); teacher is producing repetitive templates"
        )
    logger.info(
        "generated %d/%d rows (%d dropped), dup_ratio=%.2f, label histogram=%s",
        len(rows), n, dropped, ratio, _histogram(rows),
    )
    return rows


def to_examples(rows: list[GeneratedRow], split: str, teacher_model: str) -> list[TicketExample]:
    return [
        TicketExample(
            input=r.ticket,
            # `target` is typed as TicketTarget; Pydantic validates/coerces this plain dict into
            # one on construction, so there's no separate TicketTarget(...) call here.
            target=r.model_dump(include={"priority", "product", "sentiment", "next_action"}),
            split=split,
            teacher_model=teacher_model,
        )
        for r in rows
    ]


def write_jsonl(examples: list[TicketExample], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for ex in examples:
            f.write(ex.model_dump_json() + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n-train", type=int, default=200)
    parser.add_argument("--n-val", type=int, default=40)
    parser.add_argument("--n-test", type=int, default=40)
    parser.add_argument("--teacher", default="granite4.1:3b", help="Ollama tag or cloud model name")
    parser.add_argument("--repair-model", default="qwen3.5:0.8b", help="empty string disables repair")
    parser.add_argument("--max-dup-ratio", type=float, default=0.4)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    teacher = get_teacher(args.teacher)
    repair_teacher = get_teacher(args.repair_model) if args.repair_model else None

    for split, n in (("train", args.n_train), ("val", args.n_val), ("test", args.n_test)):
        if n <= 0:
            continue  # e.g. --n-val 0: that split's jsonl file is never written, not written empty
        rows = generate_rows(n, teacher, repair_teacher, args.max_dup_ratio)
        examples = to_examples(rows, split, teacher.model_name)
        out_path = args.out_dir / f"{split}.jsonl"
        write_jsonl(examples, out_path)
        logger.info("wrote %d rows to %s", len(examples), out_path)


if __name__ == "__main__":
    main()
