"""Name -> schema lookup. Not a decorator/plugin system — schemas are plain
pydantic.BaseModel classes registered explicitly (see the four built-ins in
this package for the pattern)."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel


@dataclass(frozen=True)
class RegisteredSchema:
    name: str
    model: type[BaseModel]
    example: BaseModel


class SchemaRegistry:
    def __init__(self) -> None:
        self._schemas: dict[str, RegisteredSchema] = {}

    def register(self, name: str, model: type[BaseModel], example: BaseModel) -> None:
        if not isinstance(example, model):
            raise TypeError(f"example for {name!r} must be an instance of {model.__name__}")
        self._schemas[name] = RegisteredSchema(name=name, model=model, example=example)

    def names(self) -> list[str]:
        return sorted(self._schemas)

    def get(self, name: str) -> type[BaseModel]:
        return self._schemas[name].model

    def json_schema(self, name: str) -> dict:
        return self.get(name).model_json_schema()

    def example(self, name: str) -> BaseModel:
        return self._schemas[name].example
