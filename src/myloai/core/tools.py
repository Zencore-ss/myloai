from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Any]
    source: str = "plugin"

    def to_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters or {"type": "object", "properties": {}},
            },
        }


class ToolRegistry:
    """Framework-agnostic registry of callable tools (plugin tools, MCP tools)."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: Callable[..., Any],
        source: str = "plugin",
    ) -> None:
        self._tools[name] = ToolSpec(name, description, parameters, handler, source)

    def unregister_source(self, source: str) -> None:
        for name in [n for n, spec in self._tools.items() if spec.source == source]:
            del self._tools[name]

    def names(self) -> list[str]:
        return sorted(self._tools)

    def specs(self) -> list[dict[str, Any]]:
        return [spec.to_openai_tool() for spec in self._tools.values()]

    def has(self, name: str) -> bool:
        return name in self._tools

    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        spec = self._tools.get(name)
        if spec is None:
            raise KeyError(f"Unknown tool '{name}'")
        result = spec.handler(**(arguments or {}))
        if inspect.isawaitable(result):
            result = await result
        return result if isinstance(result, str) else str(result)
