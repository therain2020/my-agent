# 记忆机制 + 自进化 + 死代码审计 — 综合方案

## 一、记忆机制设计（Claude Code 模式）

### Claude Code 怎么做

```
~/.claude/projects/<hash>/memory/
├── MEMORY.md            ← 索引文件，每次会话自动加载（最多 200 行）
├── user-role.md         ← 用户角色
├── feedback-testing.md  ← 教训（"不要 mock 数据库"）
├── project-phase3.md    ← 项目决策
└── reference-grafana.md ← 外部引用
```

每条记忆 = 独立的 `.md` 文件 + YAML frontmatter + MEMORY.md 指针。

### 我们怎么做

```
~/.therain2020-agent/
├── config.yaml          # provider 配置（已有）
├── memory.db            # SQLite 结构化数据（已有）
├── memory/              # 新增：Markdown 记忆文件
│   ├── MEMORY.md        # 索引（自动加载）
│   ├── tools.md         # Agent 创造的工具清单
│   ├── sessions.md      # 会话历史摘要（支持 /resume）
│   ├── learnings.md     # 从失败中提取的经验
│   └── preferences.md   # 用户偏好
└── .generated/          # Agent 生成的工具代码
    ├── image-convert.md
    └── image-convert.py
```

**新增 `therain2020/memory_manager.py`**（~120 行）：

```python
class MemoryManager:
    # —— 加载（每次会话启动） ——
    def load_context() -> str
        # 读 MEMORY.md → 解析链接 → 读 tools.md + sessions.md + learnings.md
        # → 返回注入 prompt 的上下文字符串

    # —— 写入（事件触发） ——
    def record_tool(name, description, code_summary)
        # Agent 创建工具 → 更新 tools.md + MEMORY.md 索引
    def record_session(task, result, tools_used)
        # 会话结束 → 追加到 sessions.md（保留最近 10 条）+ 更新索引
    def record_learning(type, content, source)
        # 从成功/失败学习 → 追加到 learnings.md + 更新索引
```

**四条数据流**：

```
流 1: 工具创建 → tool-writer → MemoryManager.record_tool() → tools.md + MEMORY.md
流 2: 会话结束 → agent.run()  → MemoryManager.record_session() → sessions.md + SQLite
流 3: 会话启动 → create_session() → MemoryManager.load_context() → 注入系统 prompt
流 4: 失败学习 → agent 捕获错误 → MemoryManager.record_learning() → learnings.md
```

**和 Claude Code 的对应**：

| Claude Code | therain2020 |
|------------|-------------|
| `memory/` + `MEMORY.md` | `memory/` + `MEMORY.md`（相同格式） |
| 自动保存重要事件 | `record_session()`, `record_tool()`, `record_learning()` |
| 新会话自动加载 | `load_context()` → 注入 `_build_system()` |
| `/resume` | 读 `sessions.md` → Agent 知道上次做了什么 |
| 记忆类型：user/feedback/project/reference | tools/sessions/learnings/preferences |

---

## 二、优化后的自进化机制

### 完整流程

```
第 1 次会话：
  > 把图片转成 webp
  
  [思考] 现有工具不包含图片格式转换能力，我需要写一个工具...
  
  … tool-writer__write(
      name="image-convert",
      code="from PIL import Image; ...",
      description="Convert images between formats"
    )
  [✓] → Tool 'image-convert' created. Restart to load.
  
  → MemoryManager.record_tool("image-convert", "Convert images", "from PIL import Image")
  → 更新 memory/tools.md
  → 更新 MEMORY.md 索引

第 2 次会话（重启后）：
  → create_session()
  → MemoryManager.load_context()
     → 读 MEMORY.md → 发现 tools.md
     → 读 tools.md → "Agent 创造了 image-convert 工具"
     → 注入系统 prompt
  → ToolRegistry.scan_generated() → 加载 image-convert
  
  > 把这几张图都转成 webp
  … image-convert__run(path="a.png", format="webp")  ← 直接用！
  [✓]
```

### 自进化的三个层次

| 层次 | 机制 | 持久化 |
|------|------|--------|
| **L1: 工具自创** | `tool-writer` → `.generated/` + `MemoryManager.record_tool()` | `tools.md` + `.py` 文件 |
| **L2: 经验自积累** | 失败 → `MemoryManager.record_learning()` | `learnings.md` |
| **L3: 会话自恢复** | `/resume` → `MemoryManager.load_context()` | `sessions.md` |

---

## 三、死代码审计

### 总览

| 类别 | 数量 | 代码量 |
|------|------|--------|
| `agent/` 旧代码（新包不引用） | 44 个 .py 文件 | ~7900 行 |
| 旧测试（import agent/） | 31 个测试文件 | ~6000 行 |
| 旧数据目录 | 3 个（tools/, roles/, dont-do/） | ~200 行 |
| 新代码（therain2020/） | 16 个 .py 文件 | ~1700 行 |
| 新测试（import therain2020/） | 14 个测试文件 | ~1200 行 |

### 旧 agent/ 包 — 全部可以移除

**新包 `therain2020/` 零引用 `agent/`。** 旧 CLI（`therain2020-agent` 命令）已损坏——`agent/cli/providers.py` 在 v0.8.0 被删除。

### 可以安全删除的文件清单

#### agent/ 根目录（24 个文件）
```
agent/config.py              # 配置体系 → 已被 config.py + env vars 替代
agent/consolidation.py       # 记忆整合 daemon → 不用的模式
agent/context.py             # 上下文窗口管理 → 过度设计
agent/context_compressor.py  # 语义压缩 → 过度设计
agent/core.py                # 1770 行 god class → 已被 agent.py 替代
agent/correction.py          # 纠正系统
agent/dont_do.py             # 旧安全引擎 → 已被 safety.py 替代
agent/errors.py              # 20+ 异常类 → 过度设计
agent/eval.py                # 评估基准
agent/events.py              # 11 种事件类型 → 事件溯源（不需要）
agent/event_store.py         # 追加日志 + 快照 → 已被 memory.py 替代
agent/interrupt.py           # Ctrl+C 处理 → 无处引用
agent/memory.py              # 旧记忆 → 已被 memory.py 替代
agent/memory_migrations.py   # 旧 schema 迁移 → 不需要
agent/multi_agent.py         # 多 Agent → 不需要
agent/objects.py             # 本体论系统 → 轻量使用
agent/output_format.py       # XML 格式规则 → 不需要
agent/pattern_miner.py       # 模式挖掘 → 与 consolidation 重叠
agent/prompt.py              # XML prompt 组装 → 不需要
agent/publish.py             # 包发布 → 不核心
agent/retry.py               # 重试 → 内联
agent/role.py                # 角色系统 → 不需要
agent/search.py              # 搜索引擎抽象
agent/streaming.py           # 旧流式 → 已被 cli/streaming.py 替代
```

#### agent/cli/（7 个文件）
```
agent/cli/__init__.py, __main__.py, autodetect.py
agent/cli/display.py, repl.py, run.py
agent/cli/tui/__init__.py, app.py
```

#### agent/providers/（8 个文件）
```
__init__.py, anthropic.py, capability.py, custom.py
deepseek.py, openai.py, pool.py, router.py
```

#### agent/tools/（7 个文件）
```
editor.py, evolution.py, executor.py, loader.py
mcp_transports.py, registry.py, supervisor.py
```

#### agent/tools/browser/（3 个文件）
```
daemon.py, helpers.py, user_helpers.py
```

#### agent/tools/adapters/（12 个文件）
```
browser_harness.py, claude_plugin.py, claude_settings.py
claude_skill.py, codex.py, cursor.py, gemini.py
mcp.py, plain_text.py, remote_search.py, scanner.py, validator.py
```

#### agent/security/（2 个文件）
```
__init__.py, credentials.py
```

#### agent/skills/（4 个文件）
```
lifecycle.py, models.py, pii_gate.py, repository.py
```

#### 旧数据目录
```
tools/           # 旧工具系统数据
roles/           # 空目录
dont-do/         # 旧安全引擎数据
```

#### 旧测试（31 个文件）
```
tests/test_autodetect.py, test_browser_harness.py
tests/test_context_compressor.py, test_evolution.py
tests/test_repl.py, test_skills.py, test_verification.py
tests/integration/test_e2e.py
tests/unit/test_adapters.py, test_capability.py
tests/unit/test_consolidation.py, test_context.py
tests/unit/test_correction.py, test_cost_router.py
tests/unit/test_credentials.py, test_dont_do.py
tests/unit/test_errors.py, test_eval.py
tests/unit/test_event_sourcing.py, test_fitness.py
tests/unit/test_mcp_transports.py, test_memory.py
tests/unit/test_multi_agent.py, test_objects.py
tests/unit/test_output_format.py, test_pattern_miner.py
tests/unit/test_provider_pool.py, test_publish.py
tests/unit/test_registry.py, test_search.py
tests/unit/test_security.py, test_tool_loader.py
```

### 需要保留的

| 保留 | 说明 |
|------|------|
| `therain2020/` | 新核心包（16 文件，~1700 行） |
| `tests/test_agent.py` 等 14 个新测试 | |
| `agent/__init__.py` | 仅版本号（如仍需 `import agent; agent.__version__`） |
| `pyproject.toml` | 移除旧入口点后保留 |
| `docs/` | 所有方案文档 |
| `scripts/` | 构建脚本 |

---

## 四、实施计划

| 阶段 | 内容 | PR |
|------|------|-----|
| **Step 1** | 新增 `memory_manager.py` + 记忆上下文注入 | #1 |
| **Step 2** | 新增 `tool-writer` 工具 + 记忆联动 | #2 |
| **Step 3** | 修复 `_learn_from_failure()` + 经验提取 | #3 |
| **Step 4** | 移除所有死代码（44 旧文件 + 31 旧测试 + 3 旧目录） | #4 |
| **Step 5** | 更新 pyproject.toml、README、CLAUDE.md | #5 |
