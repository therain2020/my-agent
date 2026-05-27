# therain2020-agent

pip install therain2020-agent。带上你自己的 API key。带上你自己找来的工具。完了。

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-123%20passed-brightgreen.svg)](tests/)
[![PyPI](https://img.shields.io/pypi/v/therain2020-agent.svg)](https://pypi.org/project/therain2020-agent/)

[English](README.md)

---

## 为什么做这个

我在 Claude Code、Codex、Gemini 之间来回切。每个上面都有我想要的工具，每个上面都有我攒的技能。换一个就得重来。

这个项目把它们粘在一起。你给它一个 Claude Code skill、一个 MCP server、或者一个 Cursor rule，它吃掉。然后用你自己付钱的 LLM 跑，而不是别人替你做决定的那个。

---

## 快速开始

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

## 做什么的

四件事：

**add** — 从其他 AI agent 拉工具和规则。Claude Code skill、MCP server、Cursor rule、普通 CLAUDE.md 文件。全部转成 agent 能用的格式。

**publish** — 把你自己的工具打包，让别人能用。一条命令打 .tar.gz，另一条推到 GitHub Releases。

**run** — 执行任务。它会自己判断你给的是待办步骤还是需要拆解的目标，两种都能处理。

**provider** — 管理你用的是哪个 LLM。Anthropic、OpenAI、DeepSeek、或者任何 OpenAI 兼容的接口。随时切换。

---

## 命令

```bash
# Provider
therain2020-agent provider add <name> --adapter anthropic|openai|deepseek|custom ...
therain2020-agent provider list
therain2020-agent provider test <name>
therain2020-agent provider remove <name>

# Add（重点）
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

## 吃什么

| 来源 | 吃什么 | 变成什么 |
|---|---|---|
| Claude Code | SKILL.md, .claude-plugin/, settings.json, CLAUDE.md | tool.md, role.md, dont-do 规则 |
| Codex CLI | config.yaml, plugins/ | tool.md (MCP) |
| Gemini CLI | config.json, extensions/ | tool.md (MCP) |
| Cursor | .cursor/rules/, mcp.json | tool.md, 行为规则 |
| MCP Server | stdio, SSE, Streamable HTTP | tool.md (runtime=mcp) |
| Aider | CONVENTIONS.md | 行为规则 |

---

## 里面有什么

它不只是一个 prompt 包装器。里面有一个基于 SQLite 的记忆系统，记住你用什么工具；一个非集引擎，真的会阻止危险操作而不是客气地请求；一个凭据守护，保证 API key 不出现在 LLM 视线里；还有一个上下文管理器，防止长对话炸掉 token 窗口。

如果你关心设计，[agent-design/temp/](../agent-design/temp/) 里有完整的架构讨论。20 个话题，80 多个方案变体，119 条 OS 类比映射。每个组件都对应 Linux 内核的一个概念。

---

## 测试

```bash
pytest tests/ -v    # 123 passed
```

---

## 许可

MIT
