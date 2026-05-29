# 自进化方案：Agent 给自己写工具

## browser-harness 的自进化模式

```
agent: wants to upload a file
│
● agent-workspace/agent_helpers.py → helper 不存在
│
● agent 自己写 helper 代码
│
✓ file uploaded，下次这个 helper 就有了
```

核心：**Agent 是工具的消费者，也是工具的生产者**。

## 当前状态：能力闭环是断的

`ToolRegistry.scan_generated()` 已实现——会扫描 `workspace/.generated/*.md`。
但 Agent 的工具列表里没有"写一个 tool.md 文件"的能力。

```
生成端 ✗: Agent 无法创建 tool.md → .generated 目录永远是空的
消费端 ✓: ToolRegistry.scan_generated() 会加载（只是没有东西可加载）
```

## 方案

### 新增一个内置工具：`tool-writer`

在 `domain/tools/` 下新增 `tool-writer.md`，让 Agent 有能力给自己写新工具。

```markdown
---
name: tool-writer
version: 1.0.0
objects: [tool]
capabilities:
  - name: write
    description: "Create a new tool for yourself. Use when existing tools cannot complete
                  a task and you know how to solve it with Python code or a tool.md definition."
    parameters:
      name: string (required) — Tool name (e.g., 'image-resizer')
      code: string (required) — Python function body for the tool
      description: string — What this tool does
---
```

对应的 Python 实现：

```python
# domain/tool_writer.py

def write(name: str, code: str, description: str = "") -> str:
    """Create a new tool.md + Python module in .generated/"""
    generated = WORKSPACE_DIR / ".generated"
    generated.mkdir(parents=True, exist_ok=True)

    # 1. 写 Python 实现
    py_file = generated / f"{name}.py"
    py_file.write_text(code, encoding="utf-8")

    # 2. 写 tool.md 注册文件
    md_file = generated / f"{name}.md"
    md_content = f"""---
name: {name}
version: 0.1.0
objects: []
capabilities:
  - name: run
    description: {description}
---
# {name}
Agent-generated tool.
"""
    md_file.write_text(md_content, encoding="utf-8")
    return f"Tool '{name}' created. Restart to load it."
```

### 流程

```
第 1 次会话：
  > 帮我把这张图片转成 webp 格式
  … filesystem__read("photo.png")
  [思考] 没有 image-convert 工具，但我可以用 Pillow 写一个...
  … tool-writer__write(name="image-convert", code="from PIL import Image\n...")
  [✓] → Tool created. Restart to load.

第 2 次会话（重启后）：
  > 把这批图片都转成 webp
  /tools → 显示 tool-writer, filesystem, browser, image-convert ← 新工具！
  … image-convert__run(path="photo1.png", format="webp")
  [✓]
  … image-convert__run(path="photo2.png", format="webp")
  [✓]
```

### 再加上记忆闭环（配套）

工具写了，重启后能加载。但如果 Agent 能**记住**"上次我写了一个 image-convert 工具"就更好了——这是记忆闭环的作用：

```
启动时 → _build_memory_context() → "Learned: you created 'image-convert' tool last session"
       → ToolRegistry.scan_generated() → 加载 image-convert
       → Agent 知道自己有什么能力，也记得自己创造过什么能力
```

## 改动范围

| 文件 | 变更 | 说明 |
|------|------|------|
| `domain/tools/tool-writer.md` | 新增 | 工具定义 |
| `domain/tool_writer.py` | 新增 ~30 行 | write() 实现 |
| `agent.py` | +40 行 | 记忆上下文注入 + 失败学习 |
| **新增** | **~70 行** | |

## 不做

- 不做"自动修复代码"——Agent 写的代码可能有 bug，下次跑的时候报错就是反馈
- 不做"工具版本管理"——browser-harness 没有 evolution manager，文件系统就是版本控制
- 不做"工具质量评分"——用得多的自然留下，不用的被覆盖

## 和 browser-harness 的精确对应

| browser-harness | therain2020 自进化 |
|----------------|-------------------|
| `agent_helpers.py` 被 Agent 编辑 | `tool-writer` → `.generated/{name}.py` |
| `domain-skills/` 被 Agent 写 | `tool-writer` → `.generated/{name}.md` |
| 重启后 `import agent_helpers` | 重启后 `ToolRegistry.scan_generated()` |
| Agent 自己写 helper | Agent 调用 `tool-writer__write()` |
| run.py 自动加载 | create_session() 自动加载 |

自进化机制和agent的记忆机制密不可分，我们知道，claude code采用的是每个session在一个单独的记忆文件，可以保存到本地让新session读取记忆文件。也可以直接在新session通过/resume直接读取历史session记忆。我们项目的agent要实现自进化机制，就必须有适合的记忆机制。参考claude code的记忆机制，为实现自进化机制，设计适合我们项目的记忆机制。同时优化当前自进化机制。