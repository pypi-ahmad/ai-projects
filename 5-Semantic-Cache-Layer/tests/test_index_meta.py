import pytest

from src.embed.ollama_client import DEFAULT_EMBED_MODEL, REBUILD_EMBED_MODEL
from src.store.index_meta import (
    IndexMeta,
    RebuildRequiredError,
    ensure_embed_model_matches,
    load_index_meta,
    save_index_meta,
)


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "index_meta.json"
    meta = IndexMeta(embed_model=DEFAULT_EMBED_MODEL, dim=1024)

    save_index_meta(meta, path=path)

    assert load_index_meta(path=path) == meta


def test_load_missing_file_returns_none(tmp_path):
    assert load_index_meta(path=tmp_path / "missing.json") is None


def test_mrl_dim_roundtrip(tmp_path):
    path = tmp_path / "index_meta.json"
    meta = IndexMeta(embed_model=DEFAULT_EMBED_MODEL, dim=512, mrl_dim=512)

    save_index_meta(meta, path=path)

    assert load_index_meta(path=path).mrl_dim == 512


def test_matching_model_and_dim_passes():
    meta = IndexMeta(embed_model=DEFAULT_EMBED_MODEL, dim=1024)
    ensure_embed_model_matches(meta, requested_model=DEFAULT_EMBED_MODEL, requested_dim=1024)


def test_mismatched_model_raises_rebuild_required():
    meta = IndexMeta(embed_model=DEFAULT_EMBED_MODEL, dim=1024)

    with pytest.raises(RebuildRequiredError) as exc_info:
        ensure_embed_model_matches(
            meta, requested_model=REBUILD_EMBED_MODEL, requested_dim=2560
        )

    assert exc_info.value.code == "REBUILD_REQUIRED"


def test_mismatched_dim_same_model_raises_rebuild_required():
    meta = IndexMeta(embed_model=DEFAULT_EMBED_MODEL, dim=1024)

    with pytest.raises(RebuildRequiredError):
        ensure_embed_model_matches(meta, requested_model=DEFAULT_EMBED_MODEL, requested_dim=512)


def test_mrl_dim_is_the_effective_dim_for_matching():
    meta = IndexMeta(embed_model=DEFAULT_EMBED_MODEL, dim=1024, mrl_dim=512)

    ensure_embed_model_matches(meta, requested_model=DEFAULT_EMBED_MODEL, requested_dim=512)
    with pytest.raises(RebuildRequiredError):
        ensure_embed_model_matches(meta, requested_model=DEFAULT_EMBED_MODEL, requested_dim=1024)
