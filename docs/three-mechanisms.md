# 三机制协同设计：自愈 + 自进化 + 记忆

## 当前问题

1. Agent 遇到 "browser-harness not installed" → 写 shell 脚本到 /tmp → 无法执行 → 废操作
2. 用户看不到 Agent 在做什么、为什么这么做
3. 三个机制各自存在但不协同

## 机制一：自进化

### 定义
Agent 遇到现有工具无法解决的问题时，用 `tool-writer` 创造新工具。新工具持久化到 `.generated/`，下次自动加载。

### 缺少什么
Agent 缺少**系统级执行能力**。没有 `shell`/`exec` 工具，只能操作文件不能运行命令。自进化缺少原材料。

### 设计
**新增 `shell` 工具** — 让 Agent 能执行系统命令：

```
domain/
├── shell.py          # run(command, timeout) → (stdout, stderr, exit_code)
└── tools/
    └── shell.md      # 工具注册
```

- 仅允许非交互式命令
- 30 秒超时
- 不继承 shell 环境（每次调用独立）
- 输出截断到 5000 字符防止上下文污染

有了 shell，Agent 可以：
- `pip install browser-harness`
- `browser-harness <<'PY'...PY` 启动 daemon
- 运行任意诊断命令

## 机制二：自愈

### 定义
Agent 遇到工具报错时，**自动诊断 → 修复 → 重试**。不道歉不放弃。

### 缺少什么
当前 `agent.py` 的事件循环没有重试逻辑。工具失败 = 直接返回结果给 LLM = LLM 自己决定怎么办。但 LLM 往往会放弃。

### 设计
**在 agent 层实现工具级重试**：

```python
async def _execute_tool_with_retry(tc, session, tools_used):
    result = await _execute_tool(tc, session, tools_used)
    if _is_fixable(result):
        # 给 LLM 一次修复机会
        fix_prompt = f"Tool {tc['function']['name']} failed: {result}. How would you fix this?"
        # 在当前 conversation 中插入修复 prompt
        session.conversation.append({"role": "user", "content": fix_prompt})
        retry_response = await _step(session, tools_used)
        if retry_response.tool_calls:
            # execute fix, then retry original
            ...
    return result
```

实际上更简单的做法：**错误信息自带修复指令**。

```
browser__new_tab 失败时返回：
"Error: browser daemon not running.
 Fix: browser-setup__setup()
 Or: shell__run('pip install browser-harness && browser-harness <<PY...PY')"
```

Agent 看到这条错误，天然知道下一步该调什么。不需要复杂的重试框架。

## 机制三：记忆

### 定义
Agent 的每次会话、每次工具创建、每次错误修复，记录到 MEMORY.md 系统。新会话加载历史。

### 缺少什么
记忆被记录了但**格式太松散**。`load_context()` 返回一大段文本，LLM 很难从中提取可操作的信息。

### 设计
**结构化记忆块**：

```markdown
# MEMORY.md

- [tools.md](tools.md) — Created tools
- [fixes.md](fixes.md) — Fix recipes
- [sessions.md](sessions.md) — Recent sessions
```

**fixes.md** — 关键的记忆类型。Agent 解决一个问题后自动记录：

```markdown
## 2026-05-29 browser-harness 安装
**Problem**: browser-harness not installed
**Fix**: shell__run("pip install browser-harness")
**Result**: OK
```

下次浏览器工具失败时，`load_context()` 加载这段，LLM 立刻知道怎么修。

## 三个机制如何协同

```
用户: 打开谷歌浏览器
  ↓
Agent: browser__new_tab("https://google.com")
  ↓ (失败)
browser: "Error: daemon not running. Fix: browser-setup__setup()"
  ↓ (自愈)
Agent: browser-setup__setup()
  ↓ (失败)
browser-setup: "FAILED: browser-harness not installed."
  ↓ (记忆召回 → load_context 显示上次修复方案)
Agent: [从 fixes.md 读到: shell__run("pip install browser-harness")]
  ↓ (自进化 — 如果 shell 工具不存在就用 tool-writer 创建)
Agent: shell__run("pip install browser-harness")
  ↓ (成功)
Agent: browser-setup__setup()
  ↓ (成功)
Agent: browser__new_tab("https://google.com")
  ↓ (成功)
Agent: "Chrome 已打开 Google 首页"
  ↓ (记忆写入)
MemoryManager.record_session("打开谷歌浏览器", success=True)
MemoryManager.record_fix("browser-harness 安装失败", "pip install")
```

## 改动清单

| 优先级 | 改动 | 文件 | 行数 |
|--------|------|------|------|
| **P0** | 新增 `shell` 工具 | `domain/shell.py` + `tools/shell.md` | ~80 |
| **P0** | 错误信息自带修复指令 | `domain/browser.py` 等 | ~30 |
| **P1** | 新增 `fixes.md` 记忆类型 | `memory_manager.py` | ~30 |
| **P1** | REPL 显示 Agent 计划（非思考内容时） | `cli/repl.py` | ~20 |
| **P2** | 事件循环支持一步修复重试 | `agent.py` | ~40 |

**总计 ~200 行**。不改提示词，改机制。
