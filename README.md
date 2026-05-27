# therain2020-agent

Scan your Claude Code, Cursor, and Gemini installs. Pull their skills and MCP tools into one place. Run them with your own API key.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-123%20passed-brightgreen.svg)](tests/)
[![PyPI](https://img.shields.io/pypi/v/therain2020-agent.svg)](https://pypi.org/project/therain2020-agent/)

[中文](README.zh-CN.md)

---

## Why

I use Claude Code, Cursor, and Gemini. Each has skills I've accumulated, MCP servers I've configured. None of them talk to each other. Claude Code's tools are stuck in Claude Code. Cursor's rules don't leave Cursor.

This project scans your installed agents, finds everything you've set up, and converts it into a shared tool format. Then you run it all through whatever LLM you want. Claude, GPT, Qwen, DeepSeek, a local model — your call.

---

## Quick start

```bash
pip install therain2020-agent

therain2020-agent provider add qwen --adapter custom \
  --api-key-env ALI_TONGYI_KEY \
  --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 \
  --model qwen-plus

therain2020-agent add discover
therain2020-agent add from-claude-code
therain2020-agent run "fix the login bug"
```

---

## Three capabilities

### add — scan, adapt, import

Two things.

Built-in adapters for the major AI agent extension formats. Claude Code (skills, .claude-plugin/, settings.json, CLAUDE.md). Cursor (rules, mcp.json). Gemini CLI (extensions, config.json). Codex CLI (plugins, config.yaml). MCP protocol (stdio, SSE, Streamable HTTP). `add discover` scans your machine. `add from-claude-code` migrates everything in one command.

It's also an open tool interface. Every imported tool normalizes to `tool.md` — a documented format you can write yourself. Drop a `tool.md` and a Python script into the tools directory, done. The interface is symmetric: `add` pulls external tools in, `publish` packages your tools for distribution.

### publish — package and distribute

Build .tar.gz packages. Push to GitHub Releases. Anyone installs them with one command.

### provider — bring your own model

Your API key. Anthropic, OpenAI, DeepSeek, Qwen, any OpenAI-compatible endpoint. Failover keeps things running when a provider drops. An ondemand mode routes simple tasks to cheap models and complex ones to strong models.

---

## Commands

```bash
# Provider
therain2020-agent provider add <name> --adapter anthropic|openai|deepseek|custom ...
therain2020-agent provider list
therain2020-agent provider test <name>

# Add
therain2020-agent add discover
therain2020-agent add search <keyword>
therain2020-agent add from-claude-code
therain2020-agent add from-cursor
therain2020-agent add from-gemini
therain2020-agent add from-codex
therain2020-agent add skill <path>
therain2020-agent add mcp <command>
therain2020-agent add list
therain2020-agent add remove <name>

# Publish
therain2020-agent publish init <name>
therain2020-agent publish build
therain2020-agent publish verify

# Run
therain2020-agent run "task"
therain2020-agent run "goal" --mode goal

# Info
therain2020-agent info tools
therain2020-agent info dont-do
therain2020-agent info config
```

---

## Supported formats

| Source | Reads | Produces |
|---|---|---|
| Claude Code | SKILL.md, .claude-plugin/, settings.json, CLAUDE.md | tool.md, role.md, dont-do rules |
| Cursor | .cursor/rules/, mcp.json | tool.md, behavior rules |
| Gemini CLI | config.json, extensions/ | tool.md (MCP) |
| Codex CLI | config.yaml, plugins/ | tool.md (MCP) |
| MCP | stdio / SSE / Streamable HTTP | tool.md (runtime=mcp) |
| Aider | CONVENTIONS.md | behavior rules |
| Custom | tool.md + Python script | native, no conversion needed |

---

## Under the hood

Not just a prompt wrapper. SQLite-backed memory that learns from task history. A dont-do engine that blocks dangerous operations at runtime. Credentials stay in the agent core, invisible to the LLM. A virtual memory manager prevents context window exhaustion.

Full design docs at [agent-design/temp/](../agent-design/temp/). 20 topics, 80+ solution variants, 119 OS analogy mappings. Every component maps to a Linux kernel concept.

---

## Tests

```bash
pytest tests/ -v    # 123 passed
```

---

## License

MIT
