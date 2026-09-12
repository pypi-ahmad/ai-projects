"""calc arithmetic-only sandbox; read_note path-traversal rejection."""

import pytest

from tools.builtins import CalcArgs, ReadNoteArgs, calc, read_note


def test_calc_basic_arithmetic():
    assert calc(CalcArgs(expression="2+2")).value == 4.0


def test_calc_rejects_names():
    with pytest.raises(ValueError, match="names are not allowed"):
        calc(CalcArgs(expression="__import__"))


def test_read_note_rejects_path_traversal():
    with pytest.raises(ValueError, match="path traversal rejected"):
        read_note(ReadNoteArgs(name="../x"), run_id="test-run")
