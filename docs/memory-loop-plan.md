# 记忆闭环方案：自愈 + 自进化

## 当前状态：记忆是断的

`Memory.log_episode()` 已经工作，数据写入 SQLite。但**从未有人读它**。

```
写入 ✓:  agent.py → Memory.log_episode() → episodic 表 → ✅ 有数据
读取 ✗:  session.py → _build_system() → ❌ 没有查记忆
修复 ✗:  错误发生后 → ❌ 没有提取规则 → ❌ 没有写入安全规则
```

三个缺失让"自愈"和"自进化"不可能：
1. **会话启动时**不加载历史上下文
2. **失败后**不提取教训
3. **教训**不变成下次的约束

## 方案：三步闭环

### Step 1: 上下文注入（~40 行，改动 session.py）

每次 `create_session()` 时，从 Memory 加载相关上下文注入系统提示。

```python
def _build_memory_context(memory: Memory, task: str) -> str:
    """Build context from past episodes and learned knowledge."""
    parts = []

    # 1. 语义记忆（固化知识：偏好、事实、模式）
    semantic = memory.search_semantic(task, limit=5)
    if semantic:
        parts.append("Learned knowledge:")
        for s in semantic:
            parts.append(f"  - [{s.type}] {s.content} (confidence: {s.confidence:.0%})")

    # 2. 最近经历（上次做了什么）
    recent = memory.get_recent(limit=3)
    if recent:
        parts.append("Recent activity:")
        for ep in recent:
            status = "ok" if ep.success else f"FAILED: {ep.error}"
            parts.append(f"  - {ep.task} → {status}")

    # 3. 活跃的安全规则（从语义记忆中筛选 type=rule）
    rules = memory.get_semantic_by_type("rule")
    if rules:
        parts.append("Learned safety rules:")
        for r in rules:
            parts.append(f"  - {r.content}")

    return "\n".join(parts) if parts else ""
```

注入位置：`agent.py` `_build_system()` 末尾。

### Step 2: 失败学习（~30 行，改动 agent.py）

每次任务失败后，用 LLM 分析错误，提取教训，写入语义记忆。

```python
async def _learn_from_failure(task: str, error: str, session: Session):
    """Ask LLM to extract a lesson from a failure."""
    # 仅当有错误时才触发
    if not error or "No LLM provider" in error:
        return

    prompt = (
        f"Task failed: {task}\n"
        f"Error: {error}\n\n"
        f"Extract one concrete lesson or safety rule from this failure. "
        f"Reply with JSON: {{\"type\": \"rule|fact|preference\", "
        f"\"content\": \"the lesson\"}}"
    )
    # 用当前 provider 调一次简单的 complete（不用工具）
    try:
        response = await session.provider.complete(
            messages=[{"role": "user", "content": prompt}],
            tools=None, max_tokens=200,
        )
        lesson = safe_parse_json(response.content)
        session.memory.upsert_semantic(SemanticEntry(
            type=lesson.get("type", "fact"),
            content=lesson.get("content", f"Task '{task}' failed: {error}"),
            confidence=0.7,
        ))
    except Exception:
        pass  # 学习失败不影响主流程
```

触发位置：`agent.py` `run()` 和 `run_stream()` 的 except 块中。

### Step 3: 自愈闭环（~20 行，改动 safety.py）

语义记忆中 `type=rule` 的条目自动注入为活跃安全规则。

`safety.py` 新增：

```python
def load_rules_from_memory(memory: Memory):
    """Load learned rules from semantic memory into the engine."""
    entries = memory.get_semantic_by_type("rule")
    for e in entries:
        if e.confidence >= 0.5:
            engine.add_rule(Rule(
                id=f"learned:{e.id}",
                description=e.content,
                hooks=[HookPoint.PRE_ACTION],
                match={"params": {}},  # 通用规则，匹配所有
                action=Verdict.WARN,
                message=e.content,
            ))
```

## 闭环效果

```
第 1 次会话：
  > 删除 /etc/hosts
  ✗ REJECTED（内置规则拦截）

第 2 次会话（重启后）：
  > 帮我清理临时文件
  [提示] Learned: "上次清理临时文件时误删了配置文件，应该先 list 再 rm"
  → Agent 先 list_files 再逐个删除

第 N 次会话：
  > 执行日常维护
  [提示] Recent: "清理临时文件" → ok, "更新配置" → ok
  [提示] Learned: 4 rules, 3 facts, 2 preferences
  → Agent 基于历史经验自动选择正确策略
```

## 改动范围

| 文件 | 变更 | 说明 |
|------|------|------|
| `session.py` | +3 行 | `create_session()` 加载记忆规则 |
| `agent.py` | +50 行 | `_build_memory_context()`, `_learn_from_failure()` |
| `safety.py` | +15 行 | `load_rules_from_memory()` |
| **合计** | **~70 行** | |

## 和 browser-harness 的对应关系

| browser-harness 机制 | therain2020 记忆闭环 |
|---------------------|---------------------|
| `agent_helpers.py` 被 Agent 编辑 | 语义记忆 → Agent 下次自动使用 |
| `domain-skills/*.md` | 最近经历 → 上下文注入 |
| Agent 写代码保存到磁盘 | `_learn_from_failure()` 提取教训 → 语义记忆 |
| 重启后 helpers 依然生效 | `_build_memory_context()` 加载历史 |

## 不做的

- 不做复杂的 consolidation daemon（旧项目的错误）
- 不做 LLM 驱动的语义提取循环（太重）
- 不做 pattern mining（和 consolidation 重叠）
- 不做 event sourcing 双写

只做：**写入 → 读取 → 失败 → 学习 → 下次更好**。
