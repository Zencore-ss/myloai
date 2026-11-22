from __future__ import annotations

import asyncio
import json
import os
import shutil
from dataclasses import dataclass, field
from typing import Any

from myloai.core.config import AppConfig, McpServerConfig

MCP_PROTOCOL_VERSION = "2024-11-05"
CLIENT_INFO = {"name": "MyLoAI Control Center", "version": "2.2.0"}


class McpError(RuntimeError):
    pass


@dataclass(slots=True)
class McpTool:
    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})


class McpClient:
    """Minimal MCP stdio client: initialize, tools/list, tools/call over newline-delimited JSON-RPC."""

    def __init__(self, server: McpServerConfig, request_timeout: float = 30.0) -> None:
        self.server = server
        self.request_timeout = request_timeout
        self._process: asyncio.subprocess.Process | None = None
        self._reader: asyncio.StreamReader | None = None
        self._next_id = 0
        self._pending: dict[int, asyncio.Future] = {}

    @property
    def connected(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def start(self) -> None:
        if not self.server.command:
            raise McpError(f"MCP server '{self.server.name}' has no command configured")
        if shutil.which(self.server.command) is None and not os.path.exists(self.server.command):
            raise McpError(f"MCP server command not found: {self.server.command}")
        env = dict(os.environ)
        env.update(self.server.env)
        self._process = await asyncio.create_subprocess_exec(
            self.server.command,
            *self.server.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        self._reader = self._process.stdout
        await self._request(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": CLIENT_INFO,
            },
        )
        await self._notify("notifications/initialized")

    async def stop(self) -> None:
        process = self._process
        self._process = None
        self._reader = None
        for future in self._pending.values():
            if not future.done():
                future.set_exception(McpError("MCP client stopped"))
        self._pending.clear()
        if process is not None and process.returncode is None:
            try:
                process.terminate()
                await asyncio.wait_for(process.wait(), timeout=5)
            except (TimeoutError, ProcessLookupError):
                process.kill()

    async def list_tools(self) -> list[McpTool]:
        result = await self._request("tools/list", {})
        tools = []
        for item in result.get("tools", []):
            tools.append(
                McpTool(
                    name=str(item.get("name", "")),
                    description=str(item.get("description", "")),
                    input_schema=item.get("inputSchema") or {"type": "object", "properties": {}},
                )
            )
        return [tool for tool in tools if tool.name]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        result = await self._request(
            "tools/call", {"name": name, "arguments": arguments or {}}
        )
        if result.get("isError"):
            message = "; ".join(
                str(part.get("text", "")) for part in result.get("content", []) if part.get("text")
            )
            raise McpError(f"MCP tool '{name}' returned an error: {message or 'unknown error'}")
        parts = [
            str(part.get("text", ""))
            for part in result.get("content", [])
            if part.get("type") == "text"
        ]
        return "\n".join(parts)

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._process is None or self._reader is None or not self.connected:
            raise McpError(f"MCP server '{self.server.name}' is not connected")
        self._next_id += 1
        request_id = self._next_id
        message = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            self._process.stdin.write((json.dumps(message) + "\n").encode())
            await self._process.stdin.drain()
            while True:
                line = await asyncio.wait_for(self._reader.readline(), timeout=self.request_timeout)
                if not line:
                    raise McpError(f"MCP server '{self.server.name}' closed the connection")
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if data.get("id") == request_id:
                    if "error" in data:
                        raise McpError(str(data["error"].get("message", "MCP error")))
                    return data.get("result", {})
                # responses to other ids and notifications are handled by their own waiters
        finally:
            self._pending.pop(request_id, None)

    async def _notify(self, method: str) -> None:
        if self._process is None or self._process.stdin is None:
            raise McpError(f"MCP server '{self.server.name}' is not connected")
        message = {"jsonrpc": "2.0", "method": method}
        self._process.stdin.write((json.dumps(message) + "\n").encode())
        await self._process.stdin.drain()


class McpManager:
    """Owns the configured MCP server processes and aggregates their tools."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.clients: dict[str, McpClient] = {}

    def server_config(self, name: str) -> McpServerConfig | None:
        return next((s for s in self.config.mcp_servers if s.name == name), None)

    async def start_server(self, name: str) -> list[McpTool]:
        server = self.server_config(name)
        if server is None:
            raise McpError(f"Unknown MCP server '{name}'")
        await self.stop_server(name)
        client = McpClient(server)
        await client.start()
        self.clients[name] = client
        return await client.list_tools()

    async def stop_server(self, name: str) -> None:
        client = self.clients.pop(name, None)
        if client is not None:
            await client.stop()

    async def start_enabled(self) -> dict[str, Any]:
        """Start every enabled server; failures are isolated per server."""
        results: dict[str, Any] = {}
        for server in self.config.mcp_servers:
            if not server.enabled:
                continue
            try:
                results[server.name] = await self.start_server(server.name)
            except (TimeoutError, McpError, OSError) as exc:
                results[server.name] = f"error: {exc}"
        return results

    async def stop_all(self) -> None:
        for name in list(self.clients):
            await self.stop_server(name)

    async def list_tools(self) -> dict[str, list[McpTool]]:
        tools: dict[str, list[McpTool]] = {}
        for name, client in list(self.clients.items()):
            try:
                tools[name] = await client.list_tools()
            except (TimeoutError, McpError) as exc:
                tools[name] = []
                await self.stop_server(name)
                raise McpError(f"Lost connection to MCP server '{name}': {exc}") from exc
        return tools

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict[str, Any]) -> str:
        client = self.clients.get(server_name)
        if client is None:
            await self.start_server(server_name)
            client = self.clients[server_name]
        try:
            return await client.call_tool(tool_name, arguments)
        except (TimeoutError, McpError) as exc:
            await self.stop_server(server_name)
            raise McpError(f"MCP call failed on '{server_name}': {exc}") from exc
