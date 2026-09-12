"""Windows-only test (skipped elsewhere) for run.cmd's
install-only-when-requirements-change behavior. Fakes `uv`/`netstat` as
throwaway batch scripts under a temp cwd rather than touching a real venv,
and asserts exact call counts for each launch.

Next: run.cmd itself (not a Python module).
"""

from pathlib import Path
import os
import subprocess

import pytest


@pytest.mark.skipif(os.name != "nt", reason="Windows launcher")
def test_launcher_installs_only_when_requirements_change(tmp_path):
    launcher = Path(__file__).parents[1] / "run.cmd"
    (tmp_path / "run.cmd").write_bytes(launcher.read_bytes())
    (tmp_path / "requirements.txt").write_text("example==1\n")
    (tmp_path / "uv.cmd").write_text(
        '@echo off\n'
        'echo %*>>calls.txt\n'
        'if "%1"=="venv" (\n'
        'mkdir .venv\\Scripts\n'
        'type nul > .venv\\Scripts\\python.exe\n'
        ')\n'
        'if "%1"=="pip" if exist fail-install exit /b 1\n'
        'exit /b 0\n'
    )
    (tmp_path / "netstat.cmd").write_text("@echo off\nexit /b 0\n")

    def launch():
        return subprocess.run(
            ["cmd.exe", "/d", "/c", "run.cmd"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )

    assert launch().returncode == 0
    assert launch().returncode == 0
    calls = (tmp_path / "calls.txt").read_text().splitlines()
    assert sum(line.startswith("pip ") for line in calls) == 1
    assert sum(line.startswith("run ") for line in calls) == 2

    (tmp_path / "requirements.txt").write_text("example==2\n")
    (tmp_path / "fail-install").touch()
    assert launch().returncode != 0
    assert (tmp_path / ".venv/requirements-installed.txt").read_text() == "example==1\n"
    assert sum(line.startswith("run ") for line in (tmp_path / "calls.txt").read_text().splitlines()) == 2

    (tmp_path / "fail-install").unlink()
    assert launch().returncode == 0
    assert launch().returncode == 0
    calls = (tmp_path / "calls.txt").read_text().splitlines()
    assert sum(line.startswith("pip ") for line in calls) == 3
    assert sum(line.startswith("run ") for line in calls) == 4
