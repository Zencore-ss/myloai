# MyLoAI Control Center — Learning Guide

This guide explains, in plain language, what each part of MyLoAI Control Center is and how the pieces fit together. It is written for users who are still learning about local and remote AI — no prior knowledge is assumed. You can also open this from the app under **Help > What is all this? (Learning Guide)**.

## The big picture

An **LLM** (large language model) is a program that reads text and writes text back. MyLoAI is a **control center**: it does not contain a model itself. Instead, it connects to *providers* — services that run models — and lets you chat with them, manage their models, and extend the app with agents, skills, plugins, and MCP tools.

```
You  <-->  MyLoAI Control Center  <-->  Provider (Ollama, llama.cpp, OpenAI-compatible, ...)
                              <-->  MCP servers (extra tools the model can call)
```

## Providers and endpoints (Settings > API Endpoints...)

A **provider** is a kind of service that speaks a known API. MyLoAI supports:

- **Ollama** — the popular local model server (`http://localhost:11434` by default).
- **OpenAI-compatible** — any server that mimics the OpenAI chat API (many local and hosted services do).
- **llama.cpp** — the `llama-server` program from llama.cpp, which also speaks the OpenAI-compatible API.

An **endpoint** (called a "provider profile" in the app) is one concrete connection: a name, a type, a base URL, an optional API key, and a default model. API keys are stored in your operating system's credential store (keyring), never in the plain-text config file. Use the toolbar's **Provider** dropdown to switch between endpoints; the status bar shows whether the connection works and how fast it responded.

## Models (Models menu, Models panel)

A **model** is the actual AI you talk to (for example `qwen3.5:4b`). With a local provider you can **pull** (download), **push**, **clone**, **create** (from a Modelfile), and **delete** models. The **Model** dropdown in the toolbar selects which model the current chat uses. The Models panel shows each model's size, quantization, parameter count, and context length.

A **Modelfile** is a small recipe file (`FROM`, `PARAMETER`, `SYSTEM`, `TEMPLATE`, ...) that builds a custom model on top of an existing one. The Modelfiles editor can validate and preview it before building.

## Chat, sessions, and prompts

A **chat** is one conversation, shown as a tab. **Sessions** are saved chats — File > Save (Ctrl+S) stores the current chat; the Chat Sessions panel reopens them. You can also export a chat to Markdown, JSON, or plain text.

A **system prompt** steers the model's behavior for the whole conversation (for example "You are a concise coding assistant"). Manage reusable ones in the System Prompts panel / Prompt Manager; double-click one to apply it to the current chat. **Settings > Default System Prompt...** sets the prompt used by every new chat.

**Send** with the button or Ctrl+Enter. With **Stream** checked, the answer appears word by word; otherwise it arrives all at once. **Stop** cancels generation, **Regenerate/Retry** redo the last answer, and **Edit/Delete Message** change earlier turns.

## Parameters (Settings > AI Model Settings...)

**Parameters** are the dials of generation: temperature (creativity), top_k / top_p / min_p (sampling), repeat_penalty, num_predict (max tokens), seed, stop sequences, num_ctx (context window), and more. Presets let you save and reload a set of values. **Reasoning mode** can switch the model into a thinking mode (`think`) where supported.

## Agents (Agents menu, Agent toolbar dropdown)

An **agent** is a reusable profile: a name plus a preferred model, a linked system prompt, a reasoning mode, a behavior style, a memory mode, an execution policy for tools, and lists of tools/plugins. Selecting an agent in the **Agent** dropdown applies all of that to the current chat; new chats inherit the selected agent, and the choice is saved with the session.

## Skills (Skills menu, Skills panel)

A **skill** is a bundle of instructions (stored as a `SKILL.md` file with a small header) that you can apply to a chat in one click — for example "Code Reviewer" or "Explain like I'm five". Applying a skill sets the chat's system prompt to the skill's instructions. Create, edit, import, and export skills in **Skills > Skills Builder...**.

## Plugins (Plugins menu)

A **plugin** is a Python file that extends the app at runtime: it can register **tools** (callable helpers the model can invoke), **commands**, **chat interceptors** (they see and can modify the outgoing messages), **memory providers**, and custom **UI panels**. Because plugins run arbitrary code in-process, MyLoAI uses an explicit **trust** step: install a plugin (Plugins > Install validates it first), mark it trusted and enabled in the Plugin Manager, and reload when you change files. See the Plugin SDK documentation under Plugins > Plugin SDK Documentation.

## MCP — Model Context Protocol (MCP menu)

**MCP** is a standard way to plug external *tool servers* into an AI app. An MCP server is a small program that exposes tools — for example a filesystem tool, a web-search tool, or a database tool. In MyLoAI:

1. **MCP > MCP Servers...** — add a server by its command and arguments (typically `npx -y <some-mcp-server>`), enable it, and test the connection.
2. MyLoAI starts each enabled server as a subprocess and speaks MCP to it over stdio (JSON-RPC).
3. The server's tools are listed under **MCP > List MCP Tools** and registered as `server__tool` entries.
4. When a chat runs with tools available (and the agent's execution policy allows tools), the tools are sent to the model; if the model answers with tool calls, MyLoAI executes them through the MCP server and feeds the results back automatically (up to a small number of rounds).

## Developer tools (Developer menu)

- **Request Inspector / Request Viewer** — the exact JSON payload sent to the provider (the app's internal system prompt is redacted).
- **Token/Response Viewer** — the raw streamed response.
- **Diagnostics** — Logs (structured app logs), Console (captured stdout/stderr), and Operations (model pull/create/delete progress).

## View and Settings

Panels (Models, Chat Sessions, System Prompts, Skills, Diagnostics, Request/Token viewers) are dockable — toggle them in **View**. The theme (MyLoAI Dark or System), font size (Ctrl++/Ctrl+-/Ctrl+0), and window layout are remembered between runs.

## Where to go next

- Set up a provider: **Settings > API Endpoints...**
- Get a model: **Models > Browse & Pull Models...**
- Make the assistant yours: **Agents > Agent Builder...** and **Skills > Skills Builder...**
- Give the model superpowers: **MCP > MCP Servers...** and **Plugins > Plugin Manager**
