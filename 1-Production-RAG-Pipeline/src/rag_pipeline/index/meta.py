"""Small on-disk record of which embed model built the current index, so the
query path (Phase 5+) embeds with the same model rather than re-deriving it
from vector dimension alone.
"""

import json
from pathlib import Path

META_FILENAME = "index_meta.json"


def write_index_meta(index_dir: Path, embed_model: str) -> None:
    path = index_dir / META_FILENAME
    path.write_text(json.dumps({"embed_model": embed_model}), encoding="utf-8")


def read_index_meta(index_dir: Path) -> dict:
    path = index_dir / META_FILENAME
    if not path.exists():
        raise RuntimeError(
            f"no {META_FILENAME} found under {index_dir} -- run "
            f"`uv run python -m rag_pipeline.index` first"
        )
    return json.loads(path.read_text(encoding="utf-8"))
