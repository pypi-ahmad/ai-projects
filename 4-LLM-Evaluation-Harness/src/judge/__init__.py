"""LLM-as-judge scoring. Start at pipeline.py (judge_case) for the end-to-end
flow: prompt.py builds the prompt, parsing.py + repair.py turn the raw response
into a validated JudgeVerdict, and models.py defines both that schema and the
JudgeRecord written to judge_scores.jsonl.
"""

from src.judge.models import JudgeRecord, JudgeVerdict
from src.judge.pipeline import judge_case
from src.judge.rubric import Rubric, load_rubric

__all__ = ["JudgeRecord", "JudgeVerdict", "Rubric", "judge_case", "load_rubric"]
