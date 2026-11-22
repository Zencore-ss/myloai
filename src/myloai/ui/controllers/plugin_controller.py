from __future__ import annotations

from pathlib import Path
from typing import Protocol


class PluginWindowPort(Protocol):
    def log(self, text: str) -> None: ...
    def ask_open_file(self, title: str, name_filter: str) -> str: ...
    def show_error(self, title: str, text: str) -> None: ...


class PluginController:
    def __init__(self, plugins, config, window: PluginWindowPort) -> None:
        self.plugins = plugins
        self.config = config
        self.window = window

    def reload_plugins(self) -> None:
        self.plugins.reload()
        self.window.log("Plugins reloaded")

    def install_plugin(self, parent) -> None:
        path = self.window.ask_open_file("Install Plugin", "Python (*.py)")
        if not path:
            return
        try:
            dest = self.plugins.install(Path(path))
        except (OSError, ValueError) as error:
            self.window.log(f"Plugin install rejected: {error}")
            self.window.show_error("Install Plugin", f"Plugin was not installed:\n{error}")
            return
        self.window.log(f"Installed plugin {dest}")
