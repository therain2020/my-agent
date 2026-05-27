# therain2020-agent

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-170%20passed-brightgreen.svg)](tests/)
[![PyPI](https://img.shields.io/pypi/v/therain2020-agent.svg)](https://pypi.org/project/therain2020-agent/)

[English](README.md)

一个闭环 AI Agent 框架。结构化观察、运行时安全拦截、纠正驱动学习、有证据的验证——用你自己的 API key。

---

## 为什么做这个

大多数 agent 框架就是 prompt 包装器。让 LLM 干活，祈祷它干对，然后说"完成了"。

这个不是。

- **观察**对象状态再动手。知道什么变了。
- **拦截**危险操作——不是在 prompt 里请求，是运行时强制规则。
- **学习**纠正。用户说一次"别这么干"，就再也不会犯。
- **验证**结果。对着验收标准逐条比对，带证据。不是猜 YES/NO。

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

## 怎么工作的

### Agent 循环

```
观察 → 分析 → 计划 → 执行 → 验证 → （循环，上限3次）
```

不是线性 prompt→response。是 Kubernetes 风格的对账循环——没达成目标就重来，直到达成或耗尽循环。

### 双模式

| 模式 | 适用场景 | 验证方式 |
|------|---------|---------|
| **TODO** | 有验收标准的任务列表 | 逐条比对执行记录中的证据 |
| **Goal** | 开放目标 | 重新观察对象状态，对比前后差异，返回置信度 |

### 对象模型

Agent 不只是执行命令。它维护操作对象的类型化模型——文件、数据库、git 仓库、服务。每个对象有 URI、类型和观察到的状态。行动前观察当前状态。行动后再次观察。验证时对比差异。

### 基于角色的观察

角色定义了*观察什么*和*怎么观察*。后端开发角色知道要观察文件系统、git 仓库和数据库对象。每种对象类型映射到特定的观察工具和操作工具。观察是有目标的——agent 只调用相关工具，而不是把整个工具箱塞给 LLM。

---

## 安全

三层。不是一层。

### 非集规则 — iptables 风格执行

```yaml
rules:
  - id: no-delete-system
    hook: [PRE_ACTION]
    match:
      object: file
      operation: delete_file
    action: REJECT
    message: "禁止删除系统文件"
```

规则在**运行时**三个钩子点触发：`PLAN`（执行前过滤步骤）、`PRE_ACTION`（拦截工具调用）、`POST_ACTION`（审计结果）。Prompt 注入是第一层。运行时执行是第二层。

### 纠正→规则闭环

用户中途发现问题？扔一个 YAML 文件到 `corrections/` 目录。Agent 会：
1. 解析纠正内容
2. 通过 LLM 生成 dont-do 规则
3. 持久化到规则目录
4. 带上约束重新规划

同样的错误不会犯两次。

### 凭据守护

API key 留在 agent 核心层。LLM 永远看不到。工具执行器在调用时注入。输出后扫描泄漏。

---

## 它会学习

### 情景记忆

每次任务运行都记录：用了什么工具、哪些对象变了、哪些非集规则触发了、成功还是失败。SQLite + WAL + FTS5 全文搜索。

### 语义记忆

LLM 驱动的记忆整合守护进程（类比 kswapd + LFS cleaner）定期将情景记录蒸馏为可复用的知识——偏好、事实、模式——带置信度评分。没有 LLM 时回退到规则提取。

### 对象状态历史

`get_object_history("file://src/main.py")` 返回任意对象在所有 episode 中的完整变化时间线。可以追溯几天内 agent 对某个文件的所有操作。

---

## 输出规范

系统级的格式约束注入到每一个 prompt：

```
<format_rules immutable="true">
  文件引用: path/to/file:line_number
  长回答: --- 分隔（总结 → 关键细节 → 完整说明）
  每个 function_call 必须有 <action_report>
</format_rules>
```

格式违规事后检测并标记。不是建议——是不可变规则。

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

## 架构

每个组件映射到 Linux 内核概念：

| 模块 | OS 类比 | 做什么 |
|------|--------|--------|
| `agent/core.py` | 进程调度器 | TODO/Goal 事件循环，3 次上限 |
| `agent/objects.py` | VFS inode | 类型化对象模型，状态快照 |
| `agent/role.py` | seccomp profile | 按对象类型定义观察和权限 |
| `agent/dont_do.py` | iptables netfilter | 钩子式规则引擎，首次匹配 |
| `agent/correction.py` | auditd + 规则生成 | 用户反馈→非集规则闭环 |
| `agent/memory.py` | ext4 日志 (WAL) | 情景+语义，FTS5 搜索 |
| `agent/consolidation.py` | kswapd + LFS cleaner | LLM 驱动情景→语义蒸馏 |
| `agent/prompt.py` | ELF loader | 结构化 prompt 组装+格式约束 |
| `agent/context.py` | MMU + 页面置换 | LRU 上下文窗口管理 |
| `agent/output_format.py` | syslog 格式器 | 文献引用、渐进式披露、行动报告 |
| `agent/providers/pool.py` | RAID 1 + 多路径 | Provider 故障转移+断路器 |
| `agent/providers/router.py` | ondemand cpufreq | 成本感知路由 |
| `agent/tools/supervisor.py` | systemd | MCP 进程生命周期管理 |
| `agent/tools/registry.py` | udev | 工具注册，按对象类型查找 |
| `agent/tools/adapters/` | 文件系统驱动 | 9 种生态适配器 |
| `agent/security/` | LSM + keyring | 凭据守护、prompt 注入防御 |

完整设计文档：`D:\GitHub\agent-design\temp\`。30 个设计话题，80+ 方案，119 条 OS 类比映射。

---

## 测试

```bash
pytest tests/ -v    # 170 passed
```

---

## 许可

MIT
