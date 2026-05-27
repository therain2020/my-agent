# therain2020-agent

**Add-First Agent Skeleton.** Bring your own LLM. Bring your own tools.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-123%20passed-brightgreen.svg)](tests/)
[![PyPI](https://img.shields.io/pypi/v/therain2020-agent.svg)](https://pypi.org/project/therain2020-agent/)

> English | 中文

Extract skills and tools from Claude Code / Codex / Gemini / Cursor / MCP. Plug in your own LLM API key. Run.

从 Claude Code / Codex / Gemini / Cursor / MCP 中提取 skill 和工具，接入你自己的 LLM API key，跑起来。

---

## Quick Start / 快速开始

```bash
# Install / 安装
pip install therain2020-agent

# Bring your own LLM / 接入你的 LLM
therain2020-agent provider add qwen --adapter custom \
  --api-key-env ALI_TONGYI_KEY \
  --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 \
  --model qwen-plus

# Discover tools from installed AI agents / 从已安装的 AI agent 发现工具
therain2020-agent add discover

# One-click migration / 一键迁移
therain2020-agent add from-claude-code

# Run / 执行
therain2020-agent run "your task"
```

---

## How It Works / 工作原理

```
therain2020-agent
    │
    ├── add      ★ import tools from external ecosystems
    │             从外部生态导入工具
    │
    ├── publish     package and share your own tools
    │              打包并分享你自建的工具
    │
    ├── run         execute tasks (TODO + Goal dual mode)
    │              执行任务（TODO 模式 + Goal 模式）
    │
    └── provider    manage LLM providers (Anthropic/OpenAI/DeepSeek/Custom)
                   管理 LLM 接入
```

## Core Architecture / 核心架构

```
Agent Core — K8s reconciliation loop / K8s 调节循环
  ├── Don't-Do Engine (iptables rule chains) / 非集引擎
  ├── Memory System (SQLite WAL + FTS5, semantic consolidation) / 记忆系统
  ├── Context Manager (virtual memory, LRU + zswap) / 上下文虚拟内存
  ├── Provider Pool (RAID failover + circuit breaker + cost routing) / 模型池
  ├── Tool Registry (udev model, import/mcp/subprocess) / 工具注册表
  ├── Credential Guard (kernel keyring) / 凭据守护
  └── Multi-Agent Bus (D-Bus + Unix pipe) / 多 Agent 总线
```

## Commands / 命令

```bash
# Provider / 模型接入
therain2020-agent provider add <name> --adapter anthropic|openai|deepseek|custom ...
therain2020-agent provider list
therain2020-agent provider test <name>
therain2020-agent provider remove <name>

# Add (headline) / 添加工具
therain2020-agent add discover             # Scan local AI agents / 扫描本地
therain2020-agent add search <keyword>     # Search (local + remote) / 搜索
therain2020-agent add from-claude-code     # One-click migration / 一键迁移
therain2020-agent add from-codex
therain2020-agent add from-gemini
therain2020-agent add from-cursor
therain2020-agent add skill <path>         # Import SKILL.md / 导入 skill
therain2020-agent add mcp <command>        # Import MCP server / 导入 MCP
therain2020-agent add list                 # List imported / 列出已导入
therain2020-agent add remove <name>        # Remove / 删除

# Publish / 发布
therain2020-agent publish init <name>      # Initialize package / 初始化包
therain2020-agent publish build            # Build .tar.gz / 打包
therain2020-agent publish verify           # Validate / 校验

# Run / 执行
therain2020-agent run "task"               # Auto-detect mode / 自动识别模式
therain2020-agent run "task" --mode goal   # Goal mode / 目标模式

# Info / 查询
therain2020-agent info tools               # List tools / 工具列表
therain2020-agent info dont-do             # List rules / 非集规则
therain2020-agent info config              # Show config / 查看配置
```

## Supported Import Sources / 支持的导入来源

| Source / 来源 | Format / 格式 | Product / 产物 |
|---|---|---|
| Claude Code | SKILL.md, .claude-plugin/, settings.json, CLAUDE.md | tool.md, role.md, dont-do, behavior_rules |
| Codex CLI | config.yaml, plugins/ | tool.md (MCP) |
| Gemini CLI | config.json, extensions/ | tool.md (MCP) |
| Cursor | .cursor/rules/, mcp.json | tool.md, behavior_rules |
| MCP Server | stdio / SSE / Streamable HTTP | tool.md (runtime=mcp) |
| Aider | CONVENTIONS.md | behavior_rules |

## Supported LLM Providers / 支持的模型

| Adapter / 适配器 | Usage / 用法 |
|---|---|
| Anthropic | `--adapter anthropic --api-key-env ANTHROPIC_API_KEY` |
| OpenAI | `--adapter openai --api-key-env OPENAI_API_KEY` |
| DeepSeek | `--adapter deepseek --api-key-env DEEPSEEK_API_KEY` |
| Qwen / Custom | `--adapter custom --base-url <URL> --api-key-env <ENV>` |

## Design / 设计

20 design topics, 80+ solution variants, 119 OS analogy mappings.

20 个设计话题，80+ 方案变体，119 条 OS 类比映射。

See / 详见: [agent-design/temp/README.md](../agent-design/temp/README.md)

## Tests / 测试

```bash
pytest tests/ -v    # 123 passed
```

## License / 许可

MIT
