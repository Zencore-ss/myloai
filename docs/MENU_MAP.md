# Menu Map

Date: 2026-11-22
Scope: `src/myloai/ui/main_window.py` — menus are built once at construction (`_build_menus`). There is no runtime patching layer. Status values: `implemented` (wired and working), per `docs/FEATURE_MATRIX.md`.

## Toolbar

| Control | Handler | Behavior | Status |
|---|---|---|---|
| New Chat / Save / Refresh Models / Parameters / Plugins / Prompt Manager | toolbar actions | core flows | implemented |
| Provider combo | `switch_provider` | persists active endpoint, retests connection | implemented |
| Model combo | `model_changed` | sets active chat model | implemented |
| Agent combo | `agent_changed` | applies selected agent profile to current chat | implemented |

## File

| Action | Handler | Behavior | Status |
|---|---|---|---|
| New Chat (Ctrl+N) | `new_chat` | new session tab, inherits agent/provider/model | implemented |
| Open Chat (Ctrl+O) | `chat_controller.open_chat_file` | import session JSON, open tab | implemented |
| Save (Ctrl+S) | `chat_controller.save_current` | persist session | implemented |
| Save As / Export / Import | `save_as` / `export_current` / `import_chat` | session file save/export/import | implemented |
| Exit (Ctrl+Q) | `close` | safe shutdown (workers, MCP, state) | implemented |

## Models

| Action | Handler | Behavior | Status |
|---|---|---|---|
| Browse & Pull Models... | `show_model_browser` | catalog browser with hardware-based recommendation | implemented |
| Pull / Push / Clone / Create / Delete | `model_controller` | async ops with progress + confirmation for delete | implemented |
| Modelfiles / Templates | `open_modelfile_editor` / `open_template_viewer` | Modelfile editor; model metadata viewer | implemented |

## Agents

| Action | Handler | Behavior | Status |
|---|---|---|---|
| Agent Builder... | `open_agent_builder` | create/edit agents incl. linked system prompt | implemented |
| Import Agent... / Export Agent... | `import_agent` / `export_agent` | JSON import/export of agent profiles | implemented |

## Skills

| Action | Handler | Behavior | Status |
|---|---|---|---|
| Skills Builder... | `open_skill_builder` | create/edit/delete/import/export SKILL.md skills | implemented |
| Apply Skill to Chat... | `apply_skill_dialog` | applies skill instructions as system prompt | implemented |
| Import Skill... / Export Skill... | `import_skill` / `export_skill` | SKILL.md import/export | implemented |

## Plugins

| Action | Handler | Behavior | Status |
|---|---|---|---|
| Plugin Manager | `open_plugins` | discover/trust/enable/disable/reload/uninstall | implemented |
| Install | `plugin_controller.install_plugin` | validates manifest, then copies into plugin dir | implemented |
| Reload | `plugin_controller.reload_plugins` | re-imports enabled plugins, cleans registrations | implemented |
| Plugin SDK Documentation | bundled `docs/PLUGIN_SDK.md` | works in source and frozen builds | implemented |

## MCP

| Action | Handler | Behavior | Status |
|---|---|---|---|
| MCP Servers... | `open_mcp_servers` | manage server processes (add/remove/enable/test/tools) | implemented |
| Reconnect MCP Servers | `start_mcp_servers` | starts enabled servers, registers their tools | implemented |
| List MCP Tools | `list_mcp_tools` | shows connected MCP tools | implemented |

## Settings

| Action | Handler | Behavior | Status |
|---|---|---|---|
| API Endpoints... | `open_endpoints` | provider profile CRUD, keyring credentials | implemented |
| AI Model Settings... | `open_parameters` | generation parameters + presets + reasoning mode | implemented |
| Prompt Manager... | `open_prompt_manager` | system prompt CRUD with version history | implemented |
| Theme... | `choose_theme` | persisted MyLoAI Dark / System choice | implemented |
| Keyboard Shortcuts | `show_shortcuts` | shortcut reference dialog | implemented |
| Default System Prompt... | `edit_default_system_prompt` | default prompt for new chats | implemented |
| Increase/Decrease/Reset Font Size | `adjust_font_size` | persisted UI font size (Ctrl++/Ctrl+-/Ctrl+0) | implemented |

## View

| Action | Handler | Behavior | Status |
|---|---|---|---|
| Toggle Panels / Reset Layout | `toggle_all_docks` / `reset_layout` | show/hide all docks; restore default layout | implemented |
| Models / Chat Sessions / System Prompts / Skills / Diagnostics / Request Viewer / Token Viewer panels | `_show_dock` / dock showers | raise the respective dock | implemented |

## Developer

| Action | Handler | Behavior | Status |
|---|---|---|---|
| Request Inspector | `inspect_api` | focuses the redacted outbound request | implemented |
| Diagnostics > Logs / Console / Operations / Request Viewer / Token Viewer | dock showers | diagnostics panels | implemented |

## Help

| Action | Handler | Behavior | Status |
|---|---|---|---|
| What is all this? (Learning Guide) | bundled `docs/LEARNING_GUIDE.md` | plain-language explanations of every feature | implemented |
| Documentation | bundled `packaging/USER_MANUAL.md` | user manual, works in source and frozen builds | implemented |
| About | `about` | product name + application version | implemented |
