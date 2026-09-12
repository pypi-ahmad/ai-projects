"""Seed a demo conversation, then recall a planted fact from it.

Default mode: appends 12 turns of a fake project-kickoff conversation
(codename planted in turn 3) into a small-cap WorkingMemory so it actually
overflows into episodic memory partway through -- then runs
tick(distill=True) and recall() to show the codename survives.

--recall-only: skips seeding entirely and just recalls, proving the data
survives a real process restart (SQLite file + Qdrant path on disk, not
just this process's memory) -- run the default mode once, then run this
script again with --recall-only in a separate process invocation.

Writes to the REAL project data store (data/memory/), under
session_id="demo" -- open the Streamlit UI afterward with Session ID
"demo" to inspect what landed where. Default mode is safe to re-run; it
loads prior working-memory state first rather than clobbering it.

Must not: be run at the same time as the Streamlit UI (or another copy of
this script) against the same data/memory/ path -- embedded Qdrant only
supports one process at a time (see docs/RUNBOOK.md).
"""

import argparse

from memory.episodic import EpisodicMemory
from memory.orchestrator import Orchestrator
from memory.recall import recall
from memory.semantic import SemanticMemory
from memory.working import WorkingItem, WorkingMemory

SESSION_ID = "demo"
QUERY = "What is the codename for this initiative?"

TURNS = [
    ("user", "Let's kick off the new initiative properly this time."),
    ("assistant", "Sounds good. What should we call it internally?"),
    ("user", "The codename for this initiative is Nimbus Finch."),
    ("assistant", "Got it, Nimbus Finch it is. What's the first milestone?"),
    ("user", "We need a working prototype by the end of next month."),
    ("assistant", "Understood, I'll draft a rough timeline."),
    ("user", "Also loop in the design team early this time, not at the end."),
    ("assistant", "Noted, I'll set up a kickoff meeting with them."),
    ("user", "Budget is tight, so keep the vendor list short."),
    ("assistant", "Will do, I'll stick to two vendors max for quotes."),
    ("user", "One more thing: no public announcements until legal signs off."),
    ("assistant", "Understood, I'll keep this internal until legal clears it."),
]


def _seed(working: WorkingMemory, episodic: EpisodicMemory, semantic: SemanticMemory) -> None:
    orchestrator = Orchestrator(working, episodic, semantic, SESSION_ID)
    print(f"Seeding session {SESSION_ID!r} with {len(TURNS)} turns (working token_cap=60)...")
    for i, (role, text) in enumerate(TURNS, start=1):
        working.append(WorkingItem.create(role, text))
        report = orchestrator.tick()
        if report.working_evicted:
            print(
                f"  turn {i}: overflow -> compressed {report.working_evicted} items "
                f"({report.compress_reason_counts}) into 1 episode"
            )
    working.snapshot()

    print("\nDistilling episodes into facts (tick(distill=True))...")
    report = orchestrator.tick(distill=True)
    print(f"  facts_distilled={report.facts_distilled} facts_deduped={report.facts_deduped}")


def _recall_and_report(working: WorkingMemory, episodic: EpisodicMemory, semantic: SemanticMemory) -> bool:
    print(f"\nrecall(query={QUERY!r}, session_id={SESSION_ID!r}, token_budget=500):\n")
    packed = recall(working, episodic, semantic, QUERY, SESSION_ID, token_budget=500)
    print(packed.text)
    print(f"\n[{packed.token_count} tokens, {len(packed.provenance)} provenance entries]")
    for p in packed.provenance:
        print(f"  {p.store:9s} id={p.id[:8]} score={p.score}")

    found = "Nimbus Finch" in packed.text
    print(f"\n{'PASS' if found else 'FAIL'}: 'Nimbus Finch' {'found' if found else 'missing'} in recall result.")
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--recall-only",
        action="store_true",
        help="skip seeding; load persisted state in this (fresh) process and just recall",
    )
    args = parser.parse_args()

    working = WorkingMemory(token_cap=60)
    working.load()  # restore prior state -- never silently clobber it on re-run
    episodic = EpisodicMemory()
    semantic = SemanticMemory()

    if args.recall_only:
        print(f"--recall-only: loading persisted state for session {SESSION_ID!r}, skipping seeding...")
    else:
        _seed(working, episodic, semantic)

    _recall_and_report(working, episodic, semantic)

    episodic.close()
    semantic.close()


if __name__ == "__main__":
    main()
