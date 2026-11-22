from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from myloai.core.config import AppConfig, McpServerConfig, ProviderProfile
from myloai.core.domain import AgentProfile, PromptRecord, SkillRecord
from myloai.core.managers import AgentManager, PluginManager, PromptManager, SkillManager
from myloai.core.mcp import McpManager


class ModelfileHighlighter(QSyntaxHighlighter):
    def highlightBlock(self, text: str) -> None:
        keyword = QTextCharFormat()
        keyword.setForeground(QColor("#88c0d0"))
        keyword.setFontWeight(700)
        for word in ("FROM", "PARAMETER", "TEMPLATE", "SYSTEM", "ADAPTER", "LICENSE", "MESSAGE"):
            idx = text.find(word)
            if idx >= 0:
                self.setFormat(idx, len(word), keyword)


class EndpointDialog(QDialog):
    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("API Endpoints")
        self.config = config
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Name", "Type", "Base URL", "API Key", "Enabled"])
        add = QPushButton("Add")
        remove = QPushButton("Remove")
        add.clicked.connect(self.add_row)
        remove.clicked.connect(lambda: self.table.removeRow(self.table.currentRow()))
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        row = QHBoxLayout()
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch()
        layout.addLayout(row)
        layout.addWidget(buttons)
        for profile in config.provider_profiles:
            self.add_row(profile)

    def add_row(self, profile: ProviderProfile | None = None) -> None:
        profile = profile or ProviderProfile(name="New Endpoint", provider_type="ollama")
        r = self.table.rowCount()
        self.table.insertRow(r)
        for c, value in enumerate(
            [
                profile.name,
                profile.provider_type,
                profile.base_url,
                profile.api_key,
                str(profile.enabled),
            ]
        ):
            self.table.setItem(r, c, QTableWidgetItem(value))

    def accept(self) -> None:
        profiles = []
        for r in range(self.table.rowCount()):
            profiles.append(
                ProviderProfile(
                    name=self.table.item(r, 0).text(),
                    provider_type=self.table.item(r, 1).text(),
                    base_url=self.table.item(r, 2).text(),
                    api_key=self.table.item(r, 3).text(),
                    enabled=self.table.item(r, 4).text().lower() == "true",
                )
            )
        if profiles:
            self.config.provider_profiles = profiles
            self.config.active_provider = profiles[0].name
            self.config.save()
        super().accept()


class ModelfileEditor(QDialog):
    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Modelfile Editor")
        self.resize(900, 700)
        self.config = config
        self.path: Path | None = None
        self.editor = QPlainTextEdit(
            "FROM llama3\nPARAMETER temperature 0.7\nSYSTEM You are helpful.\n"
        )
        ModelfileHighlighter(self.editor.document())
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.name = QLineEdit("custom-model")
        for button_text, handler in [
            ("New", self.new),
            ("Open", self.open_file),
            ("Save", self.save),
            ("Duplicate", self.duplicate),
            ("Validate", self.validate),
            ("Preview Config", self.update_preview),
            ("Build Model", self.build_model),
        ]:
            btn = QPushButton(button_text)
            btn.clicked.connect(handler)
            setattr(self, button_text.lower().replace(" ", "_"), btn)
        top = QHBoxLayout()
        for attr in (
            "new",
            "open",
            "save",
            "duplicate",
            "validate",
            "preview_config",
            "build_model",
        ):
            top.addWidget(getattr(self, attr))
        top.addWidget(QLabel("Model name:"))
        top.addWidget(self.name)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(QLabel("Modelfile"))
        layout.addWidget(self.editor, 2)
        layout.addWidget(QLabel("Preview"))
        layout.addWidget(self.preview, 1)

    def new(self) -> None:
        self.path = None
        self.editor.setPlainText(
            "FROM llama3\nPARAMETER temperature 0.7\nSYSTEM You are helpful.\n"
        )

    def open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Modelfile", str(self.config.paths.modelfiles_dir)
        )
        if path:
            self.path = Path(path)
            self.editor.setPlainText(self.path.read_text(encoding="utf-8"))

    def save(self) -> None:
        if not self.path:
            path, _ = QFileDialog.getSaveFileName(
                self, "Save Modelfile", str(self.config.paths.modelfiles_dir / "Modelfile")
            )
            if not path:
                return
            self.path = Path(path)
        self.path.write_text(self.editor.toPlainText(), encoding="utf-8")
        version_dir = self.config.paths.modelfiles_dir / ".versions" / self.path.stem
        version_dir.mkdir(parents=True, exist_ok=True)
        (version_dir / f"{len(list(version_dir.glob('*.Modelfile'))) + 1}.Modelfile").write_text(
            self.editor.toPlainText(), encoding="utf-8"
        )

    def duplicate(self) -> None:
        self.path = None
        self.name.setText(self.name.text() + "-copy")
        self.save()

    def validate(self) -> None:
        text = self.editor.toPlainText()
        errors = []
        if "FROM " not in text:
            errors.append("A Modelfile must include a FROM directive.")
        for line_no, line in enumerate(text.splitlines(), 1):
            if (
                line
                and not line.startswith("#")
                and line.split()[0]
                not in {"FROM", "PARAMETER", "TEMPLATE", "SYSTEM", "ADAPTER", "LICENSE", "MESSAGE"}
            ):
                errors.append(f"Line {line_no}: unsupported directive {line.split()[0]}")
        QMessageBox.information(
            self, "Validation", "Valid Modelfile" if not errors else "\n".join(errors)
        )

    def build_model(self) -> None:
        self.save()
        parent = self.parent()
        if hasattr(parent, "build_model_from_modelfile"):
            parent.build_model_from_modelfile(self.name.text(), self.editor.toPlainText())

    def update_preview(self) -> None:
        params = []
        system = []
        template = []
        for line in self.editor.toPlainText().splitlines():
            if line.startswith("PARAMETER "):
                params.append(line.removeprefix("PARAMETER "))
            elif line.startswith("SYSTEM "):
                system.append(line.removeprefix("SYSTEM "))
            elif line.startswith("TEMPLATE "):
                template.append(line.removeprefix("TEMPLATE "))
        self.preview.setPlainText(
            f"System Prompt:\n{' '.join(system)}\n\nParameters:\n"
            + "\n".join(params)
            + f"\n\nTemplate:\n{' '.join(template)}"
        )


class PromptManagerDialog(QDialog):
    def __init__(self, manager: PromptManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("System Prompt Manager")
        self.resize(800, 600)
        self.manager = manager
        self.listw = QListWidget()
        self.editor = QPlainTextEdit()
        self.title = QLineEdit()
        self.category = QLineEdit("General")
        self.favorite = QCheckBox("Favorite")
        self.listw.currentRowChanged.connect(self.load_selected)
        buttons = QHBoxLayout()
        for text, slot in [
            ("New", self.new),
            ("Save", self.save),
            ("Delete", self.delete),
            ("Import", self.import_prompt),
            ("Export", self.export_prompts),
        ]:
            b = QPushButton(text)
            b.clicked.connect(slot)
            buttons.addWidget(b)
        form = QFormLayout()
        form.addRow("Title", self.title)
        form.addRow("Category", self.category)
        form.addRow("", self.favorite)
        layout = QHBoxLayout(self)
        layout.addWidget(self.listw, 1)
        right = QVBoxLayout()
        right.addLayout(form)
        right.addWidget(self.editor)
        right.addLayout(buttons)
        layout.addLayout(right, 3)
        self.current_id = ""
        self.refresh()

    def refresh(self) -> None:
        self.prompts = self.manager.list()
        self.listw.clear()
        for p in self.prompts:
            self.listw.addItem(("★ " if p.favorite else "") + f"{p.category}: {p.title}")

    def load_selected(self, row: int) -> None:
        if row < 0 or row >= len(self.prompts):
            return
        p = self.prompts[row]
        self.current_id = p.id
        self.title.setText(p.title)
        self.category.setText(p.category)
        self.favorite.setChecked(p.favorite)
        self.editor.setPlainText(p.content)

    def new(self) -> None:
        self.current_id = ""
        self.title.setText("New Prompt")
        self.category.setText("General")
        self.favorite.setChecked(False)
        self.editor.clear()

    def save(self) -> None:
        p = PromptRecord(
            title=self.title.text(),
            content=self.editor.toPlainText(),
            category=self.category.text(),
            favorite=self.favorite.isChecked(),
            id=self.current_id or PromptRecord("", "").id,
        )
        self.manager.upsert(p)
        self.current_id = p.id
        self.refresh()

    def delete(self) -> None:
        if self.current_id:
            self.manager.delete(self.current_id)
            self.refresh()
            self.new()

    def import_prompt(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import Prompt")
        if path:
            self.manager.import_file(Path(path))
            self.refresh()

    def export_prompts(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export Prompts", "prompts.json")
        if path:
            self.manager.export(Path(path))


class AgentBuilderDialog(QDialog):
    def __init__(
        self,
        manager: AgentManager,
        models: list[str],
        plugins: list[str],
        prompts: list[PromptRecord],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Agent Builder")
        self.resize(720, 520)
        self.manager = manager
        self.current_id = ""
        self.agents = QListWidget()
        self.agents.currentRowChanged.connect(self.load_selected)
        self.name = QLineEdit("New Agent")
        self.model = QComboBox()
        self.model.addItems(models)
        self.system_prompt = QComboBox()
        self.system_prompt.addItem("(none)", "")
        for prompt in prompts:
            self.system_prompt.addItem(f"{prompt.category}: {prompt.title}", prompt.id)
        self.reasoning = QComboBox()
        self.reasoning.addItems(["normal", "thinking", "planner"])
        self.behavior = QComboBox()
        self.behavior.addItems(["constrained", "planner", "executor", "autonomous"])
        self.memory = QComboBox()
        self.memory.addItems(["none", "session", "persistent"])
        self.policy = QComboBox()
        self.policy.addItems(["confirm_tools", "auto_tools", "no_tools"])
        self.tools = QLineEdit()
        self.plugins = QLineEdit(",".join(plugins))
        form = QFormLayout()
        for label, widget in [
            ("Name", self.name),
            ("Model", self.model),
            ("System Prompt", self.system_prompt),
            ("Reasoning", self.reasoning),
            ("Behavior", self.behavior),
            ("Memory", self.memory),
            ("Execution Policy", self.policy),
            ("Tools CSV", self.tools),
            ("Plugins CSV", self.plugins),
        ]:
            form.addRow(label, widget)
        row = QHBoxLayout()
        for text, slot in [
            ("New", self.new),
            ("Save", self.save),
            ("Import", self.import_agent),
            ("Export", self.export_agent),
        ]:
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        layout = QHBoxLayout(self)
        layout.addWidget(self.agents, 1)
        right = QVBoxLayout()
        right.addLayout(form)
        right.addLayout(row)
        layout.addLayout(right, 2)
        self.refresh()

    def refresh(self) -> None:
        self.items = self.manager.list()
        self.agents.clear()
        [self.agents.addItem(a.name) for a in self.items]

    def load_selected(self, row: int) -> None:
        if row < 0 or row >= len(self.items):
            return
        a = self.items[row]
        self.current_id = a.id
        self.name.setText(a.name)
        self.model.setCurrentText(a.model)
        idx = self.system_prompt.findData(a.system_prompt_id)
        self.system_prompt.setCurrentIndex(max(idx, 0))
        self.reasoning.setCurrentText(a.reasoning_mode)
        self.behavior.setCurrentText(a.behavior)
        self.memory.setCurrentText(a.memory_mode)
        self.policy.setCurrentText(a.execution_policy)
        self.tools.setText(",".join(a.tools))
        self.plugins.setText(",".join(a.plugins))

    def new(self) -> None:
        self.current_id = ""
        self.name.setText("New Agent")

    def _agent(self) -> AgentProfile:
        return AgentProfile(
            name=self.name.text(),
            model=self.model.currentText(),
            system_prompt_id=self.system_prompt.currentData() or "",
            tools=[x.strip() for x in self.tools.text().split(",") if x.strip()],
            plugins=[x.strip() for x in self.plugins.text().split(",") if x.strip()],
            memory_mode=self.memory.currentText(),
            reasoning_mode=self.reasoning.currentText(),
            behavior=self.behavior.currentText(),
            execution_policy=self.policy.currentText(),
            id=self.current_id or AgentProfile("x").id,
        )

    def save(self) -> None:
        self.manager.upsert(self._agent())
        self.refresh()

    def import_agent(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import Agent", filter="JSON (*.json)")
        if path:
            self.manager.upsert(
                AgentProfile(**__import__("json").loads(Path(path).read_text(encoding="utf-8")))
            )
            self.refresh()

    def export_agent(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export Agent", "agent.json")
        if path:
            Path(path).write_text(
                __import__("json").dumps(asdict(self._agent()), indent=2), encoding="utf-8"
            )


class PluginManagerDialog(QDialog):
    def __init__(self, manager: PluginManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Plugin Manager")
        self.resize(760, 480)
        self.manager = manager
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Enabled", "Trusted", "ID", "Name", "Version", "Path/Error"])
        reload_btn = QPushButton("Reload Plugins")
        reload_btn.clicked.connect(self.reload_plugins)
        save_btn = QPushButton("Apply Enable/Trust")
        save_btn.clicked.connect(self.apply)
        uninstall_btn = QPushButton("Uninstall Selected")
        uninstall_btn.clicked.connect(self.uninstall_selected)
        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        row = QHBoxLayout()
        row.addWidget(save_btn)
        row.addWidget(reload_btn)
        row.addWidget(uninstall_btn)
        row.addStretch()
        layout.addLayout(row)
        self.refresh()

    def refresh(self) -> None:
        self.plugins = self.manager.discover()
        self.table.setRowCount(0)
        for p in self.plugins:
            r = self.table.rowCount()
            self.table.insertRow(r)
            enabled = QTableWidgetItem(
                "true"
                if self.manager.config.enabled_plugins.get(p.get("id", ""), False)
                else "false"
            )
            enabled.setFlags(enabled.flags() | Qt.ItemFlag.ItemIsEditable)
            trusted = QTableWidgetItem(
                "true" if p.get("id", "") in self.manager.config.trusted_plugins else "false"
            )
            trusted.setFlags(trusted.flags() | Qt.ItemFlag.ItemIsEditable)
            for c, val in enumerate(
                [
                    enabled,
                    trusted,
                    p.get("id", ""),
                    p.get("name", ""),
                    p.get("version", ""),
                    p.get("error") or p.get("path", ""),
                ]
            ):
                self.table.setItem(
                    r, c, val if isinstance(val, QTableWidgetItem) else QTableWidgetItem(str(val))
                )

    def apply(self) -> None:
        for r, p in enumerate(self.plugins):
            pid = p.get("id", "")
            if not pid or p.get("error"):
                continue
            enabled = self.table.item(r, 0).text().lower() in {"true", "1", "yes", "enabled"}
            trusted = self.table.item(r, 1).text().lower() in {"true", "1", "yes", "trusted"}
            try:
                if trusted and pid not in self.manager.config.trusted_plugins:
                    self.manager.trust(pid)
                if not trusted and pid in self.manager.config.trusted_plugins:
                    self.manager.untrust(pid)
                if enabled and pid not in self.manager.loaded:
                    self.manager.enable(Path(p["path"]))
                elif not enabled and pid in self.manager.loaded:
                    self.manager.disable(pid)
            except (PermissionError, ValueError, OSError) as error:
                QMessageBox.warning(self, "Plugin Manager", str(error))
        self.refresh()

    def uninstall_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.plugins):
            return
        pid = self.plugins[row].get("id", "")
        if not pid or self.plugins[row].get("error"):
            return
        answer = QMessageBox.question(
            self,
            "Uninstall Plugin",
            f"Uninstall plugin '{pid}'? This disables it, removes trust, and deletes the plugin file.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.manager.remove(pid)
        self.refresh()

    def reload_plugins(self) -> None:
        self.manager.reload()
        self.refresh()


class ParameterDialog(QDialog):
    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Generation Parameters")
        self.resize(520, 620)
        self.config = config
        p = config.parameters
        self.widgets: dict[str, QWidget] = {}
        form = QFormLayout()

        def spin(name: str, value: int, lo: int, hi: int) -> QSpinBox:
            w = QSpinBox()
            w.setRange(lo, hi)
            w.setValue(value)
            self.widgets[name] = w
            form.addRow(name, w)
            return w

        def dbl(name: str, value: float, lo: float, hi: float) -> QLineEdit:
            w = QLineEdit(str(value))
            self.widgets[name] = w
            form.addRow(name, w)
            return w

        dbl("temperature", p.temperature, 0, 5)
        spin("top_k", p.top_k, 0, 1000)
        dbl("top_p", p.top_p, 0, 1)
        dbl("min_p", p.min_p, 0, 1)
        dbl("repeat_penalty", p.repeat_penalty, 0, 5)
        spin("repeat_last_n", p.repeat_last_n, -1, 32768)
        spin("num_predict", p.num_predict, -2, 200000)
        spin("seed", p.seed, -1, 2_147_483_647)
        spin("num_ctx", p.num_ctx, 128, 1_000_000)
        spin("num_batch", p.num_batch, 1, 32768)
        spin("num_gpu", p.num_gpu, -1, 999)
        self.stop = QLineEdit("|".join(p.stop))
        form.addRow("stop (| separated)", self.stop)
        self.preset_name = QLineEdit("default")
        form.addRow("preset name", self.preset_name)
        self.reasoning_mode = QComboBox()
        self.reasoning_mode.addItems(["normal", "thinking"])
        self.reasoning_mode.setCurrentText(p.reasoning_mode)
        self.reasoning_mode.setToolTip(
            "Reasoning mode for the next request. "
            "'thinking' maps to the capability-gated Ollama request field think=true. "
            "'normal' is app-default mode (no mode field sent)."
        )
        form.addRow("reasoning mode", self.reasoning_mode)
        save_preset = QPushButton("Save Preset")
        save_preset.clicked.connect(self.save_preset)
        load_preset = QPushButton("Load Preset")
        load_preset.clicked.connect(self.load_preset)
        preset_row = QHBoxLayout()
        preset_row.addWidget(save_preset)
        preset_row.addWidget(load_preset)
        preset_row.addStretch()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(preset_row)
        layout.addWidget(buttons)

    def _collect(self) -> dict[str, object]:
        values = {}
        for name, widget in self.widgets.items():
            values[name] = widget.value() if isinstance(widget, QSpinBox) else float(widget.text())
        values["stop"] = [x for x in self.stop.text().split("|") if x]
        values["reasoning_mode"] = self.reasoning_mode.currentText()
        return values

    def save_preset(self) -> None:
        self.config.parameter_presets[self.preset_name.text() or "default"] = self._collect()
        self.config.save()
        QMessageBox.information(self, "Preset", "Parameter preset saved.")

    def load_preset(self) -> None:
        preset = self.config.parameter_presets.get(self.preset_name.text())
        if not preset:
            QMessageBox.warning(self, "Preset", "No preset found with that name.")
            return
        for name, value in preset.items():
            if name in self.widgets:
                widget = self.widgets[name]
                if isinstance(widget, QSpinBox):
                    widget.setValue(int(value))
                else:
                    widget.setText(str(value))
        self.stop.setText("|".join(preset.get("stop", [])))
        preset_mode = str(preset.get("reasoning_mode", "normal"))
        if preset_mode not in {"normal", "thinking"}:
            preset_mode = "thinking" if bool(preset.get("thinking_mode", False)) else "normal"
        self.reasoning_mode.setCurrentText(preset_mode)

    def accept(self) -> None:
        p = self.config.parameters
        for name, value in self._collect().items():
            setattr(p, name, value)
        self.config.save()
        super().accept()


class McpServersDialog(QDialog):
    """Manage MCP server processes: add/remove servers, toggle, test, inspect tools."""

    def __init__(self, config: AppConfig, mcp: McpManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("MCP Servers")
        self.resize(860, 520)
        self.config = config
        self.mcp = mcp
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Enabled", "Name", "Command", "Args", "Transport"])
        add = QPushButton("Add")
        remove = QPushButton("Remove Selected")
        test = QPushButton("Test Connection")
        tools_btn = QPushButton("List Tools")
        add.clicked.connect(self.add_row)
        remove.clicked.connect(lambda: self.table.removeRow(self.table.currentRow()))
        test.clicked.connect(self.test_selected)
        tools_btn.clicked.connect(self.list_tools_selected)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        row = QHBoxLayout()
        row.addWidget(add)
        row.addWidget(remove)
        row.addWidget(test)
        row.addWidget(tools_btn)
        row.addStretch()
        layout.addLayout(row)
        layout.addWidget(buttons)
        self.refresh()

    def refresh(self) -> None:
        self.table.setRowCount(0)
        for server in self.config.mcp_servers:
            self._insert_row(server)

    def _insert_row(self, server: McpServerConfig) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        enabled = QTableWidgetItem("true" if server.enabled else "false")
        enabled.setFlags(enabled.flags() | Qt.ItemFlag.ItemIsEditable)
        for c, value in enumerate(
            [
                enabled,
                server.name,
                server.command,
                " ".join(server.args),
                server.transport,
            ]
        ):
            self.table.setItem(
                r, c, value if isinstance(value, QTableWidgetItem) else QTableWidgetItem(str(value))
            )

    def add_row(self) -> None:
        self._insert_row(McpServerConfig(name="New MCP Server", command="npx"))

    def _selected_server(self) -> str:
        row = self.table.currentRow()
        if row < 0:
            return ""
        return self.table.item(row, 1).text().strip()

    def _collect(self) -> list[McpServerConfig]:
        servers = []
        for r in range(self.table.rowCount()):
            servers.append(
                McpServerConfig(
                    name=self.table.item(r, 1).text().strip() or f"server-{r}",
                    command=self.table.item(r, 2).text().strip(),
                    args=[a for a in self.table.item(r, 3).text().split() if a],
                    enabled=self.table.item(r, 0).text().lower() in {"true", "1", "yes"},
                    transport=self.table.item(r, 4).text().strip() or "stdio",
                )
            )
        return servers

    def accept(self) -> None:
        self.config.mcp_servers = self._collect()
        self.config.save()
        super().accept()

    def test_selected(self) -> None:
        name = self._selected_server()
        if not name:
            QMessageBox.information(self, "MCP Servers", "Select a server row first.")
            return
        server = next((s for s in self._collect() if s.name == name), None)
        if server is None:
            return
        self.config.mcp_servers = self._collect()
        from myloai.ui.workers import AsyncTask

        def work():
            async def run():
                from myloai.core.mcp import McpClient

                client = McpClient(server)
                try:
                    await client.start()
                    tools = await client.list_tools()
                    return f"Connected. {len(tools)} tools: " + ", ".join(t.name for t in tools)
                finally:
                    await client.stop()

            import asyncio

            return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(run())

        task = AsyncTask(work)
        task.result.connect(lambda msg: QMessageBox.information(self, "MCP Test", str(msg)))
        task.error.connect(lambda err: QMessageBox.critical(self, "MCP Test", str(err)))
        task.start()
        self._test_task = task

    def list_tools_selected(self) -> None:
        name = self._selected_server()
        if not name:
            QMessageBox.information(self, "MCP Tools", "Select a server row first.")
            return
        import asyncio
        import json as _json

        from myloai.core.mcp import McpClient

        server = next((s for s in self._collect() if s.name == name), None)
        if server is None:
            return

        def work():
            async def run():
                client = McpClient(server)
                try:
                    await client.start()
                    tools = await client.list_tools()
                    return _json.dumps(
                        [
                            {"name": t.name, "description": t.description, "inputSchema": t.input_schema}
                            for t in tools
                        ],
                        indent=2,
                    )
                finally:
                    await client.stop()

            return asyncio.new_event_loop().run_until_complete(run())

        from myloai.ui.workers import AsyncTask

        task = AsyncTask(work)
        task.result.connect(lambda text: self._show_details("MCP Tools", str(text)))
        task.error.connect(lambda err: QMessageBox.critical(self, "MCP Tools", str(err)))
        task.start()
        self._tools_task = task

    def _show_details(self, title: str, text: str) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.setText(text[:1000])
        box.setDetailedText(text)
        box.exec()


class SkillBuilderDialog(QDialog):
    """Create, edit, import, export, and delete skills (SKILL.md bundles)."""

    def __init__(self, manager: SkillManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Skills Builder")
        self.resize(820, 560)
        self.manager = manager
        self.current_id = ""
        self.skills = QListWidget()
        self.skills.currentRowChanged.connect(self.load_selected)
        self.name = QLineEdit("New Skill")
        self.description = QLineEdit()
        self.version = QLineEdit("1.0.0")
        self.tags = QLineEdit()
        self.instructions = QPlainTextEdit()
        self.instructions.setPlaceholderText("Skill instructions (become the chat system prompt when applied).")
        form = QFormLayout()
        for label, widget in [
            ("Name", self.name),
            ("Description", self.description),
            ("Version", self.version),
            ("Tags CSV", self.tags),
        ]:
            form.addRow(label, widget)
        buttons_row = QHBoxLayout()
        for text, slot in [
            ("New", self.new),
            ("Save", self.save),
            ("Delete", self.delete),
            ("Import", self.import_skill),
            ("Export", self.export_skill),
        ]:
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            buttons_row.addWidget(btn)
        layout = QHBoxLayout(self)
        layout.addWidget(self.skills, 1)
        right = QVBoxLayout()
        right.addLayout(form)
        right.addWidget(QLabel("Instructions"))
        right.addWidget(self.instructions)
        right.addLayout(buttons_row)
        layout.addLayout(right, 2)
        self.refresh()

    def refresh(self) -> None:
        self.items = self.manager.list()
        self.skills.clear()
        for skill in self.items:
            self.skills.addItem(f"{skill.name} (v{skill.version})")

    def load_selected(self, row: int) -> None:
        if row < 0 or row >= len(self.items):
            return
        skill = self.items[row]
        self.current_id = skill.id
        self.name.setText(skill.name)
        self.description.setText(skill.description)
        self.version.setText(skill.version)
        self.tags.setText(",".join(skill.tags))
        self.instructions.setPlainText(skill.instructions)

    def new(self) -> None:
        self.current_id = ""
        self.name.setText("New Skill")

    def _skill(self) -> SkillRecord:
        return SkillRecord(
            name=self.name.text().strip() or "Untitled Skill",
            instructions=self.instructions.toPlainText(),
            description=self.description.text().strip(),
            version=self.version.text().strip() or "1.0.0",
            tags=[t.strip() for t in self.tags.text().split(",") if t.strip()],
            id=self.current_id or SkillRecord("x", "").id,
        )

    def save(self) -> None:
        self.manager.upsert(self._skill())
        self.refresh()

    def delete(self) -> None:
        if self.current_id:
            self.manager.delete(self.current_id)
            self.current_id = ""
            self.refresh()

    def import_skill(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import Skill", filter="Markdown (*.md)")
        if path:
            skill = self.manager.import_file(Path(path))
            self.refresh()
            idx = next((i for i, s in enumerate(self.items) if s.id == skill.id), -1)
            if idx >= 0:
                self.skills.setCurrentRow(idx)

    def export_skill(self) -> None:
        if not self.current_id:
            QMessageBox.information(self, "Export Skill", "Select a skill to export.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export Skill", f"{self.name.text()}.md", "Markdown (*.md)")
        if path:
            self.manager.export(self._skill(), Path(path))
