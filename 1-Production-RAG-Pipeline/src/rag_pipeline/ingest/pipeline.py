"""Walk an input folder, parse/OCR/translate each file, write one JSONL record per file."""

import hashlib
import json
import logging
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import ollama

from rag_pipeline.config import load_settings
from rag_pipeline.ingest.ocr import ocr_image, unload_model
from rag_pipeline.ingest.parsers import SUPPORTED_EXTENSIONS, get_mime, parse_file
from rag_pipeline.ingest.records import IngestRecord, PageRecord
from rag_pipeline.ingest.translate import TRANSLATE_MODEL, detect_lang, translate_pages

logger = logging.getLogger(__name__)

OUTPUT_FILENAME = "ingest.jsonl"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_id(relative_path: str) -> str:
    return hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:16]


def walk_files(input_dir: Path) -> list[Path]:
    return sorted(
        p for p in input_dir.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    )


def load_existing_records(out_path: Path) -> dict[str, dict]:
    if not out_path.exists():
        return {}
    records: dict[str, dict] = {}
    for line in out_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        records[record["path"]] = record
    return records


def process_file(
    path: Path,
    relative_path: str,
    file_hash: str,
    client: ollama.Client,
    used_models: set[str],
    *,
    translate: bool,
    target_lang: str,
) -> IngestRecord:
    parsed_pages = parse_file(path)
    page_records = []
    for page in parsed_pages:
        if page.needs_ocr:
            assert page.image_bytes is not None, "needs_ocr pages always carry image_bytes"
            text, confidence, model_used = ocr_image(page.image_bytes, client)
            used_models.add(model_used)
            page_records.append(
                PageRecord(page=page.page, text=text, ocr=True, confidence=confidence)
            )
        else:
            page_records.append(PageRecord(page=page.page, text=page.text, ocr=False))

    text_by_page = [p.text for p in page_records]
    lang = detect_lang("\n".join(text_by_page))

    translation = None
    if translate and lang not in ("unknown", target_lang):
        used_models.add(TRANSLATE_MODEL)
        translated_pages = translate_pages(text_by_page, lang, target_lang, client)
        translation = {"target_lang": target_lang, "text_by_page": translated_pages}

    return IngestRecord(
        id=make_id(relative_path),
        path=relative_path,
        mime=get_mime(path),
        page_count=len(page_records),
        text_by_page=page_records,
        ocr_used=any(p.ocr for p in page_records),
        lang=lang,
        hash=file_hash,
        ingested_at=datetime.now(UTC).isoformat(),
        translation=translation,
    )


def run_ingest(
    input_dir: Path,
    out_dir: Path,
    *,
    translate: bool = False,
    target_lang: str = "en",
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / OUTPUT_FILENAME
    existing = load_existing_records(out_path)

    client = ollama.Client(host=load_settings().ollama_host)
    used_models: set[str] = set()
    results: list[dict] = []

    for path in walk_files(input_dir):
        # .as_posix() (not str()) so source_path is forward-slash on every OS --
        # a Windows backslash path here would silently fail to match a
        # hand-written qa.jsonl relevant_sources entry.
        relative_path = path.relative_to(input_dir).as_posix()
        file_hash = sha256_file(path)
        cached = existing.get(relative_path)
        if cached and cached.get("hash") == file_hash:
            results.append(cached)
            logger.info("skip (unchanged): %s", relative_path)
            continue
        record = process_file(
            path,
            relative_path,
            file_hash,
            client,
            used_models,
            translate=translate,
            target_lang=target_lang,
        )
        results.append(asdict(record))
        logger.info("ingested: %s", relative_path)

    with out_path.open("w", encoding="utf-8") as f:
        for record in results:
            f.write(json.dumps(record, ensure_ascii=False))
            f.write("\n")

    for model in used_models:
        unload_model(client, model)

    return out_path
