"""Loads data/eval/qa.jsonl-style cases, runs each through agent.loop.run_safe(), and
scores 3 pure metrics (metrics.py) from the results. Must not change agent/ behavior --
it only observes AgentResult/AgentTrace. Start reading at eval/pipeline.py.
"""
