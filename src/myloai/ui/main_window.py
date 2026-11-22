from __future__ import annotations

import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import psutil
from PySide6.QtCore import QByteArray, Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from myloai import __version__
from myloai.backends.manager import create_backend
from myloai.backends.ollama import OllamaBackend
from myloai.core.config import APP_SYSTEM_PROMPT, AppConfig
from myloai.core.domain import AgentProfile, ChatMessage, ChatSession, ModelInfo
from myloai.core.managers import (
    AgentManager,
    PluginContext,
    PluginManager,
    PromptManager,
    SessionManager,
    SkillManager,
    apply_agent_to_session,
    apply_skill_to_session,
)
from myloai.core.mcp import McpManager
from myloai.core.operations import OperationStreamParser, OperationUpdate
from myloai.core.tools import ToolRegistry
from myloai.ui.chat_view import (
    assistant_label,
    compute_scroll_restore_plan,
    redacted_request_messages,
    visible_chat_messages,
)
from myloai.ui.controllers import ChatController, ModelController, PluginController
from myloai.ui.diagnostics import (
    DiagnosticsSignals,
    LineBufferedStream,
    QtLogHandler,
    append_output,
)
from myloai.ui.dialogs import (
    AgentBuilderDialog,
    EndpointDialog,
    McpServersDialog,
    ModelfileEditor,
    ParameterDialog,
    PluginManagerDialog,
    PromptManagerDialog,
    SkillBuilderDialog,
)
from myloai.ui.documents import bundled_document_path
from myloai.ui.model_browser import ModelBrowserDialog
from myloai.ui.theme import dark_qss
from myloai.ui.workers import AsyncTask, StreamTask

LOG = logging.getLogger(__name__)

# Reserved MainWindow UI placeholders retained for future implementation:
# from PySide6.QtWidgets import QLineEdit, QSplitter, QTreeWidget, QTreeWidgetItem
# Historical stylesheet constant retained as a reference; the active MainWindow
# uses dark_qss(font_size) so font-size changes remain centralized.
# from myloai.ui.theme import DARK_QSS


def _build_readonly_table_item(value: str) -> QTableWidgetItem:
    item = QTableWidgetItem(value)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return item


class ChatTab(QWidget):
    def __init__(self, session: ChatSession) -> None:
        super().__init__()
        self.session = session
        self.chat = QTextEdit()
        self.chat.setReadOnly(True)
        self.input = ComposerTextEdit()
        self.input.setPlaceholderText("Write a message. Press Ctrl+Enter (or Ctrl+Return) to send.")
        self.input.setMaximumHeight(140)
        self.streaming = QCheckBox("Stream")
        self.streaming.setChecked(True)
        self.send = QPushButton("Send")
        self.stop = QPushButton("Stop")
        self.regen = QPushButton("Regenerate")
        self.retry = QPushButton("Retry")
        self.copy_last = QPushButton("Copy Last")
        self.edit_msg = QPushButton("Edit Message")
        self.delete_msg = QPushButton("Delete Message")
        row = QHBoxLayout()
        row.addWidget(self.streaming)
        row.addStretch()
        row.addWidget(self.copy_last)
        row.addWidget(self.edit_msg)
        row.addWidget(self.delete_msg)
        row.addWidget(self.retry)
        row.addWidget(self.regen)
        row.addWidget(self.stop)
        row.addWidget(self.send)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.chat)
        layout.addWidget(self.input)
        layout.addLayout(row)
        self.render()
        self.set_generating(False)

    def render(self, active_model: str = "") -> None:
        scroll = self.chat.verticalScrollBar()
        plan = compute_scroll_restore_plan(scroll.value(), scroll.maximum())
        palette = QApplication.palette()
        base_color = palette.base().color().name()
        text_color = palette.text().color().name()
        html = []
        colors = {"system": "#8fbcbb", "user": "#a3be8c", "assistant": "#81a1c1", "tool": "#d08770"}
        for idx, msg in enumerate(visible_chat_messages(self.session.messages)):
            safe = (
                msg.content.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\n", "<br>")
            )
            html.append(
                f"<div style='margin:10px 0;padding:10px;border-left:3px solid {colors.get(msg.role, '#ccc')};background:{base_color};color:{text_color};border-radius:6px'><b>{idx + 1}. {assistant_label(msg, active_model)}</b><br>{safe}</div>"
            )
        self.chat.setHtml("".join(html))
        if plan.should_pin_bottom:
            scroll.setValue(scroll.maximum())
        else:
            scroll.setValue(min(plan.previous_value, scroll.maximum()))

    def set_generating(self, generating: bool) -> None:
        self.send.setEnabled(not generating)
        self.stop.setEnabled(generating)
        self.retry.setEnabled(not generating)
        self.regen.setEnabled(not generating)
        self.input.setReadOnly(generating)


class ComposerTextEdit(QPlainTextEdit):
    send_requested = Signal()
    zoom_requested = Signal(int)

    def keyPressEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.send_requested.emit()
                event.accept()
                return
            if event.key() in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
                self.zoom_requested.emit(1)
                event.accept()
                return
            if event.key() == Qt.Key.Key_Minus:
                self.zoom_requested.emit(-1)
                event.accept()
                return
            if event.key() == Qt.Key.Key_0:
                self.zoom_requested.emit(0)
                event.accept()
                return
        super().keyPressEvent(event)

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                self.zoom_requested.emit(1 if delta > 0 else -1)
                event.accept()
                return
        super().wheelEvent(event)


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
        self.setWindowTitle("MyLoAI Control Center")
        self.resize(1440, 900)
        self.setStyleSheet(dark_qss(self.config.ui.font_size))
        self.sessions = SessionManager(config)
        self.prompts = PromptManager(config)
        self.agents = AgentManager(config)
        self.skills = SkillManager(config)
        self.mcp = McpManager(config)
        self.tool_registry = ToolRegistry()
        self.plugin_context = PluginContext(self, config)
        self.plugins = PluginManager(config, self.plugin_context)
        self.models: list[ModelInfo] = []
        self.chat_controller = ChatController(self.sessions, self.config, self)
        self.model_controller = ModelController(self.config, self)
        self.plugin_controller = PluginController(self.plugins, self.config, self)
        self.worker_refs: list[Any] = []
        self.current_stream: StreamTask | None = None
        self._stream_owner_seq = 0
        self._active_stream_owner: int | None = None
        self._diagnostics_signals = DiagnosticsSignals(self)
        self._diagnostics_log_handler: QtLogHandler | None = None
        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr
        self._build_ui()
        self._install_diagnostics_sinks()
        self._build_menus()
        self._restore_state()
        self.plugins.load_enabled()
        self._sync_plugin_tools()
        self.new_chat()
        self.refresh_backend()
        self.start_mcp_servers()

    def _build_ui(self) -> None:
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.setCentralWidget(self.tabs)
        self.status = self.statusBar()
        self.status.showMessage("Disconnected")
        self.toolbar = QToolBar("Main")
        self.toolbar.setObjectName("mainToolbar")
        self.addToolBar(self.toolbar)
        for label, slot in [
            ("New Chat", self.new_chat),
            ("Save", self.chat_controller.save_current),
            ("Refresh Models", self.refresh_backend),
            ("Parameters", self.open_parameters),
            ("Plugins", self.open_plugins),
            ("Prompt Manager", self.open_prompt_manager),
        ]:
            action = QAction(label, self)
            action.triggered.connect(slot)
            self.toolbar.addAction(action)
        self.provider_combo = QComboBox()
        self.provider_combo.addItems([p.name for p in self.config.provider_profiles])
        self.provider_combo.setCurrentText(self.config.active_provider)
        self.provider_combo.currentTextChanged.connect(self.switch_provider)
        self.toolbar.addWidget(QLabel(" Provider "))
        self.toolbar.addWidget(self.provider_combo)
        self.model_combo = QComboBox()
        self.model_combo.currentTextChanged.connect(self.model_changed)
        self.toolbar.addWidget(QLabel(" Model "))
        self.toolbar.addWidget(self.model_combo)
        self.agent_combo = QComboBox()
        self.agent_combo.currentTextChanged.connect(self.agent_changed)
        self.toolbar.addWidget(QLabel(" Agent "))
        self.toolbar.addWidget(self.agent_combo)
        self.refresh_agents()
        self._create_docks()

    def _create_docks(self) -> None:
        self.model_table = QTableWidget(0, 8)
        self.model_table.setHorizontalHeaderLabels(
            ["Name", "Size", "Quant", "Params", "Ctx", "Backend", "RAM/VRAM", "Metadata"]
        )
        self._dock("Models", self.model_table, Qt.DockWidgetArea.LeftDockWidgetArea)
        self.sessions_list = QListWidget()
        self.sessions_list.itemDoubleClicked.connect(
            lambda item: self.open_session(item.data(Qt.ItemDataRole.UserRole))
        )
        self._dock("Chat Sessions", self.sessions_list, Qt.DockWidgetArea.LeftDockWidgetArea)
        self.prompt_list = QListWidget()
        self.prompt_list.itemDoubleClicked.connect(self.apply_prompt_item)
        self._dock("System Prompts", self.prompt_list, Qt.DockWidgetArea.RightDockWidgetArea)
        self.skill_list = QListWidget()
        self.skill_list.itemDoubleClicked.connect(self.apply_skill_item)
        self._dock("Skills", self.skill_list, Qt.DockWidgetArea.RightDockWidgetArea)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText("Structured Python logging records.")
        self.console_view = QPlainTextEdit()
        self.console_view.setReadOnly(True)
        self.console_view.setPlaceholderText("Captured stdout and stderr output.")
        self.operation_status = QLabel("No model operation is active.")
        self.operation_progress = QProgressBar()
        self.operation_progress.setRange(0, 1)
        self.operation_progress.setValue(0)
        self.operation_history = QPlainTextEdit()
        self.operation_history.setReadOnly(True)
        self.operation_history.setPlaceholderText("Model operation lifecycle and status history.")
        operations_widget = QWidget()
        operations_layout = QVBoxLayout(operations_widget)
        operations_layout.setContentsMargins(6, 6, 6, 6)
        operations_layout.addWidget(self.operation_status)
        operations_layout.addWidget(self.operation_progress)
        operations_layout.addWidget(self.operation_history)
        self.diagnostics_tabs = QTabWidget()
        self.diagnostics_tabs.addTab(self.log_view, "Logs")
        self.diagnostics_tabs.addTab(self.console_view, "Console")
        self.diagnostics_tabs.addTab(operations_widget, "Operations")
        self.diagnostics_dock = self._dock(
            "Diagnostics", self.diagnostics_tabs, Qt.DockWidgetArea.BottomDockWidgetArea
        )
        self.request_view = QPlainTextEdit()
        self.request_view.setReadOnly(True)
        self.request_copy = QPushButton("Copy Request")
        self.request_clear = QPushButton("Clear Request")
        self.request_copy.clicked.connect(lambda: QApplication.clipboard().setText(self.request_view.toPlainText()))
        self.request_clear.clicked.connect(self.request_view.clear)
        req_row = QHBoxLayout()
        req_row.addWidget(self.request_copy)
        req_row.addWidget(self.request_clear)
        req_wrap = QWidget()
        req_layout = QVBoxLayout(req_wrap)
        req_layout.setContentsMargins(0, 0, 0, 0)
        req_layout.addWidget(self.request_view)
        req_layout.addLayout(req_row)
        self.request_dock = self._dock("Request Viewer (Redacted)", req_wrap, Qt.DockWidgetArea.BottomDockWidgetArea)
        self.request_view.setPlaceholderText("Outbound request payload (app-internal system prompt is redacted).")
        self.token_view = QPlainTextEdit()
        self.token_view.setReadOnly(True)
        self.token_copy = QPushButton("Copy Tokens")
        self.token_clear = QPushButton("Clear Tokens")
        self.token_copy.clicked.connect(lambda: QApplication.clipboard().setText(self.token_view.toPlainText()))
        self.token_clear.clicked.connect(self.token_view.clear)
        tok_row = QHBoxLayout()
        tok_row.addWidget(self.token_copy)
        tok_row.addWidget(self.token_clear)
        tok_wrap = QWidget()
        tok_layout = QVBoxLayout(tok_wrap)
        tok_layout.setContentsMargins(0, 0, 0, 0)
        tok_layout.addWidget(self.token_view)
        tok_layout.addLayout(tok_row)
        self.token_dock = self._dock("Token/Response Viewer", tok_wrap, Qt.DockWidgetArea.BottomDockWidgetArea)
        self.token_view.setPlaceholderText("Current streamed response/tokens for active generation.")
        self.refresh_sessions()
        self.refresh_prompts()
        self.refresh_skills()

    def _dock(self, title: str, widget: QWidget, area: Qt.DockWidgetArea) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setWidget(widget)
        dock.setObjectName(title)
        self.addDockWidget(area, dock)
        return dock

    def add_plugin_panel(self, title: str, widget: QWidget, area: Any = None) -> QDockWidget:
        return self._dock(title, widget, area or Qt.DockWidgetArea.RightDockWidgetArea)

    def _menu_action(self, menu, text, slot, shortcut: str | None = None):
        action = QAction(text, self)
        action.triggered.connect(slot)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        menu.addAction(action)
        return action

    def _build_menus(self) -> None:
        self._build_file_menu()
        self._build_models_menu()
        self._build_agents_menu()
        self._build_skills_menu()
        self._build_plugins_menu()
        self._build_mcp_menu()
        self._build_settings_menu()
        self._build_view_menu()
        self._build_developer_menu()
        self._build_help_menu()

    def _build_file_menu(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        self._menu_action(file_menu, "New Chat", self.new_chat, "Ctrl+N")
        self._menu_action(
            file_menu, "Open Chat", lambda: self.chat_controller.open_chat_file(self), "Ctrl+O"
        )
        self._menu_action(file_menu, "Save", self.chat_controller.save_current, "Ctrl+S")
        self._menu_action(file_menu, "Save As", self.save_as)
        self._menu_action(file_menu, "Export", self.export_current)
        self._menu_action(file_menu, "Import", self.import_chat)
        file_menu.addSeparator()
        self._menu_action(file_menu, "Exit", self.close, "Ctrl+Q")

    def _build_models_menu(self) -> None:
        models_menu = self.menuBar().addMenu("Models")
        self._menu_action(models_menu, "Browse && Pull Models...", self.show_model_browser)
        models_menu.addSeparator()
        self._menu_action(models_menu, "Pull", lambda: self.model_controller.pull_model(self))
        self._menu_action(models_menu, "Push", lambda: self.model_controller.push_model(self))
        self._menu_action(models_menu, "Clone", lambda: self.model_controller.clone_model(self))
        self._menu_action(models_menu, "Create", self.model_controller.create_model)
        self._menu_action(models_menu, "Delete", lambda: self.model_controller.delete_model(self))
        models_menu.addSeparator()
        self._menu_action(models_menu, "Modelfiles", self.open_modelfile_editor)
        self._menu_action(models_menu, "Templates", self.open_template_viewer)

    def _build_agents_menu(self) -> None:
        agents_menu = self.menuBar().addMenu("Agents")
        self._menu_action(agents_menu, "Agent Builder...", self.open_agent_builder)
        agents_menu.addSeparator()
        self._menu_action(agents_menu, "Import Agent...", self.import_agent)
        self._menu_action(agents_menu, "Export Agent...", self.export_agent)

    def _build_skills_menu(self) -> None:
        skills_menu = self.menuBar().addMenu("Skills")
        self._menu_action(skills_menu, "Skills Builder...", self.open_skill_builder)
        self._menu_action(skills_menu, "Apply Skill to Chat...", self.apply_skill_dialog)
        skills_menu.addSeparator()
        self._menu_action(skills_menu, "Import Skill...", self.import_skill)
        self._menu_action(skills_menu, "Export Skill...", self.export_skill)

    def _build_plugins_menu(self) -> None:
        plugins_menu = self.menuBar().addMenu("Plugins")
        self._menu_action(plugins_menu, "Plugin Manager", self.open_plugins)
        self._menu_action(
            plugins_menu, "Install", lambda: self.plugin_controller.install_plugin(self)
        )
        self._menu_action(plugins_menu, "Reload", self.plugin_controller.reload_plugins)
        plugins_menu.addSeparator()
        self._menu_action(
            plugins_menu,
            "Plugin SDK Documentation",
            lambda: self.open_bundled_document("Plugin SDK", "PLUGIN_SDK.md"),
        )

    def _build_mcp_menu(self) -> None:
        mcp_menu = self.menuBar().addMenu("MCP")
        self._menu_action(mcp_menu, "MCP Servers...", self.open_mcp_servers)
        self._menu_action(mcp_menu, "Reconnect MCP Servers", self.start_mcp_servers)
        self._menu_action(mcp_menu, "List MCP Tools", self.list_mcp_tools)

    def _build_settings_menu(self) -> None:
        settings_menu = self.menuBar().addMenu("Settings")
        self._menu_action(settings_menu, "API Endpoints...", self.open_endpoints)
        self._menu_action(settings_menu, "AI Model Settings...", self.open_parameters)
        self._menu_action(settings_menu, "Prompt Manager...", self.open_prompt_manager)
        settings_menu.addSeparator()
        self._menu_action(settings_menu, "Theme...", self.choose_theme)
        self._menu_action(settings_menu, "Keyboard Shortcuts", self.show_shortcuts)
        self._menu_action(settings_menu, "Default System Prompt...", self.edit_default_system_prompt)
        settings_menu.addSeparator()
        self._menu_action(settings_menu, "Increase Font Size", lambda: self.adjust_font_size(1), "Ctrl++")
        self._menu_action(settings_menu, "Decrease Font Size", lambda: self.adjust_font_size(-1), "Ctrl+-")
        self._menu_action(settings_menu, "Reset Font Size", lambda: self.adjust_font_size(0), "Ctrl+0")

    def _build_view_menu(self) -> None:
        view_menu = self.menuBar().addMenu("View")
        self._menu_action(view_menu, "Toggle Panels", self.toggle_all_docks)
        self._menu_action(view_menu, "Reset Layout", self.reset_layout)
        view_menu.addSeparator()
        for label, slot in [
            ("Models Panel", lambda: self._show_dock(self.find_dock("Models"), "Models")),
            ("Chat Sessions Panel", lambda: self._show_dock(self.find_dock("Chat Sessions"), "Chat Sessions")),
            ("System Prompts Panel", lambda: self._show_dock(self.find_dock("System Prompts"), "System Prompts")),
            ("Skills Panel", lambda: self._show_dock(self.find_dock("Skills"), "Skills")),
            ("Diagnostics Panel", self.show_diagnostics_dock),
            ("Request Viewer", self.show_request_dock),
            ("Token Viewer", self.show_token_dock),
        ]:
            self._menu_action(view_menu, label, slot)

    def _build_developer_menu(self) -> None:
        developer_menu = self.menuBar().addMenu("Developer")
        self._menu_action(developer_menu, "Request Inspector", self.inspect_api)
        diagnostics_menu = developer_menu.addMenu("Diagnostics")
        self._menu_action(diagnostics_menu, "Logs", self.show_logs_dock)
        self._menu_action(diagnostics_menu, "Console", self.show_console_dock)
        self._menu_action(diagnostics_menu, "Operations", self.show_operations_dock)
        self._menu_action(diagnostics_menu, "Request Viewer", self.show_request_dock)
        self._menu_action(diagnostics_menu, "Token Viewer", self.show_token_dock)

    def _build_help_menu(self) -> None:
        help_menu = self.menuBar().addMenu("Help")
        self._menu_action(
            help_menu,
            "What is all this? (Learning Guide)",
            lambda: self.open_bundled_document("Learning Guide", "LEARNING_GUIDE.md"),
        )
        self._menu_action(
            help_menu,
            "Documentation",
            lambda: self.open_bundled_document("Documentation", "USER_MANUAL.md"),
        )
        self._menu_action(help_menu, "About", self.about)

    def current_tab(self) -> ChatTab | None:
        w = self.tabs.currentWidget()
        return w if isinstance(w, ChatTab) else None

    def refresh_agents(self, select_id: str = "") -> None:
        self.agent_combo.blockSignals(True)
        current = select_id or self.agent_combo.currentData() or ""
        self.agent_combo.clear()
        self.agent_combo.addItem("(none)", "")
        for agent in self.agents.list():
            self.agent_combo.addItem(agent.name, agent.id)
        idx = self.agent_combo.findData(current)
        self.agent_combo.setCurrentIndex(max(idx, 0))
        self.agent_combo.blockSignals(False)

    def selected_agent(self):
        agent_id = self.agent_combo.currentData() or ""
        return self.agents.get(agent_id) if agent_id else None

    def agent_changed(self, _name: str) -> None:
        tab = self.current_tab()
        agent = self.selected_agent()
        if tab is not None and agent is not None:
            apply_agent_to_session(tab.session, agent, self.prompts.list())
            if agent.model:
                idx = self.model_combo.findText(agent.model)
                if idx >= 0:
                    self.model_combo.setCurrentIndex(idx)
            self.render_tab(tab)
            self.sessions.save(tab.session)
            self.refresh_sessions()

    def new_chat(self) -> None:
        session = ChatSession(
            provider=self.config.active_provider,
            model=self.model_combo.currentText(),
            system_prompt=self.config.global_system_prompt,
        )
        if session.system_prompt:
            session.messages.append(ChatMessage("system", session.system_prompt))
        agent = self.selected_agent()
        if agent is not None:
            apply_agent_to_session(session, agent, self.prompts.list())
        tab = ChatTab(session)
        self._wire_chat_tab(tab)
        self.tabs.addTab(tab, session.title)
        self.tabs.setCurrentWidget(tab)

    def _wire_chat_tab(self, tab: ChatTab) -> None:
        tab.send.clicked.connect(self.chat_controller.send_message)
        tab.input.send_requested.connect(self.chat_controller.send_message)
        tab.input.zoom_requested.connect(self.adjust_font_size)
        tab.stop.clicked.connect(self.stop_generation)
        tab.regen.clicked.connect(self.chat_controller.regenerate)
        tab.retry.clicked.connect(self.chat_controller.retry)
        tab.copy_last.clicked.connect(self.chat_controller.copy_last_message)
        tab.edit_msg.clicked.connect(lambda: self.chat_controller.edit_message(self))
        tab.delete_msg.clicked.connect(lambda: self.chat_controller.delete_message(self))

    def close_tab(self, idx: int) -> None:
        if self.tabs.count() > 1:
            self.tabs.removeTab(idx)

    def _generate(self, tab: ChatTab) -> None:
        profile = self.config.active_profile()
        backend = create_backend(profile)
        agent = self.agents.get(tab.session.agent_id) if tab.session.agent_id else None
        model = (agent.model if agent and agent.model else "") or self.model_combo.currentText() or profile.default_model
        if not model:
            QMessageBox.warning(self, "No model", "Select or configure a model before generating.")
            return
        tab.session.model = model
        tab.session.provider = profile.name
        messages = [ChatMessage("system", APP_SYSTEM_PROMPT, metadata={"internal": True, "source": "app"})]
        messages.extend(tab.session.messages)
        for interceptor in self.plugin_context.chat_interceptors:
            messages = interceptor(messages)
        options = self.config.parameters.to_backend_options()
        options.update(tab.session.parameters or {})
        tools = self._available_tools(agent)
        if tools:
            options["tools"] = tools
        request_preview = {
            "provider": profile.name,
            "url": profile.base_url,
            "model": model,
            "messages": redacted_request_messages(messages),
            "options": options,
        }
        if isinstance(backend, OllamaBackend):
            request_preview = backend.build_chat_payload(model, messages, options, tab.streaming.isChecked())
            request_preview.update({"provider": profile.name, "url": profile.base_url})
            request_preview["messages"] = redacted_request_messages(messages)
        self.request_view.setPlainText(json.dumps(request_preview, indent=2, default=str))
        tab.set_generating(True)
        self.token_view.clear()
        assistant = ChatMessage("assistant", "")
        tab.session.messages.append(assistant)
        tab.render(model)
        if tools:
            self._generate_with_tools(tab, backend, model, messages, options)
            return
        self.status.showMessage("generating" if not tab.streaming.isChecked() else "streaming")
        task = StreamTask(
            lambda: backend.chat(
                model,
                messages,
                options,
                tab.streaming.isChecked(),
            )
        )
        self._stream_owner_seq += 1
        owner = self._stream_owner_seq
        self.current_stream = task
        self._active_stream_owner = owner
        self.worker_refs.append(task)
        task.token.connect(lambda tok, owner_id=owner: self._append_token(tab, assistant, tok, owner_id))
        task.error.connect(lambda error, owner_id=owner: self._stream_error(error, owner_id))
        task.completed.connect(lambda _, owner_id=owner: self._stream_done(tab, owner_id))
        task.start()

    def _append_token(self, tab: ChatTab, msg: ChatMessage, token: str, owner_id: int) -> None:
        if self._active_stream_owner != owner_id:
            return
        msg.content += token
        self.token_view.insertPlainText(token)
        tab.render(self.model_combo.currentText() or tab.session.model)

    def _stream_error(self, error: str, owner_id: int) -> None:
        if self._active_stream_owner != owner_id:
            return
        self.status.showMessage("idle")
        tab = self.current_tab()
        if tab:
            tab.set_generating(False)
        self._active_stream_owner = None
        self.current_stream = None
        self.log(f"Generation error: {error}")
        QMessageBox.critical(self, "Generation Error", error)

    def _stream_done(self, tab: ChatTab, owner_id: int) -> None:
        if self._active_stream_owner != owner_id:
            return
        self.status.showMessage("idle")
        tab.set_generating(False)
        self._active_stream_owner = None
        self.current_stream = None
        self.sessions.save(tab.session)
        self.refresh_sessions()
        tab.render(self.model_combo.currentText() or tab.session.model)

    def stop_generation(self) -> None:
        if self.current_stream:
            self.current_stream.cancel()
            self._active_stream_owner = None
            self.current_stream = None
            tab = self.current_tab()
            if tab:
                tab.set_generating(False)
            self.status.showMessage("idle")
            self.log("Generation stopped by user.")

    def model_changed(self, text: str) -> None:
        tab = self.current_tab()
        if tab:
            tab.session.model = text

    def refresh_backend(self) -> None:
        profile = self.config.active_profile()
        self.status.showMessage(f"testing {profile.base_url}")
        backend = create_backend(profile)

        async def work():
            status = await backend.test_connection()
            models = await backend.list_models() if status.state == "connected" else []
            return status, models

        task = AsyncTask(work)
        self.worker_refs.append(task)
        task.result.connect(self._backend_refreshed)
        task.error.connect(lambda e: self._backend_refresh_error(e))
        task.start()

    def _show_dock(self, dock: QDockWidget | None, name: str) -> None:
        if dock is None:
            self.status.showMessage(f"{name} panel unavailable")
            self.log(f"{name} panel unavailable")
            return
        dock.show()
        dock.raise_()

    def show_diagnostics_dock(self) -> None:
        self._show_dock(self.diagnostics_dock, "Diagnostics")

    def _show_diagnostics_tab(self, index: int) -> None:
        self.diagnostics_tabs.setCurrentIndex(index)
        self.show_diagnostics_dock()

    def show_logs_dock(self) -> None:
        self._show_diagnostics_tab(0)

    def show_console_dock(self) -> None:
        self._show_diagnostics_tab(1)

    def show_operations_dock(self) -> None:
        self._show_diagnostics_tab(2)

    def show_request_dock(self) -> None:
        self._show_dock(self.request_dock, "Request Viewer")

    def show_token_dock(self) -> None:
        self._show_dock(self.token_dock, "Token Viewer")

    def _backend_refresh_error(self, error: str) -> None:
        self.status.showMessage("backend refresh failed")
        self.log(f"Backend refresh error: {error}")
        QMessageBox.critical(self, "Backend Refresh Error", error)

    def _backend_refreshed(self, result: Any) -> None:
        status, self.models = result
        self._update_backend_status(status.state, status.latency_ms, status.detail)
        self._refresh_model_combo()
        self._refresh_model_table()

    def _update_backend_status(self, state: str, latency_ms: float, detail: str) -> None:
        model = self.model_combo.currentText() or "(none)"
        self.status.showMessage(
            f"{state} | {latency_ms:.0f} ms | {self.config.active_profile().name} | {model}"
        )
        self.log(f"Backend {state}: {detail}")

    def _refresh_model_combo(self) -> None:
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItems([model.name for model in self.models])
        self.model_combo.blockSignals(False)

    def _refresh_model_table(self) -> None:
        self.model_table.setRowCount(0)
        for model in self.models:
            self._insert_model_table_row(model)

    def _insert_model_table_row(self, model: ModelInfo) -> None:
        row = self.model_table.rowCount()
        self.model_table.insertRow(row)
        ram = model.size_display if model.size else "backend reported"
        values = [
            model.name,
            model.size_display,
            model.quantization,
            model.parameter_size,
            str(model.context_size or ""),
            model.backend,
            ram,
            json.dumps(model.metadata)[:400],
        ]
        for column, value in enumerate(values):
            self.model_table.setItem(row, column, _build_readonly_table_item(value))

    def switch_provider(self, name: str) -> None:
        self.config.active_provider = name
        self.config.save()
        self.refresh_backend()

    def refresh_sessions(self) -> None:
        self.sessions_list.clear()
        for s in self.sessions.list_sessions():
            self.sessions_list.addItem(f"{s.updated_at[:19]}  {s.title}")
            self.sessions_list.item(self.sessions_list.count() - 1).setData(
                Qt.ItemDataRole.UserRole, s.id
            )

    def refresh_prompts(self) -> None:
        self.prompt_list.clear()
        for p in self.prompts.list():
            self.prompt_list.addItem(("★ " if p.favorite else "") + f"{p.category}: {p.title}")
            self.prompt_list.item(self.prompt_list.count() - 1).setData(
                Qt.ItemDataRole.UserRole, p.content
            )

    def apply_prompt_item(self, item) -> None:
        tab = self.current_tab()
        if not tab:
            return
        content = item.data(Qt.ItemDataRole.UserRole)
        tab.session.system_prompt = content
        if tab.session.messages and tab.session.messages[0].role == "system":
            tab.session.messages[0].content = content
        else:
            tab.session.messages.insert(0, ChatMessage("system", content))
        tab.render(self.model_combo.currentText() or tab.session.model)

    def save_as(self) -> None:
        tab = self.current_tab()
        if not tab:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Chat As", f"{tab.session.title}.json", "JSON (*.json)"
        )
        if path:
            Path(path).write_text(tab.session.to_json(), encoding="utf-8")

    def open_session(self, session_id: str) -> None:
        session = self.sessions.load(session_id)
        self.refresh_agents(select_id=session.agent_id)
        tab = ChatTab(session)
        self._wire_chat_tab(tab)
        self.tabs.addTab(tab, session.title)
        self.tabs.setCurrentWidget(tab)

    def import_chat(self) -> None:
        self.chat_controller.open_chat_file(self)

    def export_current(self) -> None:
        tab = self.current_tab()
        if not tab:
            return
        path, _selected = QFileDialog.getSaveFileName(
            self,
            "Export Chat",
            f"{tab.session.title}.md",
            "Markdown (*.md);;JSON (*.json);;Text (*.txt)",
        )
        if not path:
            return
        p = Path(path)
        content = (
            tab.session.to_json()
            if p.suffix == ".json"
            else tab.session.export_text()
            if p.suffix == ".txt"
            else tab.session.export_markdown()
        )
        p.write_text(content, encoding="utf-8")

    def _async(self, coro_factory, done_msg: str) -> None:
        task = AsyncTask(coro_factory)
        self.worker_refs.append(task)
        task.finished_ok.connect(lambda: (self.log(done_msg), self.refresh_backend()))
        task.error.connect(lambda e: QMessageBox.critical(self, "Error", e))
        task.start()

    def run_async(
        self,
        coro_factory,
        done_msg: str,
        *,
        start_msg: str,
        error_title: str,
        parent: QWidget | None = None,
    ) -> None:
        self.begin_operation(start_msg)
        task = AsyncTask(coro_factory)
        self.worker_refs.append(task)

        def on_completed() -> None:
            self.complete_operation(done_msg)
            self.log(done_msg)
            self.refresh_backend()

        def on_error(error: str) -> None:
            self.fail_operation(start_msg, error)
            dialog_parent = parent if parent is not None else self
            QMessageBox.critical(dialog_parent, error_title, error)

        task.finished_ok.connect(on_completed)
        task.error.connect(on_error)
        task.start()

    def set_tab_title(self, title: str) -> None:
        self.tabs.setTabText(self.tabs.currentIndex(), title)

    def render_tab(self, tab: ChatTab) -> None:
        tab.render(self.model_combo.currentText() or tab.session.model)

    def generate_for_tab(self, tab: ChatTab) -> None:
        self._generate(tab)

    def model_name(self) -> str:
        return self.model_combo.currentText()

    def _install_diagnostics_sinks(self) -> None:
        self._diagnostics_signals.log_line.connect(self.append_log)
        self._diagnostics_signals.console_text.connect(self.append_console)
        self._diagnostics_log_handler = QtLogHandler(self._diagnostics_signals)
        logging.getLogger().addHandler(self._diagnostics_log_handler)
        sys.stdout = LineBufferedStream(
            self._diagnostics_signals.console_text.emit, self._original_stdout
        )
        sys.stderr = LineBufferedStream(
            self._diagnostics_signals.console_text.emit, self._original_stderr
        )

    def append_log(self, text: str) -> None:
        append_output(self.log_view, text)

    def append_console(self, text: str) -> None:
        append_output(self.console_view, text)

    def append_operation_history(self, text: str) -> None:
        if not text.endswith("\n"):
            text += "\n"
        append_output(self.operation_history, text)

    def begin_operation(self, operation: str) -> None:
        self.operation_status.setText(operation)
        self.operation_progress.setRange(0, 0)
        self.append_operation_history(f"[START] {operation}")

    def update_operation(self, update: OperationUpdate) -> None:
        self.operation_status.setText(update.status)
        if update.total and update.total > 0 and update.completed is not None:
            progress = max(0, min(100, int(update.completed * 100 / update.total)))
            self.operation_progress.setRange(0, 100)
            self.operation_progress.setValue(progress)
        else:
            self.operation_progress.setRange(0, 0)
        if update.history_text:
            self.append_operation_history(update.history_text)

    def complete_operation(self, operation: str) -> None:
        self.operation_status.setText(f"Completed: {operation}")
        self.operation_progress.setRange(0, 1)
        self.operation_progress.setValue(1)
        self.append_operation_history(f"[OK] {operation}")

    def fail_operation(self, operation: str, error: str) -> None:
        self.operation_status.setText(f"Failed: {operation}")
        self.operation_progress.setRange(0, 1)
        self.operation_progress.setValue(0)
        self.append_operation_history(f"[ERROR] {operation}: {error}")

    def add_worker(self, worker: Any) -> None:
        self.worker_refs.append(worker)

    def open_modelfile_editor(self) -> None:
        ModelfileEditor(self.config, self).exec()

    def build_model_from_modelfile(self, name: str, modelfile: str) -> None:
        name = name.strip()
        if not name:
            QMessageBox.warning(self, "Create Model", "Model name is required.")
            return
        operation = f"Create model: {name}"
        parser = OperationStreamParser()
        self.begin_operation(operation)
        task = StreamTask(
            lambda: create_backend(self.config.active_profile()).create_model(name, modelfile)
        )
        self.worker_refs.append(task)

        def on_stream(chunk: str) -> None:
            for update in parser.feed(chunk):
                self.update_operation(update)

        def on_completed(_output: str) -> None:
            self.complete_operation(operation)
            self.refresh_backend()

        def on_error(error: str) -> None:
            self.fail_operation(operation, error)
            QMessageBox.critical(self, "Create Model", error)

        task.token.connect(on_stream)
        task.completed.connect(on_completed)
        task.error.connect(on_error)
        task.start()

    def open_template_viewer(self) -> None:
        model = self.model_combo.currentText().strip()
        if not model:
            QMessageBox.information(
                self,
                "Template Viewer",
                "Select a model before inspecting its template.",
            )
            return

        operation = f"Load template: {model}"
        self.begin_operation(operation)

        async def show():
            return await create_backend(self.config.active_profile()).show_model(model)

        def on_result(data: Any) -> None:
            self.complete_operation(operation)
            self._show_text_dialog("Template Viewer", json.dumps(data, indent=2))

        def on_error(error: str) -> None:
            self.fail_operation(operation, error)
            QMessageBox.critical(self, "Template Viewer", error)

        task = AsyncTask(show)
        self.worker_refs.append(task)
        task.result.connect(on_result)
        task.error.connect(on_error)
        task.start()

    def _show_text_dialog(self, title: str, text: str) -> None:
        d = QMessageBox(self)
        d.setWindowTitle(title)
        d.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        d.setDetailedText(text)
        d.setText(text[:1000])
        d.exec()

    def open_endpoints(self) -> None:
        if EndpointDialog(self.config, self).exec():
            self.provider_combo.clear()
            self.provider_combo.addItems([p.name for p in self.config.provider_profiles])
            self.refresh_backend()

    def open_parameters(self) -> None:
        ParameterDialog(self.config, self).exec()

    def open_prompt_manager(self) -> None:
        PromptManagerDialog(self.prompts, self).exec()
        self.refresh_prompts()

    def edit_default_system_prompt(self) -> None:
        text, ok = QInputDialog.getMultiLineText(
            self,
            "Default System Prompt",
            "User-editable default system prompt for new chats:",
            self.config.global_system_prompt,
        )
        if ok:
            self.config.global_system_prompt = text.strip() or "You are a helpful, concise assistant."
            self.config.save()
            self.status.showMessage("Default system prompt saved.")

    def open_plugins(self) -> None:
        PluginManagerDialog(self.plugins, self).exec()
        self._sync_plugin_tools()

    def _sync_plugin_tools(self) -> None:
        self.tool_registry.unregister_source("plugin")
        for name, handler in self.plugin_context.tools.items():
            self.tool_registry.register(
                name,
                f"Plugin tool '{name}'",
                {"type": "object", "properties": {"text": {"type": "string"}}},
                handler,
                source="plugin",
            )

    def open_agent_builder(self) -> None:
        AgentBuilderDialog(
            self.agents,
            [m.name for m in self.models],
            list(self.plugins.loaded),
            self.prompts.list(),
            self,
        ).exec()
        self.refresh_agents()

    def import_agent(self) -> None:
        path = self.ask_open_file("Import Agent", "JSON (*.json)")
        if not path:
            return
        try:
            agent = AgentProfile(**json.loads(Path(path).read_text(encoding="utf-8")))
            self.agents.upsert(agent)
            self.refresh_agents()
            QMessageBox.information(self, "Import Agent", f"Imported agent: {agent.name}")
        except (OSError, ValueError, TypeError, KeyError) as error:
            self.show_error("Import Agent", str(error))

    def export_agent(self) -> None:
        agents = self.agents.list()
        if not agents:
            QMessageBox.information(self, "Export Agent", "There are no saved agents to export.")
            return
        name, ok = QInputDialog.getItem(
            self, "Export Agent", "Agent:", [a.name for a in agents], 0, False
        )
        if not ok:
            return
        agent = next(a for a in agents if a.name == name)
        path = self.ask_save_file("Export Agent", f"{agent.name}.json", "JSON (*.json)")
        if not path:
            return
        try:
            Path(path).write_text(json.dumps(asdict(agent), indent=2), encoding="utf-8")
            QMessageBox.information(self, "Export Agent", f"Exported agent: {agent.name}")
        except OSError as error:
            self.show_error("Export Agent", str(error))

    def choose_theme(self) -> None:
        choice, ok = QInputDialog.getItem(
            self,
            "Theme",
            "Select application theme:",
            ["MyLoAI Dark", "System"],
            0 if self.config.ui.theme == "dark" else 1,
            False,
        )
        if not ok:
            return
        if choice == "MyLoAI Dark":
            self.config.ui.theme = "dark"
            self.setStyleSheet(dark_qss(self.config.ui.font_size))
        else:
            self.config.ui.theme = "system"
            self.setStyleSheet("")
        self.config.save()

    def show_shortcuts(self) -> None:
        self._show_text_dialog(
            "Keyboard Shortcuts",
            "Ctrl+N New Chat\nCtrl+O Open Chat\nCtrl+S Save\nCtrl+Q Exit\n"
            "Ctrl+Enter Send from composer\n"
            "Ctrl++ Increase text size\nCtrl+- Decrease text size\nCtrl+0 Reset text size\n"
            "Ctrl+Mouse Wheel Zoom text in/out",
        )

    def adjust_font_size(self, delta: int) -> None:
        current = self.config.ui.font_size or 12
        new_size = 12 if delta == 0 else max(10, min(28, current + delta))
        if new_size == current:
            return
        self.config.ui.font_size = new_size
        self.setStyleSheet(dark_qss(new_size))
        self.config.save()
        self.status.showMessage(f"Font size: {new_size}px")

    def toggle_all_docks(self) -> None:
        docks = self.findChildren(QDockWidget)
        visible = not all(d.isVisible() for d in docks)
        for d in docks:
            d.setVisible(visible)

    def reset_layout(self) -> None:
        for d in self.findChildren(QDockWidget):
            d.show()

    def inspect_api(self) -> None:
        self.show_request_dock()
        self.request_view.setFocus()
        if not self.request_view.toPlainText():
            self.status.showMessage("No request captured yet. Send a chat message to inspect it.")

    def _open_document(self, title: str, path: Path) -> None:
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as error:
            message = f"Unable to open {path}: {error}"
            LOG.error("%s: %s", title, message)
            QMessageBox.warning(self, title, message)
            return
        self._show_text_dialog(title, content[:20000])

    def open_bundled_document(self, title: str, name: str) -> None:
        self._open_document(title, bundled_document_path(name))

    def find_dock(self, title: str) -> QDockWidget | None:
        for dock in self.findChildren(QDockWidget):
            if dock.objectName() == title:
                return dock
        return None

    def about(self) -> None:
        QMessageBox.about(
            self,
            "About MyLoAI",
            "MyLoAI Control Center\n\nA desktop control center for local and remote LLM services.\n\n"
            f"Version {__version__}",
        )

    def diagnostics(self) -> None:
        mem = psutil.virtual_memory()
        self.append_console(
            f"CPU cores: {psutil.cpu_count()}\nRAM: {mem.available / 1024**3:.1f} GiB available / {mem.total / 1024**3:.1f} GiB total\nConfig: {self.config.file_path}\nData: {self.config.paths.data_dir}\nLogs: {self.config.paths.logs_dir}\n"
        )
        self.show_console_dock()

    def log(self, text: str) -> None:
        LOG.info(text)

    def _restore_state(self) -> None:
        if self.config.ui.geometry_hex:
            self.restoreGeometry(QByteArray.fromHex(self.config.ui.geometry_hex.encode()))
        if self.config.ui.state_hex:
            self.restoreState(QByteArray.fromHex(self.config.ui.state_hex.encode()))

    def _available_tools(self, agent) -> list[dict[str, Any]]:
        if agent is not None and agent.execution_policy == "no_tools":
            return []
        return self.tool_registry.specs()

    def _generate_with_tools(self, tab: ChatTab, backend, model: str, messages: list[ChatMessage], options: dict[str, Any]) -> None:
        """Non-streaming tool-use loop: the model may request tool calls, which are executed via the registry."""
        self.status.showMessage("generating (tool use enabled)")
        assistant = tab.session.messages[-1]

        async def work() -> str:
            conversation = list(messages)
            for _ in range(5):
                result = await backend.chat_collect(model, conversation, options)
                tool_calls = result.get("tool_calls") or []
                content = result.get("content", "")
                if not tool_calls:
                    return content
                conversation.append(
                    ChatMessage("assistant", content, metadata={"tool_calls": tool_calls})
                )
                for call in tool_calls:
                    try:
                        output = await self.tool_registry.call(call["name"], call.get("arguments") or {})
                    except Exception as exc:  # noqa: BLE001 - tool failures go back to the model
                        output = f"error: {exc}"
                    conversation.append(
                        ChatMessage(
                            "tool",
                            output,
                            name=call["name"],
                            metadata={"tool_call_id": call["id"]},
                        )
                    )
                self.status.showMessage(f"tool call: {', '.join(c['name'] for c in tool_calls)}")
            final = await backend.chat_collect(model, conversation, options)
            return final.get("content", "")

        task = AsyncTask(work)
        self._stream_owner_seq += 1
        owner = self._stream_owner_seq
        self.worker_refs.append(task)
        task.result.connect(lambda text, owner_id=owner: self._tool_result(tab, assistant, text, owner_id))
        task.error.connect(lambda error, owner_id=owner: self._stream_error(error, owner_id))
        task.start()

    def _tool_result(self, tab: ChatTab, msg: ChatMessage, text: str, owner_id: int) -> None:
        if self._active_stream_owner not in (None, owner_id):
            return
        self._active_stream_owner = None
        msg.content = text
        self.token_view.setPlainText(text)
        self.status.showMessage("idle")
        tab.set_generating(False)
        self.sessions.save(tab.session)
        self.refresh_sessions()
        tab.render(self.model_combo.currentText() or tab.session.model)

    def start_mcp_servers(self) -> None:
        async def work():
            return await self.mcp.start_enabled()

        task = AsyncTask(work)
        self.worker_refs.append(task)
        task.result.connect(self._mcp_started)
        task.error.connect(lambda e: self.log(f"MCP startup error: {e}"))
        task.start()

    def _mcp_started(self, results: dict) -> None:
        for name, value in results.items():
            if isinstance(value, str):
                self.log(f"MCP server '{name}' failed to start: {value}")
            else:
                self.log(f"MCP server '{name}' connected with {len(value)} tools")
        self._register_mcp_tools(results)

    def _register_mcp_tools(self, results: dict) -> None:
        self.tool_registry.unregister_source("mcp")
        for name, tools in results.items():
            if isinstance(tools, str):
                continue
            for tool in tools:
                tool_name = f"{name}__{tool.name}"
                self.tool_registry.register(
                    tool_name,
                    tool.description or f"MCP tool {tool.name} from server '{name}'",
                    tool.input_schema,
                    lambda _n=tool_name, _s=name: self._mcp_call(_s, _n),
                    source="mcp",
                )

    async def _mcp_call(self, server_name: str, tool_name: str, **arguments) -> str:
        return await self.mcp.call_tool(server_name, tool_name.split("__", 1)[1], arguments)

    def open_mcp_servers(self) -> None:
        if McpServersDialog(self.config, self.mcp, self).exec():
            self.start_mcp_servers()

    def list_mcp_tools(self) -> None:
        tools = self.tool_registry.specs()
        mcp_tools = [t for t in tools if t["function"]["name"].count("__")]
        self._show_text_dialog(
            "MCP Tools",
            json.dumps(mcp_tools, indent=2) if mcp_tools else "No MCP tools connected. Configure servers under MCP > MCP Servers...",
        )

    def show_model_browser(self) -> None:
        import psutil

        ram = psutil.virtual_memory().total / 1024**3
        recommended = (
            "gemma3:1b"
            if ram < 6
            else "qwen3.5:4b"
            if ram < 12
            else "mistral:7b"
            if ram < 24
            else "deepseek-r1:7b"
        )
        ModelBrowserDialog(self, recommended).exec()

    def refresh_skills(self) -> None:
        self.skill_list.clear()
        for skill in self.skills.list():
            self.skill_list.addItem(f"{skill.name} (v{skill.version})")
            self.skill_list.item(self.skill_list.count() - 1).setData(Qt.ItemDataRole.UserRole, skill.id)

    def apply_skill_item(self, item) -> None:
        tab = self.current_tab()
        skill = self.skills.get(item.data(Qt.ItemDataRole.UserRole))
        if tab and skill:
            apply_skill_to_session(tab.session, skill)
            self.render_tab(tab)
            self.sessions.save(tab.session)
            self.refresh_sessions()
            self.status.showMessage(f"Applied skill: {skill.name}")

    def apply_skill_dialog(self) -> None:
        skills = self.skills.list()
        if not skills:
            QMessageBox.information(self, "Apply Skill", "No skills yet. Create one in Skills > Skills Builder...")
            return
        name, ok = QInputDialog.getItem(
            self, "Apply Skill", "Skill:", [s.name for s in skills], 0, False
        )
        if ok:
            skill = next(s for s in skills if s.name == name)
            tab = self.current_tab()
            if tab:
                apply_skill_to_session(tab.session, skill)
                self.render_tab(tab)
                self.sessions.save(tab.session)
                self.refresh_sessions()

    def open_skill_builder(self) -> None:
        SkillBuilderDialog(self.skills, self).exec()
        self.refresh_skills()

    def import_skill(self) -> None:
        path = self.ask_open_file("Import Skill", "Markdown (*.md)")
        if path:
            skill = self.skills.import_file(Path(path))
            self.refresh_skills()
            QMessageBox.information(self, "Import Skill", f"Imported skill: {skill.name}")

    def export_skill(self) -> None:
        skills = self.skills.list()
        if not skills:
            QMessageBox.information(self, "Export Skill", "There are no saved skills to export.")
            return
        name, ok = QInputDialog.getItem(self, "Export Skill", "Skill:", [s.name for s in skills], 0, False)
        if not ok:
            return
        skill = next(s for s in skills if s.name == name)
        path = self.ask_save_file("Export Skill", f"{skill.name}.md", "Markdown (*.md)")
        if path:
            self.skills.export(skill, Path(path))
            QMessageBox.information(self, "Export Skill", f"Exported skill: {skill.name}")

    def ask_open_file(self, title: str, name_filter: str) -> str:
        path, _ = QFileDialog.getOpenFileName(self, title, filter=name_filter)
        return path

    def ask_save_file(self, title: str, default_name: str, name_filter: str) -> str:
        path, _ = QFileDialog.getSaveFileName(self, title, default_name, name_filter)
        return path

    def show_error(self, title: str, text: str) -> None:
        QMessageBox.critical(self, title, text)

    def show_info(self, title: str, text: str) -> None:
        QMessageBox.information(self, title, text)

    def ask_int(self, title: str, label: str, value: int, minimum: int, maximum: int) -> tuple[int, bool]:
        return QInputDialog.getInt(self, title, label, value, minimum, maximum)

    def ask_text(self, title: str, label: str, text: str = "") -> tuple[str, bool]:
        return QInputDialog.getText(self, title, label, text=text)

    def ask_multiline_text(self, title: str, label: str, text: str) -> tuple[str, bool]:
        return QInputDialog.getMultiLineText(self, title, label, text)

    def ask_confirm(self, title: str, text: str) -> bool:
        answer = QMessageBox.question(self, title, text)
        return answer == QMessageBox.StandardButton.Yes

    def clipboard_set(self, text: str) -> None:
        QApplication.clipboard().setText(text)

    def run_stream(self, iterator_factory, on_token, on_done, on_error) -> None:
        task = StreamTask(iterator_factory)
        self.worker_refs.append(task)
        task.token.connect(on_token)
        task.completed.connect(on_done)
        task.error.connect(on_error)
        task.start()

    def closeEvent(self, event) -> None:
        sys.stdout = self._original_stdout
        sys.stderr = self._original_stderr
        try:
            import asyncio

            asyncio.new_event_loop().run_until_complete(self.mcp.stop_all())
        except Exception:
            LOG.exception("MCP shutdown failed")
        if self._diagnostics_log_handler is not None:
            logging.getLogger().removeHandler(self._diagnostics_log_handler)
        if self.current_stream and self.current_stream.isRunning():
            self.current_stream.cancel()
        self._active_stream_owner = None
        self.current_stream = None

        # Do not let QThread instances outlive the application. A cancel flag only
        # asks a worker to stop; wait() guarantees the thread has actually exited
        # before Qt destroys the window/application.
        for worker in list(self.worker_refs):
            if not hasattr(worker, "isRunning") or not worker.isRunning():
                continue
            if hasattr(worker, "cancel"):
                worker.cancel()
            worker.requestInterruption()
            worker.wait()

        self.worker_refs.clear()
        self.config.ui.geometry_hex = bytes(self.saveGeometry().toHex()).decode()
        self.config.ui.state_hex = bytes(self.saveState().toHex()).decode()
        self.config.save()
        super().closeEvent(event)
