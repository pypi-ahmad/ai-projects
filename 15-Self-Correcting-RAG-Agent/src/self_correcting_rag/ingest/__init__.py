"""Parse supported files (.txt/.md/.pdf-text) into page text, then chunk that text.
Must not embed or index anything -- that's index/'s job. Start reading at
ingest/pipeline.py, which ties parsers.py and chunker.py together.
"""
