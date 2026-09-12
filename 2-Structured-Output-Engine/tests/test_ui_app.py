"""Streamlit UI, via st.testing.v1.AppTest (in-process, headless — no
browser, no live provider needed for these). Run: uv run python -m
unittest tests.test_ui_app -v
"""

import os
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from streamlit.testing.v1 import AppTest

APP_PATH = str(Path(__file__).resolve().parent.parent / "src" / "ui" / "app.py")


@contextmanager
def without_env(*names: str):
    with mock.patch.dict(os.environ, {}, clear=False):
        for name in names:
            os.environ.pop(name, None)
        yield


class AppLoadTests(unittest.TestCase):
    def test_loads_without_exception(self):
        at = AppTest.from_file(APP_PATH, default_timeout=10).run()
        self.assertFalse(at.exception)
        self.assertEqual(len(at.tabs), 3)

    def test_all_four_schemas_and_paste_option_available(self):
        at = AppTest.from_file(APP_PATH, default_timeout=10).run()
        options = at.selectbox(key="ui_schema_choice").options
        for name in ("contact_record", "invoice_draft", "meeting_notes", "classification_result"):
            self.assertIn(name, options)
        self.assertIn("Paste JSON Schema", options)


class SchemaTabTests(unittest.TestCase):
    def test_registry_schema_shows_json_schema_and_example(self):
        at = AppTest.from_file(APP_PATH, default_timeout=10).run()
        at.selectbox(key="ui_schema_choice").select("contact_record").run()
        self.assertFalse(at.exception)
        self.assertGreaterEqual(len(at.json), 2)  # schema + example

    def test_paste_invalid_json_shows_warning(self):
        at = AppTest.from_file(APP_PATH, default_timeout=10).run()
        at.selectbox(key="ui_schema_choice").select("Paste JSON Schema").run()
        at.text_area(key="ui_pasted_schema").set_value("{not valid json").run()
        self.assertFalse(at.exception)
        self.assertTrue(at.warning)

    def test_paste_valid_schema_builds_a_model(self):
        at = AppTest.from_file(APP_PATH, default_timeout=10).run()
        at.selectbox(key="ui_schema_choice").select("Paste JSON Schema").run()
        schema_json = '{"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}'
        at.text_area(key="ui_pasted_schema").set_value(schema_json).run()
        self.assertFalse(at.exception)
        self.assertFalse(at.warning)
        self.assertGreaterEqual(len(at.json), 1)


class RunTabErrorHandlingTests(unittest.TestCase):
    def test_missing_api_key_shows_clean_error_not_a_crash(self):
        with without_env("AGNES_API_KEY"):
            at = AppTest.from_file(APP_PATH, default_timeout=10).run()
            at.selectbox(key="ui_provider").select("agnes").run()
            at.selectbox(key="ui_schema_choice").select("contact_record").run()
            at.text_area(key="ui_text_input").set_value("Ada Lovelace, ada@example.com").run()
            at.button(key="ui_run_button").click().run()

        self.assertFalse(at.exception)  # never a raw traceback
        self.assertTrue(at.error)
        self.assertIn("missing_api_key", at.error[0].value)

    def test_empty_input_warns_instead_of_running(self):
        at = AppTest.from_file(APP_PATH, default_timeout=10).run()
        at.selectbox(key="ui_schema_choice").select("contact_record").run()
        at.button(key="ui_run_button").click().run()
        self.assertFalse(at.exception)
        self.assertTrue(at.warning)


class EvalTabTests(unittest.TestCase):
    def test_case_count_shown_without_running(self):
        at = AppTest.from_file(APP_PATH, default_timeout=10).run()
        self.assertFalse(at.exception)
        captions = " ".join(c.value for c in at.caption)
        self.assertIn("cases across", captions)


if __name__ == "__main__":
    unittest.main()
