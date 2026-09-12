"""Tool registration and discovery.

Next: builtins.py, for the five tools actually registered into one of
these, or parse.py, for how a model's tool-name string gets looked up
here.
"""

from __future__ import annotations

from .schema import ToolSpec


class Registry:
    """Holds registered ToolSpecs by unique name.

    Not thread-safe against concurrent register() calls, and nothing
    needs it to be: every call site in this repo populates one Registry
    once, at process/test start, before any lookups happen.
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            msg = f"tool already registered: {spec.name!r}"
            raise ValueError(msg)
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError:
            msg = f"no such tool: {name!r}"
            raise KeyError(msg) from None

    def list(self) -> list[dict]:
        """OpenAI Chat Completions `tools` shape: [{"type": "function", "function": {...}}].

        Verified against openai-python v2.11.0 (ChatCompletionFunctionToolParam):
        the Chat Completions API nests name/description/parameters under
        `function`. The newer Responses API instead puts them top-level
        (FunctionToolParam) -- a Responses-API adapter must flatten this shape.
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.args_model.model_json_schema(),
                },
            }
            for spec in self._tools.values()
        ]

    def list_schemas(self) -> list[dict]:
        """Generic, provider-agnostic view: [{"name", "description", "parameters"}]."""
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.args_model.model_json_schema(),
            }
            for spec in self._tools.values()
        ]
