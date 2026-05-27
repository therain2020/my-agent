# therain2020-agent

pip install therain2020-agent. Bring your own API key. Bring your own tools. That's it.

pip install therain2020-agent。带上你自己的 API key。带上你自己找来的工具。完了。

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-123%20passed-brightgreen.svg)](tests/)
[![PyPI](https://img.shields.io/pypi/v/therain2020-agent.svg)](https://pypi.org/project/therain2020-agent/)

---

## Why / 为什么

I kept switching between Claude Code, Codex, and Gemini. Each had tools I wanted, each had skills I'd built up. Moving between them meant redoing work.

This project glues them together. You point it at a Claude Code skill, an MCP server, or a Cursor rule, and it eats it. Then you run it with whatever LLM you're paying for, not the one someone else picked for you.

我一直在 Claude Code、Codex、Gemini 之间来回切。每个上面都有我想要的工具，每个上面都有我攒的技能。换一个就得重来。

这个项目把它们粘在一起。你给它一个 Claude Code skill、一个 MCP server、或者一个 Cursor rule，它吃掉。然后用你自己付钱的 LLM 跑，而不是别人替你做决定的那个。

---

## Quick start / 快速开始

```bash
pip install therain2020-agent

therain2020-agent provider add qwen --adapter custom \
  --api-key-env ALI_TONGYI_KEY \
  --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 \
  --model qwen-plus

therain2020-agent add discover
therain2020-agent add from-claude-code
therain2020-agent run "修一下 login 那个 bug"
```

---

## What it does / 做什么的

therain2020-agent has four jobs:

therain2020-agent 做四件事：

**add** — pull tools and rules from other AI agents. Claude Code skills, MCP servers, Cursor rules, plain CLAUDE.md files. It converts all of them into a format the agent can use.

**add** — 从其他 AI agent 拉工具和规则。Claude Code skill、MCP server、Cursor rule、普通 CLAUDE.md 文件。全部转成 agent 能用的格式。

**publish** — package up your own tools so other people can use them. One command builds a .tar.gz, another pushes it to GitHub Releases.

**publish** — 把你自己的工具打包，让别人能用。一条命令打 .tar.gz，另一条推到 GitHub Releases。

**run** — execute tasks. It figures out if you're giving it steps to follow or a goal to figure out, and handles both.

**run** — 执行任务。它会自己判断你给的是待办步骤还是需要拆解的目标，两种都能处理。

**provider** — manage which LLM you're using. Anthropic, OpenAI, DeepSeek, or anything OpenAI-compatible. Switch any time.

**provider** — 管理你用的是哪个 LLM。Anthropic、OpenAI、DeepSeek、或者任何 OpenAI 兼容的接口。随时切换。

---

## Commands / 命令

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

## What it eats / 吃什么

| Source | What it takes | What you get |
|---|---|---|
| Claude Code | SKILL.md, .claude-plugin/, settings.json, CLAUDE.md | tool.md, role.md, dont-do rules |
| Codex CLI | config.yaml, plugins/ | tool.md (MCP) |
| Gemini CLI | config.json, extensions/ | tool.md (MCP) |
| Cursor | .cursor/rules/, mcp.json | tool.md, behavior rules |
| MCP Server | stdio, SSE, or Streamable HTTP | tool.md (runtime=mcp) |
| Aider | CONVENTIONS.md | behavior rules |

---

## Under the hood / 里面

It's not just a prompt wrapper. There's a SQLite-based memory system that remembers what tools you use, a dont-do engine that actually blocks dangerous operations (not just asks nicely), a credential guard that keeps API keys out of the LLM's line of sight, and a context manager that stops long conversations from blowing up the token window.

If you care about the design, there's a whole directory of architecture discussions in [agent-design/temp/](../agent-design/temp/). 20 topics, 80+ solution variants, 119 OS analogy mappings. Every component maps to something from Linux internals.

它不只是一个 prompt 包装器。里面有一个基于 SQLite 的记忆系统，记住你用什么工具；一个非集引擎，真的会阻止危险操作而不是客气地请求；一个凭据守护，保证 API key 不出现在 LLM 视线里；还有一个上下文管理器，防止长对话炸掉 token 窗口。

如果你关心设计，[agent-design/temp/](../agent-design/temp/) 里有完整的架构讨论。20 个话题，80+ 方案变体，119 条 OS 类比映射。每个组件都对应 Linux 内核的一个概念。

---

## Tests / 测试

```bash
pytest tests/ -v    # 123 passed
```

---

## License / 许可

MIT
