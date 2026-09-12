# Task

**Support ticket → structured JSON.** One narrow, specialized format; not generic chat. Chosen
so LoRA has something concrete to earn its keep on (a fixed output schema), and so the bake-off
against prompt-only has an unambiguous right/wrong answer per field.

Data is 100% synthetic (teacher-generated), by design; this avoids scraping or fine-tuning on
any copyrighted third-party ticket corpus.

## Input

Free-text customer support ticket, 2-5 sentences, first person.

## Target schema

`TicketTarget` (`src/data/schema.py`), one label per ticket:

| Field | Type | Allowed values |
|---|---|---|
| `priority` | enum | `low`, `medium`, `high`, `urgent` |
| `product` | enum | `billing`, `account`, `mobile_app`, `web_app`, `api`, `integrations` |
| `sentiment` | enum | `positive`, `neutral`, `negative` |
| `next_action` | enum | `escalate`, `request_info`, `resolve`, `refund`, `schedule_callback` |

All four are closed label sets (not free text); this is a classification task expressed as JSON,
not open-ended generation. Assumption, adjustable: these six product categories and five actions
were picked as a generic-but-plausible SaaS support taxonomy; there's no external label spec to
match since the data is synthetic.

## Example row (`data/processed/{train,val,test}.jsonl`, one `TicketExample` per line)

```json
{
  "input": "I noticed that my subscription was charged an unexpected fee for an additional feature I didn't intend to purchase. Could you please look into this and let me know how to adjust my plan correctly?",
  "target": {"priority": "medium", "product": "billing", "sentiment": "negative", "next_action": "request_info"},
  "split": "train",
  "source": "synthetic",
  "teacher_model": "granite4.1:3b"
}
```

(Real output, generated end-to-end via `granite4.1:3b` during Phase 2 smoke test; see
`data/processed/train.jsonl`.)

## Success shape for the bake-off

The trained model and the prompt-only baseline both have to emit a JSON object matching
`TicketTarget`. Scoring is per-field exact match against the held-out `test.jsonl` labels (see
`docs/EVAL.md`, not yet written).
