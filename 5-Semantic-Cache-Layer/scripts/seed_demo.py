"""One-time demo seed: puts 9 FAQ pairs into namespace "demo" so the
Streamlit UI (src/ui/app.py) hits on first try.

    uv run python scripts/seed_demo.py

Safe to re-run -- each call inserts new points (put() doesn't dedupe on
query_norm), so running this twice doubles the entries rather than
erroring. Use `python -m src.cache` or the UI's "Clear namespace" button
to reset first if that matters to you.
"""

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.cache.models import CacheRecord
from src.cache.normalize import normalize_query
from src.cache.service import SemanticCache

NAMESPACE = "demo"

FAQ_PAIRS = [
    ("What are your business hours?", "We're open Monday to Friday, 9am to 6pm ET."),
    ("How do I reset my password?", "Go to Settings > Account > Reset password, and follow the emailed link."),
    ("What is your refund policy?", "Refunds are available within 30 days of purchase, no questions asked."),
    ("Do you offer international shipping?", "Yes, we ship to over 40 countries; rates are calculated at checkout."),
    ("How can I contact support?", "Email support@example.com or use the in-app chat, available 24/7."),
    ("What payment methods do you accept?", "We accept all major credit cards, PayPal, and Apple Pay."),
    ("How do I cancel my subscription?", "Go to Settings > Billing > Cancel subscription -- it takes effect at the end of the current period."),
    ("Is there a free trial?", "Yes, every plan includes a 14-day free trial, no credit card required."),
    ("Where is my order?", "Track your order's status anytime from the Orders page in your account."),
]


def main() -> None:
    cache = SemanticCache()
    for query, answer in FAQ_PAIRS:
        record = CacheRecord(
            id=str(uuid.uuid4()),
            namespace=NAMESPACE,
            query_raw=query,
            query_norm=normalize_query(query),
            answer=answer,
            producer_model="manual",
            provider="seed",
            created_at=datetime.now(timezone.utc),
        )
        cache.put(record)
        print(f"seeded: {query!r}")
    print(f"Done -- {len(FAQ_PAIRS)} entries in namespace '{NAMESPACE}'.")


if __name__ == "__main__":
    main()
