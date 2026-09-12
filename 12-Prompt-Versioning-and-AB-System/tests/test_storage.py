from pathlib import Path

import pytest

from promptreg.registry.models import PromptConfig
from promptreg.registry.storage import IntegrityError, Registry

CONFIG = PromptConfig(model="qwen3.5:0.8b", provider="ollama", temperature=0.2)


def _registry(tmp_path: Path) -> Registry:
    return Registry(tmp_path / "registry.db", tmp_path / "prompts")


def test_publish_twice_creates_two_versions(tmp_path: Path) -> None:
    reg = _registry(tmp_path)

    v1 = reg.publish("greeting", "Hello, {name}!", CONFIG, "initial", "ada")
    v2 = reg.publish("greeting", "Hi there, {name}!", CONFIG, "friendlier tone", "ada")

    assert v1.version == 1
    assert v2.version == 2
    assert v1.sha256 != v2.sha256
    assert v1.immutable is True
    assert [v.version for v in reg.list_versions("greeting")] == [1, 2]
    assert reg.get("greeting", 1).body == "Hello, {name}!"


def test_list_prompts(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    reg.publish("greeting", "hi", CONFIG, "initial", "ada")
    reg.publish("farewell", "bye", CONFIG, "initial", "ada")

    assert reg.list_prompts() == ["farewell", "greeting"]


def test_mutated_body_fails_integrity_check(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    v1 = reg.publish("greeting", "Hello, {name}!", CONFIG, "initial", "ada")

    Path(v1.body_path).write_text("tampered", encoding="utf-8")

    with pytest.raises(IntegrityError):
        reg.get("greeting", 1)


def test_rollback_moves_pointer_not_bodies(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    v1 = reg.publish("greeting", "Hello, {name}!", CONFIG, "initial", "ada")
    v2 = reg.publish("greeting", "Hi there, {name}!", CONFIG, "friendlier tone", "ada")

    reg.set_pointer("greeting", "prod", v1.version)
    reg.set_pointer("greeting", "prod", v2.version)
    assert reg.get_pointer("greeting", "prod").version == 2

    rolled = reg.rollback("greeting", "prod")
    assert rolled.version == 1
    assert reg.get_pointer("greeting", "prod").version == 1

    # bodies untouched by rollback
    assert reg.get("greeting", 1).body == "Hello, {name}!"
    assert reg.get("greeting", 2).body == "Hi there, {name}!"


def test_rollback_without_history_raises(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    v1 = reg.publish("greeting", "Hello, {name}!", CONFIG, "initial", "ada")
    reg.set_pointer("greeting", "staging", v1.version)

    with pytest.raises(ValueError, match="no previous pointer"):
        reg.rollback("greeting", "staging")
