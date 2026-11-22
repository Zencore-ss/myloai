from __future__ import annotations

from pathlib import Path
from typing import Protocol

from PySide6.QtWidgets import QFileDialog, QMessageBox


class PluginWindowPort(Protocol):
    def log(self, text: str) -> None: ...


class PluginController:
    def __init__(self, plugins, config, window: PluginWindowPort) -> None:
        self.plugins = plugins
        self.config = config
        self.window = window

    def reload_plugins(self) -> None:
        self.plugins.reload()
        self.window.log("Plugins reloaded")

    def install_plugin(self, parent) -> None:
        path, _ = QFileDialog.getOpenFileName(parent, "Install Plugin", filter="Python (*.py)")
        if not path:
            return
        try:
            dest = self.plugins.install(Path(path))
        except (OSError, ValueError) as error:
            self.window.log(f"Plugin install rejected: {error}")
            QMessageBox.critical(parent, "Install Plugin", f"Plugin was not installed:\n{error}")
            return
        self.window.log(f"Installed plugin {dest}")
