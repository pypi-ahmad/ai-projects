"""Orchestrator.tick(): the one place that runs scheduled memory upkeep --
working-memory eviction, episodic eviction, and (opt-in) fact distillation.
Not part of the original Phase 1 stub list; the other stubs (compress vs.
recall vs. providers) didn't have a clean home for "run one maintenance
pass and report what changed," so it gets its own module.

Must not: construct its own WorkingMemory/EpisodicMemory/SemanticMemory --
callers (ui.py, scripts/seed_demo.py, tests) own those instances and pass
them in, so one process can point multiple Orchestrators at the same
stores if it needs to.

Next: src/memory/recall.py -- the read-side counterpart to tick().
"""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from memory import config
from memory.compress import Compressor, Distiller
from memory.episodic import Episode, EpisodicMemory, EvictionPolicy
from memory.semantic import Fact, SemanticMemory
from memory.working import WorkingMemory


class EpisodicConfig(BaseModel):
    max_rows: int | None = 500
    max_age_days: float | None = 30
    salience_threshold: float = 0.6


class SemanticConfig(BaseModel):
    near_dup_threshold: float = 0.92


class DistillConfig(BaseModel):
    recent_episodes_n: int = 20


class MemoryConfig(BaseModel):
    episodic: EpisodicConfig = Field(default_factory=EpisodicConfig)
    semantic: SemanticConfig = Field(default_factory=SemanticConfig)
    distill: DistillConfig = Field(default_factory=DistillConfig)


def load_memory_config(path: Path = config.MEMORY_YAML_PATH) -> MemoryConfig:
    if not path.exists():
        return MemoryConfig()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return MemoryConfig.model_validate(data)


class MemoryReport(BaseModel):
    working_evicted: int = 0
    episodes_written: int = 0
    episodes_evicted: int = 0
    facts_distilled: int = 0
    facts_deduped: int = 0
    compress_reason_counts: dict[str, int] = Field(default_factory=dict)


class Orchestrator:
    def __init__(
        self,
        working: WorkingMemory,
        episodic: EpisodicMemory,
        semantic: SemanticMemory,
        session_id: str,
        *,
        memory_config: MemoryConfig | None = None,
        compressor: Compressor | None = None,
        distiller: Distiller | None = None,
        fact_namespace: str | None = None,
    ) -> None:
        self.working = working
        self.episodic = episodic
        self.semantic = semantic
        self.session_id = session_id
        self.memory_config = memory_config or load_memory_config()
        self.compressor = compressor or Compressor()
        self.distiller = distiller or Distiller()
        self.fact_namespace = fact_namespace or session_id

    def tick(self, distill: bool = False) -> MemoryReport:
        compress_reasons: dict[str, int] = {}
        episodes_written = 0

        # 1. working.evict/compress -- evict() is a no-op if under cap.
        jobs = self.working.evict()
        if jobs:
            result = self.compressor.compress([job.item.text for job in jobs])
            compress_reasons[result.reason] = compress_reasons.get(result.reason, 0) + 1
            summary = Episode.create(
                self.session_id,
                "compress_summary",
                result.text,
                refs=[job.item.id for job in jobs],
            )
            self.episodic.write(summary)
            episodes_written = 1
        # Evicted items are already gone from WorkingMemory -- evict() did
        # that; nothing left here to separately "drop".

        # 2. episodic.evict
        policy = EvictionPolicy(
            max_rows=self.memory_config.episodic.max_rows,
            max_age_days=self.memory_config.episodic.max_age_days,
            salience_threshold=self.memory_config.episodic.salience_threshold,
        )
        episodes_evicted = self.episodic.evict(self.session_id, policy)

        # 3. optional distill
        facts_distilled = facts_deduped = 0
        if distill:
            facts_distilled, facts_deduped = self._distill()

        return MemoryReport(
            working_evicted=len(jobs),
            episodes_written=episodes_written,
            episodes_evicted=episodes_evicted,
            facts_distilled=facts_distilled,
            facts_deduped=facts_deduped,
            compress_reason_counts=compress_reasons,
        )

    def _distill(self) -> tuple[int, int]:
        n = self.memory_config.distill.recent_episodes_n
        # ponytail: fetches the whole session then slices the tail --
        # EpisodicMemory.list() only offers ORDER BY ts ASC. Add a
        # order="desc" option there if a session's history gets large
        # enough for this full fetch to matter.
        recent = self.episodic.list(self.session_id)[-n:]
        if not recent:
            return 0, 0

        result = self.distiller.distill(recent)
        distilled = deduped = 0
        threshold = self.memory_config.semantic.near_dup_threshold
        for fact_text in result.facts:
            existing = self.semantic.search(fact_text, namespace=self.fact_namespace, k=1)
            if existing and existing[0].score >= threshold:
                deduped += 1
                continue
            fact = Fact(
                text=fact_text,
                namespace=self.fact_namespace,
                # Batch distillation doesn't map a fact back to one specific
                # episode; point at the most recent one in the batch.
                source_episode_id=recent[-1].id,
            )
            self.semantic.upsert_fact(fact)
            distilled += 1
        return distilled, deduped
