# 记忆机制设计：支撑自进化的会话持久化

## Claude Code 记忆机制分析

```
~/.claude/projects/<project-hash>/memory/
├── MEMORY.md            ← 索引文件（每次会话自动加载，最多 200 行）
├── user-role.md         ← 用户角色、偏好
├── feedback-testing.md  ← 经验教训（"不要 mock 数据库，上次 mock 通过但生产挂了"）
├── project-phase3.md    ← 项目决策（"合并不冻结，2月15日后恢复"）
└── reference-grafana.md ← 外部引用（"oncall 看这个 dashboard"）
```

### 每条记忆 = 独立文件 + frontmatter

```markdown
---
name: feedback-testing
description: 集成测试必须连真实数据库，不要 mock — 生产和 mock 分歧导致过的故障
type: feedback
---

# 测试数据库策略

集成测试必须连真实数据库，不要 mock。
**原因**: 上次 mock 通过了但生产迁移失败，mock/prod 分歧没被发现。
**适用范围**: 所有涉及 SQL migration 的 PR。
```

### 核心机制

| 机制 | Claude Code 做法 |
|------|-----------------|
| **写入** | 重要事件发生时 → 写独立 .md 文件 → 更新 MEMORY.md 索引 |
| **加载** | 每次会话启动 → 读取 MEMORY.md（200 行限制）→ 按需读具体文件 |
| **恢复** | `/resume` → 加载上次会话的 memory 和对话上下文 |
| **过时检测** | 引用的文件/函数如被删除 → 更新或移除记忆 |
| **类型分类** | user / feedback / project / reference — 不同类型不同处理 |

## 我们需要的记忆机制

自进化 = Agent 能写工具 + Agent 能记住自己写过什么工具。

```
当前:
  Agent 写 tool.md → .generated/ → 重启后 ToolRegistry 加载 ✓
  但 Agent 不知道"我上次写了一个 image-convert 工具" ✗

需要:
  Agent 写 tool.md → .generated/ + memory/tools.md
  下次启动 → 加载 MEMORY.md → 看到 tools.md → 读到"你有 image-convert 工具"
            → ToolRegistry 同时加载 → 两端一致
```

### 目录结构

```
~/.therain2020-agent/
├── config.yaml          # provider 配置（已有）
├── memory.db            # SQLite 结构化数据（已有——episodic + semantic）
├── memory/              # 新增：Markdown 记忆文件
│   ├── MEMORY.md        # 索引（每次会话自动加载）
│   ├── tools.md         # 自进化：我创造了哪些工具
│   ├── sessions.md      # 会话历史摘要（支持 /resume）
│   ├── learnings.md     # 经验教训（从失败中学习）
│   └── preferences.md   # 用户偏好
└── .generated/          # Agent 生成的工具代码（已有）
    ├── image-convert.md
    └── image-convert.py
```

### MEMORY.md 格式（就是 Claude Code 的格式）

```markdown
- [tools](tools.md) — Agent 创建的工具清单（自动维护）
- [sessions](sessions.md) — 最近会话摘要（自动维护）
- [learnings](learnings.md) — 从失败和成功中学到的经验
- [preferences](preferences.md) — 用户偏好和习惯
```

### 四条数据流

```
流 1: 工具创建 → 记忆更新
   Agent 调 tool-writer → 写 .generated/{name}.py + .md
                       → MemoryManager.record_tool(name, description)
                       → 更新 memory/tools.md + MEMORY.md

流 2: 会话结束 → 记忆写入
   Agent.run() 结束 → MemoryManager.record_session(task, result, tools_used)
                    → 更新 memory/sessions.md + MEMORY.md
                    → SQLite 同时写入（已有）

流 3: 会话启动 → 记忆加载
   create_session() → MemoryManager.load_context()
                    → 读 MEMORY.md
                    → 读 tools.md（知道有什么工具）
                    → 读 sessions.md 最近 3 条（知道发生了什么）
                    → 读 learnings.md（知道什么该做什么不该做）
                    → 注入系统提示

流 4: 失败学习 → 经验提取
   Agent 任务失败 → MemoryManager.learn_from_failure(task, error)
                  → LLM 提取教训
                  → 追加到 memory/learnings.md
                  → 更新 MEMORY.md
```

## 实现设计

### `therain2020/memory_manager.py`（新增，~120 行）

```python
class MemoryManager:
    """Claude Code-style memory: MEMORY.md index + per-topic .md files."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.memory_dir = base_dir / "memory"
        self.index_path = self.memory_dir / "MEMORY.md"

    # —— 初始化 ——
    def ensure(self):
        """Create memory dir + MEMORY.md if not exists."""
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        if not self.index_path.exists():
            self.index_path.write_text("# Agent Memory\n\n")

    # —— 加载 ——
    def load_context(self) -> str:
        """Read MEMORY.md index + referenced files. Return context string."""
        if not self.index_path.exists():
            return ""
        index = self.index_path.read_text(encoding="utf-8")
        # Parse markdown links from index
        entries = re.findall(r'\[([^\]]+)\]\(([^)]+)\)', index)
        context = [index]  # Always include the index itself
        for title, path in entries[:8]:  # Cap at 8 files
            file_path = self.memory_dir / path
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                context.append(f"## {title}\n\n{content}")
        return "\n---\n".join(context)

    # —— 写入 ——
    def record_tool(self, name: str, description: str, code_summary: str):
        """Agent created a new tool → update tools.md + index."""
        ...

    def record_session(self, task: str, result_summary: str, tools: list[str]):
        """Session ended → update sessions.md + index."""
        ...

    def record_learning(self, type: str, content: str, source: str):
        """Learned from success/failure → update learnings.md + index."""
        ...

    # —— 内部 ——
    def _upsert_memory(self, filename: str, title: str,
                        frontmatter: dict, content: str):
        """Write a memory file with frontmatter. Update MEMORY.md index."""
        ...

    def _update_index(self, filename: str, title: str, hook: str):
        """Add/update pointer in MEMORY.md."""
        ...
```

### 改动范围

| 文件 | 变更 | 说明 |
|------|------|------|
| `therain2020/memory_manager.py` | 新增 ~120 行 | MEMORY.md + 文件的读写 |
| `therain2020/agent.py` | +20 行 | 会话结束时调 record_session / learn_from_failure |
| `therain2020/session.py` | +5 行 | 启动时调 load_context() 注入系统提示 |
| `therain2020/domain/tool_writer.py` | +5 行 | 工具创建后调 record_tool() |
| `tests/` | +40 行 | memory_manager 测试 |
| **合计** | **~190 行** | |

## 和 browser-harness 自进化的对应

| browser-harness | therain2020 记忆 + 自进化 |
|----------------|--------------------------|
| agent_helpers.py 被 Agent 编辑 | tool-writer 写 .generated/ → MemoryManager.record_tool() |
| 重启 import agent_helpers | ToolRegistry.scan_generated() + load_context() 双重加载 |
| domain-skills/*.md 持久化 | memory/learnings.md 持久化经验 |
| Agent 知道自己有哪些 helper | MEMORY.md 索引 + tools.md 清单 |
| 人手动看 agent_helpers.py | /resume 命令加载 sessions.md |
