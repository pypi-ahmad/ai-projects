import pytest

from src.judge.rubric import Rubric, load_rubric


def _write_rubric(path, **overrides):
    data = {
        "id": "test_rubric",
        "version": 1,
        "dimensions": [
            {"name": "correctness", "description": "Is it correct?", "weight": 0.5},
            {"name": "completeness", "description": "Is it complete?", "weight": 0.5},
        ],
    }
    data.update(overrides)
    import yaml

    path.write_text(yaml.dump(data), encoding="utf-8")


def test_load_rubric_valid(tmp_path):
    _write_rubric(tmp_path / "test_rubric.yaml")

    rubric = load_rubric(tmp_path, "test_rubric")

    assert rubric.id == "test_rubric"
    assert len(rubric.dimensions) == 2


def test_rubric_rejects_weights_not_summing_to_one():
    with pytest.raises(ValueError, match="sum to"):
        Rubric.model_validate(
            {
                "id": "bad",
                "version": 1,
                "dimensions": [
                    {"name": "a", "description": "x", "weight": 0.5},
                    {"name": "b", "description": "y", "weight": 0.2},
                ],
            }
        )


def test_load_rubric_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_rubric(tmp_path, "does_not_exist")


def test_default_answer_quality_rubric_loads():
    from pathlib import Path

    rubric = load_rubric(Path("rubrics"), "answer_quality")

    assert rubric.id == "answer_quality"
    names = {d.name for d in rubric.dimensions}
    assert names == {
        "correctness",
        "completeness",
        "groundedness_if_context",
        "instruction_following",
    }
