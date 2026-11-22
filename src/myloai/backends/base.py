from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

from myloai.core.domain import ChatMessage, ModelInfo


@dataclass(slots=True)
class BackendStatus:
    state: str
    latency_ms: float = 0.0
    detail: str = ""




VALID_CHAT_ROLES = {"system", "user", "assistant", "tool"}


def serialize_chat_messages(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    """Serialize chat messages for a backend payload, including tool-call metadata."""
    serialized: list[dict[str, Any]] = []
    for message in messages:
        item: dict[str, Any] = {
            "role": str(message.role).strip().lower(),
            "content": message.content if isinstance(message.content, str) else str(message.content),
        }
        tool_calls = message.metadata.get("tool_calls")
        if tool_calls:
            item["tool_calls"] = tool_calls
        if item["role"] == "tool":
            item["tool_call_id"] = message.metadata.get("tool_call_id", "")
            if message.name:
                item["name"] = message.name
        serialized.append(item)
    return serialized


def build_chat_messages(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    """Validate and serialize chat messages before sending them to a backend."""
    serialized: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        role = str(message.role).strip().lower()
        content = message.content if isinstance(message.content, str) else str(message.content)
        if role not in VALID_CHAT_ROLES:
            raise ValueError(f"Invalid chat message role at index {index}: {role!r}")
        if not content.strip() and not message.metadata.get("tool_calls"):
            continue
        serialized.append({"role": role, "content": content})
    if not serialized:
        raise ValueError("Chat request contains no non-empty messages.")
    return serialized


def normalize_tool_calls(raw_tool_calls: Any) -> list[dict[str, Any]]:
    """Normalize provider-specific tool_calls into {id, name, arguments} dicts."""
    normalized: list[dict[str, Any]] = []
    for index, call in enumerate(raw_tool_calls or []):
        function = call.get("function", {}) if isinstance(call, dict) else {}
        arguments = function.get("arguments", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments) if arguments.strip() else {}
            except json.JSONDecodeError:
                arguments = {"_raw": arguments}
        normalized.append(
            {
                "id": str(call.get("id", f"call_{index}")) if isinstance(call, dict) else f"call_{index}",
                "name": str(function.get("name", "")) if isinstance(call, dict) else "",
                "arguments": arguments if isinstance(arguments, dict) else {},
            }
        )
    return [call for call in normalized if call["name"]]


def raise_for_chat_response(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = response.text.strip()
        if len(detail) > 1000:
            detail = detail[:1000] + "…"
        raise RuntimeError(
            f"Chat request failed with HTTP {response.status_code}: {detail or response.reason_phrase}"
        ) from exc


class LLMBackend(ABC):
    name: str

    def __init__(self, base_url: str, api_key: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    @abstractmethod
    async def test_connection(self) -> BackendStatus: ...

    @abstractmethod
    async def list_models(self) -> list[ModelInfo]: ...

    @abstractmethod
    async def chat(
        self,
        model: str,
        messages: list[ChatMessage],
        options: dict[str, Any],
        stream: bool,
    ) -> AsyncIterator[str]: ...

    async def chat_collect(
        self,
        model: str,
        messages: list[ChatMessage],
        options: dict[str, Any],
    ) -> dict[str, Any]:
        """Non-streaming chat that also surfaces tool_calls. Returns {content, tool_calls}."""
        text = ""
        async for chunk in self.chat(model, messages, options, stream=False):
            text += chunk
        return {"content": text, "tool_calls": []}

    async def pull_model(self, name: str) -> AsyncIterator[str]:
        raise NotImplementedError("Model pull is not supported by this backend")

    async def push_model(self, name: str) -> AsyncIterator[str]:
        raise NotImplementedError("Model push is not supported by this backend")

    async def delete_model(self, name: str) -> None:
        raise NotImplementedError("Model deletion is not supported by this backend")

    async def copy_model(self, source: str, destination: str) -> None:
        raise NotImplementedError("Model copy is not supported by this backend")

    async def create_model(self, name: str, modelfile: str) -> AsyncIterator[str]:
        raise NotImplementedError("Model creation is not supported by this backend")

    async def show_model(self, name: str) -> dict[str, Any]:
        raise NotImplementedError("Model metadata is not supported by this backend")
