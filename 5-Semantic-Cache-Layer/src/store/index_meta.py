"""Sidecar metadata for the (not-yet-built) vector index.

Persisted at data/cache/index_meta.json, next to where the Qdrant index
will live (docs/RUNBOOK.md). Exists so a lookup can refuse to run against
an index built with a different embed model or dimension instead of
silently returning garbage.

`dim` is the actual vector dimension in the index. `mrl_dim` is set only
when that dimension came from an explicit MRL truncation request (Ollama's
`dimensions` param) rather than the model's natural output size -- it's an
annotation of *why* dim is what it is, not a second source of truth.
"""

from pathlib import Path

from pydantic import BaseModel

DEFAULT_INDEX_META_PATH = Path("data/cache/index_meta.json")


class IndexMeta(BaseModel):
    embed_model: str
    dim: int
    mrl_dim: int | None = None


class RebuildRequiredError(Exception):
    """A lookup's embed model/dimension doesn't match the built index.

    See docs/RUNBOOK.md: wipe and rebuild the index after an embed-model
    (or MRL dimension) change -- there is no online migration.
    """

    code = "REBUILD_REQUIRED"

    def __init__(self, *, requested_model: str, requested_dim: int, index_meta: IndexMeta):
        self.requested_model = requested_model
        self.requested_dim = requested_dim
        self.index_meta = index_meta
        super().__init__(
            f"index was built with {index_meta.embed_model} "
            f"(dim={_effective_dim(index_meta)}); lookup requested "
            f"{requested_model} (dim={requested_dim}) -- wipe and rebuild "
            "the index before searching (docs/RUNBOOK.md)."
        )


def _effective_dim(meta: IndexMeta) -> int:
    return meta.mrl_dim if meta.mrl_dim is not None else meta.dim


def load_index_meta(path: Path = DEFAULT_INDEX_META_PATH) -> IndexMeta | None:
    """None means no index has been built yet -- not a mismatch."""
    if not path.exists():
        return None
    return IndexMeta.model_validate_json(path.read_text(encoding="utf-8"))


def save_index_meta(meta: IndexMeta, path: Path = DEFAULT_INDEX_META_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(meta.model_dump_json(indent=2), encoding="utf-8")


def ensure_embed_model_matches(
    meta: IndexMeta, *, requested_model: str, requested_dim: int
) -> None:
    """Refuse to search if the lookup's embed model/dim doesn't match the index."""
    if requested_model != meta.embed_model or requested_dim != _effective_dim(meta):
        raise RebuildRequiredError(
            requested_model=requested_model,
            requested_dim=requested_dim,
            index_meta=meta,
        )
