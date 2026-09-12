from pathlib import Path

from promptreg.execute.completer import execute
from promptreg.registry.models import PromptConfig
from promptreg.registry.storage import Registry

CONFIG = PromptConfig(model="stub", provider="stub")


def test_execute_is_dry_when_no_completer_registered(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "registry.db", tmp_path / "prompts")
    v1 = registry.publish("greeting", "Hello, {name}!", CONFIG, "v1", "ada")

    result = execute(v1.body, v1.config)

    assert result.dry is True
    assert result.ok is True
    assert result.output is None
    assert result.body == "Hello, {name}!"
    assert result.config == CONFIG
    assert result.latency_ms == 0.0
