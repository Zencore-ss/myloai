# MyLoAI Control Center

MyLoAI Control Center is a PySide6 desktop control center for local Ollama and remote/provider-compatible LLM backends.

## Repository layout

`src/` is the Python source-layout boundary. The application package lives at `src/myloai/` and is imported as `myloai`.

`tests/`, `packaging/`, and `docs/` contain the active test, release, and documentation surfaces.

The former `GR00T-User-706/locallama-gui` repository is the historical archive. The active repository is `GR00T-User-706/myloai`.

## Features

- Multi-provider LLM control center: Ollama, OpenAI-compatible, and llama.cpp server profiles with per-endpoint credentials stored in the OS keyring.
- Chat with streaming, sessions, system-prompt management, and reusable agent profiles (toolbar agent picker applies the agent's model, system prompt, and reasoning mode).
- Plugin SDK with static-manifest discovery, explicit trust, enable/disable/reload/uninstall lifecycle, and tool/command/chat-interceptor/memory-provider/UI-panel registration. See [docs/PLUGIN_SDK.md](docs/PLUGIN_SDK.md).

## Development entry point

`python -m myloai`

## Installed command

`myloai`

See [docs/BUILDING.md](docs/BUILDING.md) for production packaging and [docs/MIGRATION_STATUS.md](docs/MIGRATION_STATUS.md) for the current migration state.
