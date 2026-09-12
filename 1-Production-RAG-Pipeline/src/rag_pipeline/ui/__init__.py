"""Streamlit UI package: a thin presentation layer over the ingest/chunk/index/retrieve/
generate/eval pipelines. Must not contain pipeline logic of its own -- app.py calls the
same run_* functions the CLIs use, never a separate code path. See app.py.
"""
