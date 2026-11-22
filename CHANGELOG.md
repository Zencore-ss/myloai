## [2.2.0] - 2026-11-22

### Added
- **MCP (Model Context Protocol) support**: manage stdio MCP servers (MCP > MCP Servers...), auto-start enabled servers, discover their tools, and let chats use them — tools are sent in chat payloads and tool calls are executed through a tool registry in a bounded loop (`core/mcp.py`, `core/tools.py`).
- **Skills**: skills are `SKILL.md` bundles managed in Skills > Skills Builder... and applied to a chat as its system prompt from the Skills menu or Skills dock (`SkillManager`).
- **Learning guide**: Help > "What is all this? (Learning Guide)" opens a bundled plain-language explanation of providers, models, agents, skills, plugins, MCP, parameters, and diagnostics (`docs/LEARNING_GUIDE.md`, bundled in frozen builds).
- New MCP and Skills menus; Skills dock panel; toolbar Agent dropdown (from 2.1.0 work).

### Changed
- **Menus are now built correctly in one place**: `MainWindow._build_menus()` owns the full menu structure and `ui/production_fixes.py` (the runtime patch layer) is deleted. Fixed in the base build: Settings "Model Settings" miswiring (now "AI Model Settings..."), fake Agents Import/Export, Developer "Request Inspector" being dropped, "Layout Presets" renamed to "Reset Layout", persisted Theme chooser, versioned About, and bundled-document paths that work in source and frozen builds.
- GUI framework boundary: `core/`, `backends/`, and `ui/controllers/` no longer import PySide6 — controllers use window `Protocol` ports; enforced by `tests/test_architecture.py`. PySide6 remains the default UI adapter under `ui/`.
- Config schema bumped to 3 with automatic migration adding `mcp_servers`.

### Fixed
- Zero remaining references to the former legacy `locallama` identity anywhere in the repo; repository URLs normalized to `Zencore-ss/myloai`.
- Legacy CI repaired: `active-ci.yml` now targets `src/**`; `release-packaging.yml` asserts the `myloai` distribution identity and wheel payload instead of the removed legacy name (it was failing on every PR).

### Documentation
- `docs/MENU_MAP.md` rewritten as a per-item intended-vs-current contract; `docs/ARCHITECTURE.md` documents the UI-adapter boundary; `docs/CONFIG_SCHEMA.md` documents schema v3; `docs/FEATURE_MATRIX.md` records MCP, Skills, menus, and the learning guide; `docs/LEARNING_GUIDE.md` added and bundled into PyInstaller/packaging payloads.

## [2.1.0] - 2026-11-22

### Added
- Agent picker in the main toolbar: selecting an agent applies its model, linked system prompt, and reasoning mode to the current chat; new chats inherit the selected agent, opened sessions restore their agent, and `ChatSession` persists `agent_id`.
- Agent Builder can now link an agent to a stored system prompt (`system_prompt_id`).
- Plugin SDK: `PluginContext.register_memory_provider()` helper; plugin tools, commands, chat interceptors, memory providers, and UI panels are tracked per plugin and removed on disable/reload, with rollback on failed activation.
- Plugin Manager dialog exposes trust/untrust and uninstall; Plugins > Install validates the static manifest before copying a plugin file.
- Tests for agent application, plugin registration cleanup, failed-activation rollback, and install validation.

### Fixed
- Plugin modules were imported under the obsolete legacy name prefix; now `myloai_user_plugin_`.
- Sample plugin referenced a nonexistent `main_window.terminal` attribute; it now uses the diagnostics `console_view`.

### Documentation
- Updated the Plugin SDK guide for memory providers, lifecycle cleanup, and install validation.
- Feature matrix now records agent execution integration and plugin install as implemented.

## [2.0.0] - 2026-11-08

### Changed
- Broke the former `legacy_pkg` Python namespace and established the conventional `src/myloai/` source-package layout.
- Updated the application, tests, console entry point, PyInstaller specification, Linux launchers, and packaging metadata to use the `myloai` Python namespace and active `Zencore-ss/myloai` repository.
- Replaced the old generated-icon build step with the canonical MyLoAI artwork assets and organized the brand-board reference under `docs/branding/`.
- Removed the duplicate production window-title override from `production_fixes.py`; the main window now owns its canonical title directly.
- Synchronized runtime version metadata with the project version `2.0.0`.

### Fixed
- Repaired imports and test monkeypatch targets broken by the intentional source-directory rename to `src/`.
- Repaired the PyInstaller source path and package discovery for the new `src/myloai/` layout.
- Repaired development launcher and desktop-entry installation paths that still targeted the removed legacy launcher/desktop-entry contract.
- Updated runtime application identity and log filename from the obsolete legacy identity to MyLoAI.

### Migration Status
- The previous `legacy-repo` repository and `legacy_pkg` namespace are historical only. The active repository is `Zencore-ss/myloai`.
- No user-data compatibility migration is being maintained during this development reset. Existing local configuration/data paths are intentionally outside the current compatibility contract.

### Documentation
- Added project-specific standards for the MyLoAI desktop application, provider behavior, configuration, plugins, user documentation, and supported package formats.

## [1.2.12] - 2026-09-24

### Fixed
- Restored the active `PromptManagerDialog` entry point from the MainWindow so the implemented prompt-management workflow is reachable.
- Added Prompt Manager access to the main toolbar and Settings menu, and refresh the System Prompts dock after prompt-management changes.
- Preserved unused MainWindow UI imports as commented placeholders instead of deleting them while the GUI remains untested.
- Restored the original user chat-role accent color `#a3be8c`.

### Documentation
- Kept Prompt Manager functionality aligned with the existing feature matrix and QA expectations.

## [1.2.11] - 2026-09-24

### Fixed
- Fixed light/system theme chat output so message blocks use the active Qt palette instead of a hard-coded dark background.
- Fixed the production packaging workflow so distribution validation derives the expected version from `pyproject.toml` instead of a stale hard-coded release value.
- Synchronized Linux Arch packaging, Linux man-page metadata, Windows installer fallback metadata, and the Linux packaging bundle manifest to `1.2.11`.
- Excluded `archive/**` from routine Ruff validation so historical code cannot fail active CI.

### Documentation
- Updated the versioning policy to require unified application version metadata across packaging and release validation.
- Resolved the documented production-packaging audit findings and updated the known-bugs tracker.

## [1.2.10] - 2026-09-22

### Fixed
- Fixed the first-run setup wizard syntax error so the backend connection callback is valid Python.
- Made the About dialog display the canonical application version.
- Fixed source-tree Plugin SDK documentation lookup while preserving the frozen-package documentation path.

### Documentation
- Recorded the verified fixes for the active code audit findings and the remaining authorization-required light-theme issue.
- Marked stale Diagnostics and Model Settings findings as fixed after verification against the current production menu wiring.

## [1.2.9] - 2026-09-21

### Fixed
- Restored valid `from __future__ import annotations` syntax in the Ollama and OpenAI-compatible backend modules so the active backend package can be parsed and imported.
- Synchronized the release-packaging workflow and platform packaging version references with application version `1.2.9`.

### Documentation
- Recorded the active production-packaging audit findings and their verification requirements.

## [1.2.8] - 2026-09-20

### Fixed
- Validated and normalized chat message roles/content before sending requests to Ollama or OpenAI-compatible backends.
- Added server response details to chat HTTP errors so a `400 Bad Request` now exposes the backend's actual error message instead of only the status code.
- Added regression tests for user prompt serialization, empty requests, and invalid message roles.

## [1.2.7] - 2026-09-20

### Documentation
- Corrected Markdown escaping in the production build guide so the documented commands and paths render correctly.

## [1.2.6] - 2026-09-20

### Fixed
- Corrected shell variable expansion in the canonical Linux production build script so it executes correctly under Bash.

## [1.2.5] - 2026-09-20

### Fixed
- Tracked the first-run setup connectivity worker in the main window worker registry so closing the application cannot destroy the wizard's active thread.

## [1.2.4] - 2026-09-20

### Fixed
- Made asynchronous worker cancellation interrupt the active asyncio task instead of waiting indefinitely for a network operation to return during application shutdown.

## [1.2.3] - 2026-09-20

### Fixed
- Added an offline AppImage build path that accepts a locally supplied AppImage runtime through `APPIMAGERUNTIME`.

### Documentation
- Documented the complete Linux production build prerequisites and offline AppImage runtime requirement.

## [1.2.2] - 2026-09-20

### Fixed
- Included keyring backend modules and package metadata in PyInstaller bundles so credential-store discovery is preserved in frozen builds.
- Synchronized the Windows installer fallback version and Linux man-page version with the application version.
- Clarified that the Arch package recipe uses system Python dependencies while the Debian, AppImage, Windows, and macOS artifacts bundle the runtime.

### Documentation
- Added a canonical Linux production build path and explicit build prerequisites for the generated `.deb` and AppImage artifacts.

## [1.2.1] - 2026-09-20

### Changed