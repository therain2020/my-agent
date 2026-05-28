# therain2020-agent

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-247%20passed-brightgreen.svg)](tests/)
[![PyPI](https://img.shields.io/pypi/v/therain2020-agent.svg)](https://pypi.org/project/therain2020-agent/)

[English](README.md)

一个闭环 AI Agent 框架。结构化观察、运行时安全拦截、纠正驱动学习、事件溯源记忆、能力感知路由、自我教学模式挖掘——用你自己的 API key。

---

## 为什么做这个

大多数 agent 框架就是 prompt 包装器。让 LLM 干活，祈祷它干对，然后说"完成了"。

这个不是。

- **观察**对象状态再动手。知道什么变了。
- **拦截**危险操作——不是在 prompt 里请求，是运行时强制规则。上下文路径感知确保规则真正生效。
- **学习**纠正。用户说一次"别这么干"，就再也不会犯。Agent 也能**自我教学**——发现跨任务的重复模式，主动提议规则。
- **验证**结果。重新观察对象终态，计算 diff。不是猜 YES/NO。
- **记忆**用事件溯源。每次观察、每次工具调用、每次纠正、每次验证都是不可变事件。完整审计。可重放任意任务。

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

## 工作原理

### Agent 循环

```
观察 → 分析 → 规划 → 执行 → 验证 → (循环, 最多 3 次)
```

不是线性 prompt→response。是 K8s 风格的对账循环——反复尝试直到目标达成或循环耗尽。

### 两种执行模式

| 模式 | 使用场景 | 验证方式 |
|------|---------|---------|
| **TODO** | 带验收标准的任务列表 | 分析 TODO 清晰度, 缺失标准主动询问, 逐条比对验收标准 |
| **Goal** | 开放式目标 | 重新观察对象状态, 计算前后 diff, 输出置信度 |

### Ontology 对象模型 (Data + Logic + Actions + Relations)

Agent 看到的不是裸数据。每个对象携带：

- **Data** — 当前状态快照 (size, branch, exists)
- **Logic** — 约束条件 ("不能含硬编码密钥", "禁止写系统路径")
- **Actions** — 可用操作及其前置条件和副作用
- **Relations** — 对象关系 (tested_by, imports, depends_on)

这些信息注入 planning prompt。LLM 看到的不是"文件 X 大小 100"，而是"文件 X 有什么约束、关联了哪些文件、能用什么工具"。

### Event Sourcing 记忆

每次 Agent 操作都是追加到 SQLite WAL 日志的不可变事件：

```
GoalStarted → ObjectObserved → PlanGenerated → ToolCalled → ToolResult
→ CorrectionApplied → RuleAdded → GoalVerified → GoalCompleted
```

11 种事件类型。完整重放。每 50 个事件做一次状态快照。安全关键事件（规则变更）同步可见；观测事件最终一致。

### 角色化观察

角色定义*观察什么*和*怎么观察*。每个角色声明关注对象类型、观察工具、操作工具、禁止操作、行为规则。观察有针对性——Agent 只调用相关工具，不把所有工具都扔给 LLM。

---

## 安全

三层，不是一层。

### Dont-Do 规则 — iptables 风格拦截

```yaml
rules:
  - id: no-delete-system
    hook: [PRE_ACTION]
    match:
      object: file
      operation: delete_file
      path_in_restricted: true
    action: REJECT
    message: "禁止删除系统文件"
```

规则在**运行时**三个 hook 点生效：`PLAN`（过滤计划步骤）、`PRE_ACTION`（阻止工具调用）、`POST_ACTION`（审计结果）。上下文**路径感知**——Agent 自动从 params 提取路径并设置 `path_in_restricted`/`path_matches`。

### 信任边界 (STRIDE)

每次工具调用都跨越信任边界（LLM → Tool Executor）。安全模型映射到 STRIDE 威胁建模：

| 威胁 | 缓解措施 |
|------|---------|
| Spoofing | Role + DontDoEngine 双重验证 |
| Tampering | PRE_ACTION 路径感知参数检查 |
| Repudiation | Event Sourcing 完整审计溯源 |
| Info Disclosure | POST_ACTION 结果过滤 + 输出脱敏 |
| Denial of Service | max_iterations 限制 + InterruptHandler |
| Elevation | Role 工具白名单 |

### 纠正→规则闭环

用户发现执行有问题？往 `corrections/` 目录扔个 YAML。Agent 通过 LLM 生成 dont-do 规则、持久化、带新约束重规划。同一个错误不会犯两次。

### 架构适应度函数

23 个自动化测试每次 CI 都验证架构特性——不只是"代码编译了吗"，而是"非集规则有效吗"、"Agent 在角色范围内吗"、"上下文使用高效吗"。

---

## 智能

### 能力感知路由

跟踪每模型、每任务类型的成功率。"数据迁移"任务时，路由器知道 haiku 在数据库任务上成功率只有 60%——自动升级到 sonnet。新任务类型则回退到成本路由。基于 Karpathy 的"锯齿状能力边界"概念。

### 自我教学模式挖掘

Agent 跨任务发现模式：

- **错误聚类** — 同类任务反复出现同一错误 → 规则提案
- **纠正聚类** — 同一纠正反复出现 → 技能提案
- **失败聚类** — 同一验证失败反复出现 → 计划模板提示

Agent **提议**。人类**批准**（Taste 原则）。

---

## 记忆

### 情景记忆

每次任务运行都被记录：用了什么工具、对象怎么变、非集规则怎么触发、成功还是失败。SQLite WAL + 版本化 schema 迁移。

### 语义记忆

LLM 驱动的整合守护进程（kswapd + LFS cleaner）定期蒸馏 episode 为可复用知识——偏好、事实、模式——带可信度评分。

### 对象历史

`get_object_history("file://src/main.py")` 返回该对象在所有 episode 中的完整变更时间线。

### 事件重放

`event_store.replay_task(task_id)` 重构完整执行时间线——每次观察、每次工具调用、每次验证——按插入顺序还原。

---

## 输出纪律

系统级格式约束注入每个 prompt：

```
<format_rules immutable="true">
  文件引用: path/to/file:line_number
  长回复: --- 分隔 (总结 → 关键细节 → 完整说明)
  每个 function_call 必须有 <action_report>
</format_rules>
```

事后检测格式违规。不是建议——是不可变规则。

---

## 命令

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

## 支持的格式

| 来源 | 读取 | 生成 |
|---|---|---|
| Claude Code | SKILL.md, .claude-plugin/, settings.json, CLAUDE.md | tool.md, role.md, dont-do 规则 |
| Cursor | .cursor/rules/, mcp.json | tool.md, 行为规则 |
| Gemini CLI | config.json, extensions/ | tool.md (MCP) |
| Codex CLI | config.yaml, plugins/ | tool.md (MCP) |
| MCP | stdio / SSE / Streamable HTTP | tool.md (runtime=mcp) |
| Aider | CONVENTIONS.md | 行为规则 |
| Custom | tool.md + Python 脚本 | 原生，无需转换 |

---

## 架构

每个模块映射到 Linux 内核概念：

| 模块 | OS 类比 | 职责 |
|--------|-----------|------|
| `agent/core.py` | Process scheduler | TODO/Goal 事件循环, dont-do 上下文增强, 能力记录 |
| `agent/objects.py` | VFS inode + xattrs | Ontology 对象模型 (Data+Logic+Actions+Relations) |
| `agent/role.py` | seccomp profile | 结构化角色, 约束/动作生成 |
| `agent/dont_do.py` | iptables netfilter | Hook 规则引擎, first-match 语义 |
| `agent/correction.py` | auditd + rule gen | 用户反馈→dont-do 规则闭环 |
| `agent/events.py` | journald | 11 种事件类型, Event Sourcing 记忆 |
| `agent/event_store.py` | ext4 journal | Append-only event log, snapshot, 进程内 pub/sub |
| `agent/memory.py` | ext4 journal (WAL) | 情景 + 语义，FTS5 检索 |
| `agent/consolidation.py` | kswapd + LFS cleaner | LLM 驱动的记忆整合 |
| `agent/pattern_miner.py` | KSM (same-page merging) | 跨 episode 模式发现, Agent 自我教学 |
| `agent/memory_migrations.py` | Alembic-style | 版本化 schema 迁移追踪 |
| `agent/prompt.py` | ELF loader | 结构化 prompt 组装 + ontology 上下文注入 |
| `agent/context.py` | MMU + page replacement | LRU 上下文窗口管理 |
| `agent/output_format.py` | syslog format enforcer | 引用规则, 渐进披露, 行动报告 |
| `agent/providers/pool.py` | RAID 1 + multipath | Provider 故障转移, 熔断器 |
| `agent/providers/router.py` | ondemand cpufreq + NUMA | 成本 + 能力感知模型路由 |
| `agent/providers/capability.py` | CPU affinity | 锯齿状能力画像 |
| `agent/tools/supervisor.py` | systemd | MCP 进程生命周期管理 |
| `agent/tools/registry.py` | udev | 工具注册, 按对象类型查找 |
| `agent/tools/adapters/` | filesystem drivers | 9 个生态适配器 |
| `agent/security/` | LSM + keyring | 凭据守卫, prompt 注入防御 |

完整设计文档在 `D:\GitHub\agent-design\temp\`。30 个设计主题, 80+ 方案变体, 119 个 OS 类比映射。

---

## 测试

```bash
pytest tests/ -v    # 247 通过
```

含 23 个架构适应度函数（Plan 完整性, 非集有效性+STRIDE, 角色合规, 上下文效率, 输出格式合规）。

---

## License

MIT
