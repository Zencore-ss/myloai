from pathlib import Path
from types import SimpleNamespace

import pytest

from myloai.core.managers import PluginContext, PluginManager


class FakeConfig:
    def __init__(self, plugins_dir: Path) -> None:
        self.paths = SimpleNamespace(plugins_dir=plugins_dir)
        self.developer_mode = False
        self.enabled_plugins = {}
        self.trusted_plugins = []
        self.saves = 0

    def save(self) -> None:
        self.saves += 1


def make_plugin(path: Path) -> None:
    path.write_text(
        """
ACTIVATED = []
DEACTIVATED = []

class Plugin:
    manifest = {"id": "demo", "name": "Demo Plugin", "version": "1.0.0"}

    def activate(self, context):
        ACTIVATED.append("activate")

    def deactivate(self):
        DEACTIVATED.append("deactivate")
""",
        encoding="utf-8",
    )


def test_plugin_lifecycle_discover_validate_trust_enable_disable_reload_untrust_remove(tmp_path):
    plugin_path = tmp_path / "demo.py"
    make_plugin(plugin_path)
    config = FakeConfig(tmp_path)
    manager = PluginManager(config, PluginContext(SimpleNamespace(), config))

    discovered = manager.discover()
    assert discovered[0]["id"] == "demo"
    assert discovered[0]["version"] == "1.0.0"
    assert "error" not in discovered[0]

    with pytest.raises(PermissionError):
        manager.enable(plugin_path)

    manager.trust("demo")
    assert "demo" in config.trusted_plugins

    manager.enable(plugin_path)
    assert "demo" in manager.loaded
    assert config.enabled_plugins["demo"] is True

    manager.disable("demo")
    assert "demo" not in manager.loaded
    assert config.enabled_plugins["demo"] is False

    manager.enable(plugin_path)
    manager.reload()
    assert "demo" in manager.loaded
    assert config.enabled_plugins["demo"] is True

    manager.untrust("demo")
    assert "demo" not in manager.loaded
    assert "demo" not in config.trusted_plugins
    assert config.enabled_plugins["demo"] is False

    manager.trust("demo")
    manager.enable(plugin_path)
    manager.remove("demo")
    assert not plugin_path.exists()
    assert "demo" not in manager.loaded
    assert "demo" not in config.trusted_plugins
    assert "demo" not in config.enabled_plugins


def test_plugin_discovery_reports_manifest_validation_error(tmp_path):
    path = tmp_path / "invalid.py"
    path.write_text(
        "class Plugin:\n    manifest = {'id': 'invalid'}\n",
        encoding="utf-8",
    )
    config = FakeConfig(tmp_path)
    manager = PluginManager(config, PluginContext(SimpleNamespace(), config))

    result = manager.discover()[0]
    assert result["id"] == "invalid"
    assert "error" in result

    with pytest.raises(ValueError):
        manager.trust("invalid")


def make_registering_plugin(path: Path) -> None:
    path.write_text(
        """
class Plugin:
    manifest = {"id": "reg", "name": "Registering Plugin", "version": "1.0.0"}

    def activate(self, context):
        context.register_tool("t", lambda: 1)
        context.register_command("c", lambda: None)
        context.register_chat_interceptor(lambda messages: messages)
        context.register_memory_provider("m", lambda: "memory")

    def deactivate(self):
        pass
""",
        encoding="utf-8",
    )


def test_plugin_registrations_are_removed_on_disable(tmp_path):
    plugin_path = tmp_path / "reg.py"
    make_registering_plugin(plugin_path)
    config = FakeConfig(tmp_path)
    context = PluginContext(SimpleNamespace(), config)
    manager = PluginManager(config, context)

    manager.trust("reg")
    manager.enable(plugin_path)
    assert context.tools.get("t") is not None
    assert context.commands.get("c") is not None
    assert len(context.chat_interceptors) == 1
    assert context.memory_providers.get("m") is not None

    manager.disable("reg")
    assert "t" not in context.tools
    assert "c" not in context.commands
    assert context.chat_interceptors == []
    assert "m" not in context.memory_providers


def test_plugin_failed_activation_cleans_up_partial_registrations(tmp_path):
    plugin_path = tmp_path / "boom.py"
    plugin_path.write_text(
        """
class Plugin:
    manifest = {"id": "boom", "name": "Boom", "version": "1.0.0"}

    def activate(self, context):
        context.register_tool("leaked", lambda: 1)
        raise RuntimeError("activation failed")

    def deactivate(self):
        pass
""",
        encoding="utf-8",
    )
    config = FakeConfig(tmp_path)
    context = PluginContext(SimpleNamespace(), config)
    manager = PluginManager(config, context)

    manager.trust("boom")
    with pytest.raises(RuntimeError):
        manager.enable(plugin_path)
    assert "leaked" not in context.tools
    assert "boom" not in manager.loaded


def test_install_validates_manifest_before_copying(tmp_path):
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    config = FakeConfig(plugins_dir)
    manager = PluginManager(config, PluginContext(SimpleNamespace(), config))

    valid = source_dir / "good.py"
    make_plugin(valid)
    dest = manager.install(valid)
    assert dest == plugins_dir / "good.py"
    assert dest.exists()

    invalid = source_dir / "bad.py"
    invalid.write_text("class Plugin:\n    manifest = {'id': 'bad'}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        manager.install(invalid)
    assert not (plugins_dir / "bad.py").exists()
