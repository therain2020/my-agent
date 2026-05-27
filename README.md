# therain2020-agent

pip install therain2020-agent. Bring your own API key. Bring your own tools. That's it.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-123%20passed-brightgreen.svg)](tests/)
[![PyPI](https://img.shields.io/pypi/v/therain2020-agent.svg)](https://pypi.org/project/therain2020-agent/)

[中文](README.zh-CN.md)

---

## Why

I kept switching between Claude Code, Codex, and Gemini. Each had tools I wanted, each had skills I'd built up. Moving between them meant redoing work.

This project glues them together. You point it at a Claude Code skill, an MCP server, or a Cursor rule, and it eats it. Then you run it with whatever LLM you're paying for, not the one someone else picked for you.

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

## What it does

therain2020-agent has four jobs:

**add** — pull tools and rules from other AI agents. Claude Code skills, MCP servers, Cursor rules, plain CLAUDE.md files. It converts all of them into a format the agent can use.

**publish** — package up your own tools so other people can use them. One command builds a .tar.gz, another pushes it to GitHub Releases.

**run** — execute tasks. It figures out if you're giving it steps to follow or a goal to figure out, and handles both.

**provider** — manage which LLM you're using. Anthropic, OpenAI, DeepSeek, or anything OpenAI-compatible. Switch any time.

---

## Commands

```bash
# Provider
therain2020-agent provider add <name> --adapter anthropic|openai|deepseek|custom ...
therain2020-agent provider list
therain2020-agent provider test <name>
therain2020-agent provider remove <name>

# Add (this is the big one)
therain2020-agent add discover
therain2020-agent add search <keyword>
therain2020-agent add from-claude-code
therain2020-agent add from-codex
therain2020-agent add from-gemini
therain2020-agent add from-cursor
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
therain2020-agent run "task" --mode goal

# Info
therain2020-agent info tools
therain2020-agent info dont-do
therain2020-agent info config
```

---

## What it eats

| Source | What it takes | What you get |
|---|---|---|
| Claude Code | SKILL.md, .claude-plugin/, settings.json, CLAUDE.md | tool.md, role.md, dont-do rules |
| Codex CLI | config.yaml, plugins/ | tool.md (MCP) |
| Gemini CLI | config.json, extensions/ | tool.md (MCP) |
| Cursor | .cursor/rules/, mcp.json | tool.md, behavior rules |
| MCP Server | stdio, SSE, or Streamable HTTP | tool.md (runtime=mcp) |
| Aider | CONVENTIONS.md | behavior rules |

---

## Under the hood

It's not just a prompt wrapper. There's a SQLite-based memory system that remembers what tools you use, a dont-do engine that actually blocks dangerous operations (not just asks nicely), a credential guard that keeps API keys out of the LLM's line of sight, and a context manager that stops long conversations from blowing up the token window.

If you care about the design, there's a whole directory of architecture discussions in [agent-design/temp/](../agent-design/temp/). 20 topics, 80+ solution variants, 119 OS analogy mappings. Every component maps to something from Linux internals.

---

## Tests

```bash
pytest tests/ -v    # 123 passed
```

---

## License

MIT
