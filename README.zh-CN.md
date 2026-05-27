# therain2020-agent

把 Claude Code、Cursor、Gemini 里的 skill 和 MCP 工具，一键转成你自己的 agent 工具。带上自己的 API key 跑。

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-123%20passed-brightgreen.svg)](tests/)
[![PyPI](https://img.shields.io/pypi/v/therain2020-agent.svg)](https://pypi.org/project/therain2020-agent/)

[English](README.md)

---

## 为什么做这个

我同时在用 Claude Code、Cursor 和 Gemini。每个上面都攒了一堆 skill 和 MCP 工具，但它们是锁死的——Claude Code 的工具不能给 Cursor 用，Gemini 的配置也没法迁到别处。

这个项目就是解决这件事：扫描你已经装过的 AI agent，把它们的 skill、plugin、MCP 全部认出来，一键转成统一的 tool 格式。然后你用谁的 API key 跑都行。

不只适配御三家。国产的、任何 OpenAI 兼容接口的，一样接。

---

## 快速开始

```bash
pip install therain2020-agent

# 接你自己的 LLM
therain2020-agent provider add qwen --adapter custom \
  --api-key-env ALI_TONGYI_KEY \
  --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 \
  --model qwen-plus

# 扫描本机已装过的 agent，自动发现可迁移的工具
therain2020-agent add discover

# 一键迁移 Claude Code 的全部 skill 和 MCP
therain2020-agent add from-claude-code

# 跑
therain2020-agent run "修一下 login 那个 bug"
```

---

## 三个核心能力

### add — 扫描、适配、导入

做了两件事。

**第一，适配了市面上主流 AI agent 的扩展格式。** 目前内置支持的厂商：

- Claude Code（skill、plugin、settings.json、CLAUDE.md）
- Cursor（rules、mcp.json）
- Gemini CLI（extension、config.json）
- Codex CLI（plugin、config.yaml）
- MCP 协议（stdio、SSE、Streamable HTTP）

你本机装过哪些，`add discover` 自动扫描出来。`add from-claude-code` 一键全迁。`add skill <path>` 单独导入某个。

**第二，它提供了一个开放的、可扩展的工具接口。** 所有导入的工具统一转成 `tool.md` 格式。你要自己写工具也行，目录下放一个 `tool.md` 配一个 Python 脚本就行。导入和导出是对称的——你可以用 `add` 吃外面的，也可以用 `publish` 把你做的工具打包给别人用。

### publish — 打包、分发

把你写的工具打成标准的 .tar.gz 包，推到 GitHub Releases，别人就能装了。一条 build，一条 push。

### provider — 用自己的模型

你付钱的模型，你做主。Anthropic、OpenAI、DeepSeek、通义千问、任何 OpenAI 兼容接口都行。Provider 挂了自动切备用。嫌贵可以开省钱模式（ondemand），简单任务用小模型，复杂任务自动升到强的。

---

## 命令

```bash
# 模型接入
therain2020-agent provider add <name> --adapter anthropic|openai|deepseek|custom ...
therain2020-agent provider list
therain2020-agent provider test <name>

# 工具导入（核心）
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

# 工具发布
therain2020-agent publish init <name>
therain2020-agent publish build
therain2020-agent publish verify

# 执行
therain2020-agent run "任务描述"
therain2020-agent run "目标描述" --mode goal

# 查询
therain2020-agent info tools
therain2020-agent info dont-do
therain2020-agent info config
```

---

## 吃的格式

| 来源 | 能吃什么 | 转成什么 |
|---|---|---|
| Claude Code | SKILL.md, .claude-plugin/, settings.json, CLAUDE.md | tool.md, role.md, dont-do 规则 |
| Cursor | .cursor/rules/, mcp.json | tool.md, 行为规则 |
| Gemini CLI | config.json, extensions/ | tool.md (MCP) |
| Codex CLI | config.yaml, plugins/ | tool.md (MCP) |
| MCP 协议 | stdio / SSE / Streamable HTTP | tool.md (runtime=mcp) |
| Aider | CONVENTIONS.md | 行为规则 |
| 自定义 | 你自己写的 tool.md + Python 脚本 | 原生支持 |

---

## 里面

不只是一个 prompt 包装器。

记忆系统基于 SQLite，会记住你用什么工具，下次自动加载。非集引擎真的会拦截危险操作，不是在 prompt 里请求。凭据守护保证 API key 不出现在 LLM 视野里。上下文管理防止长对话撑爆 token 窗口。

设计文档在 [agent-design/temp/](../agent-design/temp/)。20 个话题，80 多个方案，119 条 OS 类比映射。每个组件都对应 Linux 内核的一个概念。

---

## 测试

```bash
pytest tests/ -v    # 123 passed
```

---

## 许可

MIT
