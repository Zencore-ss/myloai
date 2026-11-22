import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from myloai.core.config import AppConfig, McpServerConfig
from myloai.core.mcp import McpClient, McpManager
from myloai.core.tools import ToolRegistry

FAKE_MCP_SERVER = """
import json
import sys

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    req = json.loads(line)
    if "id" not in req:
        continue
    method = req.get("method")
    if method == "initialize":
        result = {"protocolVersion": req["params"]["protocolVersion"], "capabilities": {}, "serverInfo": {"name": "fake", "version": "0.0.1"}}
    elif method == "tools/list":
        result = {"tools": [{"name": "echo", "description": "Echo text", "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}}}]}
    elif method == "tools/call":
        result = {"content": [{"type": "text", "text": "echo: " + req["params"]["arguments"].get("text", "")}], "isError": False}
    else:
        result = {}
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": result}) + "\\n")
    sys.stdout.flush()
"""


@pytest.fixture()
def fake_server(tmp_path: Path) -> McpServerConfig:
    script = tmp_path / "fake_mcp_server.py"
    script.write_text(FAKE_MCP_SERVER, encoding="utf-8")
    return McpServerConfig(
        name="fake",
        command=sys.executable,
        args=[str(script)],
        enabled=True,
    )


def test_mcp_client_initialize_list_and_call(fake_server):
    async def run():
        client = McpClient(fake_server)
        await client.start()
        assert client.connected
        tools = await client.list_tools()
        assert [t.name for t in tools] == ["echo"]
        assert tools[0].input_schema["properties"]["text"]["type"] == "string"
        result = await client.call_tool("echo", {"text": "hello"})
        assert result == "echo: hello"
        await client.stop()
        assert not client.connected

    asyncio.run(run())


def test_mcp_client_missing_command_raises(tmp_path):
    server = McpServerConfig(name="nope", command="/nonexistent/binary-xyz")
    from myloai.core.mcp import McpError

    with pytest.raises(McpError):
        asyncio.run(McpClient(server).start())


class FakeConfig:
    def __init__(self, servers):
        self.mcp_servers = servers
        self.paths = SimpleNamespace(plugins_dir=Path("/nonexistent"))
        self.developer_mode = False
        self.enabled_plugins = {}
        self.trusted_plugins = []

    def save(self) -> None:
        pass


def test_mcp_manager_start_enabled_isolates_failures(fake_server, tmp_path):
    bad = McpServerConfig(name="bad", command="/nonexistent/binary-xyz")
    manager = McpManager(FakeConfig([fake_server, bad]))

    async def run():
        results = await manager.start_enabled()
        assert [t.name for t in results["fake"]] == ["echo"]
        assert isinstance(results["bad"], str) and "error" in results["bad"]
        output = await manager.call_tool("fake", "echo", {"text": "yo"})
        assert output == "echo: yo"
        await manager.stop_all()
        assert manager.clients == {}

    asyncio.run(run())


def test_tool_registry_register_call_and_cleanup():
    registry = ToolRegistry()
    registry.register("upper", "Uppercase", {"type": "object", "properties": {"text": {"type": "string"}}}, lambda text: str(text).upper(), source="plugin")
    registry.register("fake__echo", "MCP echo", {"type": "object"}, lambda text="": f"echo:{text}", source="mcp")

    assert registry.names() == ["fake__echo", "upper"]
    specs = registry.specs()
    assert specs[0]["function"]["name"] in {"fake__echo", "upper"}

    async def run():
        assert await registry.call("upper", {"text": "abc"}) == "ABC"
        with pytest.raises(KeyError):
            await registry.call("missing", {})

    asyncio.run(run())
    registry.unregister_source("mcp")
    assert registry.names() == ["upper"]


def test_config_schema_v2_migrates_to_v3_with_mcp_servers():
    data, migrated = AppConfig._migrate_data({"schema_version": 2, "active_provider": "x"})
    assert migrated is True
    assert data["schema_version"] == 3
    assert data["mcp_servers"] == []
