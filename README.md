# therain2020-agent

**Add-First Agent 骨架。** Bring your own LLM. Bring your own tools.

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-51%20passed-brightgreen.svg)](tests/)

## 一句话

从 Claude Code / Codex / Gemini / Cursor / MCP 中提取 skill 和工具，接入你自己的 LLM API key，跑起来。

## 快速开始

```bash
# 1. 安装
pip install -e .

# 2. 接入 LLM
therain2020-agent provider add anthropic --adapter anthropic --api-key-env ANTHROPIC_API_KEY --model claude-sonnet-4-6
# 或者用通义千问 (OpenAI 兼容)
therain2020-agent provider add qwen --adapter custom --api-key-env ALI_TONGYI_KEY --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 --model qwen-plus

# 3. 发现本机已有的 agent 生态
therain2020-agent add discover

# 4. 一键迁移
therain2020-agent add from-claude-code

# 5. 跑起来
therain2020-agent run "用 git 工具提交最近的改动"
```

## 核心命令

### LLM Provider
```bash
therain2020-agent provider add <name> --adapter anthropic|openai|deepseek|custom ...
therain2020-agent provider list
therain2020-agent provider test <name>
therain2020-agent provider remove <name>
```

### 添加工具 (headline feature)
```bash
# 发现
therain2020-agent add discover             # 扫描本机安装的所有 AI agent
therain2020-agent add search <keyword>     # 搜索可导入项

# 一键迁移
therain2020-agent add from-claude-code     # 迁移 Claude Code 全部内容
therain2020-agent add from-codex           # 迁移 Codex CLI
therain2020-agent add from-gemini          # 迁移 Gemini CLI
therain2020-agent add from-cursor          # 迁移 Cursor

# 单项导入
therain2020-agent add skill <path>         # 导入 SKILL.md
therain2020-agent add plugin <path>        # 导入 .claude-plugin/
therain2020-agent add mcp <command>        # 导入 MCP Server
therain2020-agent add settings <path>      # 导入 settings.json
therain2020-agent add claude-md <path>     # 导入 CLAUDE.md
therain2020-agent add cursor-rules <dir>   # 导入 Cursor rules

# 管理
therain2020-agent add list                 # 列出已导入
therain2020-agent add info <name>          # 查看详情
therain2020-agent add remove <name>        # 删除
therain2020-agent add update <name>        # 重新导入
```

### 执行任务
```bash
therain2020-agent run "你的任务描述"        # TODO 模式 (Phase 1)
```

### 查询
```bash
therain2020-agent info tools               # 列出所有工具
therain2020-agent info dont-do             # 列出非集规则
therain2020-agent info config              # 查看配置
therain2020-agent status show              # 会话状态
```

## 支持的 LLM Provider

| Adapter | 使用方式 |
|---|---|
| Anthropic | `--adapter anthropic --api-key-env ANTHROPIC_API_KEY` |
| OpenAI | `--adapter openai --api-key-env OPENAI_API_KEY` |
| DeepSeek | `--adapter deepseek --api-key-env DEEPSEEK_API_KEY` |
| Qwen / 自定义 | `--adapter custom --base-url <URL> --api-key-env <ENV>` |

## 支持的导入来源

| 来源 | 格式 | 转换产物 |
|---|---|---|
| Claude Code | SKILL.md, .claude-plugin/, settings.json, CLAUDE.md | tool.md, role.md, dont-do, behavior_rules |
| Codex CLI | config.yaml, plugins/ | tool.md (MCP) |
| Gemini CLI | config.json, extensions/ | tool.md (MCP) |
| Cursor | .cursor/rules/, mcp.json | tool.md, behavior_rules |
| MCP Server | stdio / SSE / Streamable HTTP | tool.md (runtime=mcp) |
| Aider | CONVENTIONS.md | behavior_rules |

## 项目结构

```
therain2020-agent/
├── agent/
│   ├── cli/              CLI (Click) — add/providers/run/info/status
│   ├── core.py           Agent 事件循环
│   ├── config.py         YAML 配置
│   ├── providers/        LLM HAL (Anthropic/OpenAI/DeepSeek/Custom)
│   ├── tools/
│   │   ├── adapters/     外部生态适配器 (9 个)
│   │   ├── loader.py     tool.md 解析
│   │   ├── registry.py   工具注册表
│   │   ├── executor.py   工具执行器
│   │   └── supervisor.py MCP 进程管理
│   ├── security.py       非集 (dont-do rules)
│   ├── memory.py         情景记忆
│   ├── prompt.py         ELF XML 组装
│   ├── interrupt.py      中断处理
│   └── retry.py          指数退避
├── tools/file-system/    内置文件系统工具
├── tools/.generated/     导入工具
├── dont-do/              非集规则
├── tests/                51 个测试
└── examples/             示例配置和 skill
```

## 设计

20 个设计话题 + 80+ 方案 + 119 条 OS 类比映射。

详见 [agent-design/temp/README.md](../agent-design/temp/README.md)

## 测试

```bash
pytest tests/ -v    # 51 passed
```

## License

MIT
