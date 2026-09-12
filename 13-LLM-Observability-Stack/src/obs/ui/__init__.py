"""Streamlit trace viewer + alert inbox. Run via run.cmd or:
uv run streamlit run src/obs/ui/app.py --server.port 7017

Talks to the FastAPI backend over HTTP (obs.ui.api_client); does not import
obs.export/obs.alerts directly.
"""
