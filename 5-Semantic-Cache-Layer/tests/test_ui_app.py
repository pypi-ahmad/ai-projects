"""AppTest smoke test for src/ui/app.py (docs/developing-with-streamlit
testing guidance: AppTest over a real browser for "does the app compute
and display the right thing").

This is the one test in the suite that isn't hermetic: it runs the real
app against the real default cache/config paths, so it needs a running
Ollama and the demo seed applied (scripts/seed_demo.py). It skips itself
if Ollama isn't reachable rather than failing the whole suite.
"""

import urllib.request
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP_PATH = Path(__file__).resolve().parent.parent / "src" / "ui" / "app.py"


def _ollama_is_up() -> bool:
    try:
        urllib.request.urlopen("http://localhost:11434/api/version", timeout=1)
        return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _ollama_is_up(), reason="requires a running Ollama")


def test_app_loads_without_exception():
    at = AppTest.from_file(str(APP_PATH)).run(timeout=30)
    assert not at.exception


def test_verified_paraphrase_is_a_hit():
    # Score checked live against the real qwen3-embedding:0.6b model
    # (0.9441) -- comfortably above the 0.89 default threshold, unlike
    # several looser paraphrases tried during calibration. See
    # docs/TECHNICAL.md's threshold section for the full picture.
    at = AppTest.from_file(str(APP_PATH)).run(timeout=30)

    at.text_input(key="query_text").set_value("How can I reset my password?")
    at.button[0].click().run(timeout=30)  # the lookup form's submit button

    assert not at.exception
    assert at.success  # "Hit (...)" rendered
    assert not at.warning  # no "Miss"


def test_unrelated_query_is_a_miss():
    at = AppTest.from_file(str(APP_PATH)).run(timeout=30)

    at.text_input(key="query_text").set_value("What's the airspeed velocity of an unladen swallow?")
    at.button[0].click().run(timeout=30)

    assert not at.exception
    assert at.warning  # "Miss" rendered
    assert not at.success
    # Miss path renders the generate-and-store demo section.
    assert at.selectbox(key="gen_provider")
