# Phase 2: CLI + TUI — 详细实施方案

## 目标

将旧项目的 Textual TUI 和 REPL 迁移到新 agent 核心，使 therain2020 拥有交互式终端界面。

## 前置条件

Phase 1 完成。`agent.py` 的 `run_stream()` 方法规范已确定。

## 2.1 `therain2020/cli/tui.py` (~400 行)

**职责**: 基于 Textual 的终端 UI。迁移自 `agent/cli/tui/`。

**相比于旧代码**: 保留 Textual 组件结构（TaskInput、OutputArea、StatusBar），适配到新的流式接口。

**迁移要点**:
- 用 `agent.run_stream()` 替换旧的 `Agent.goal_run()`
- 用 `StepEvent` 替换旧的 `StreamEvent`
- 保留 Textual CSS 样式
- 保留键盘快捷键（Ctrl+C 取消等）

**实现**:

```python
"""Textual TUI for therain2020 agent."""
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Input, RichLog
from textual.containers import Container

class AgentTUI(App):
    CSS = """
    /* 迁移自旧 TUI CSS */
    """
    
    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            RichLog(id="output"),
            Input(id="task_input", placeholder="Enter task..."),
        )
        yield Footer()
    
    async def on_input_submitted(self, event):
        task = event.value
        session = create_session(task=task)
        async for step_event in run_stream(task, session):
            self._render_step(step_event)
```

## 2.2 `therain2020/cli/repl.py` (~200 行)

**职责**: 简单的 read-eval-print 循环（非 TUI 模式）。

**迁移要点**:
- 用 `agent.run()` 替换旧的 REPL 循环
- 支持 Rich 渲染
- 保留历史记录

## 2.3 清理旧的 CLI 文件

删除不再需要的文件：
- `agent/cli/run.py` — 替换为 `therain2020/run.py`
- `agent/cli/add.py` — tool.md 编辑不再需要
- `agent/cli/info.py` — 信息诊断
- `agent/cli/providers.py` — 提供者管理
- `agent/cli/publish.py` — 包发布
- `agent/cli/status.py` — 状态显示
- `agent/cli/display.py` — 显示工具

## 2.4 更新 CLI 入口点

更新 `pyproject.toml`：

```toml
[project.scripts]
therain2020 = "therain2020.run:cli"

[project.optional-dependencies]
tui = ["textual", "rich"]
```

## 文件创建清单

| # | 文件 | 状态 |
|---|------|------|
| 1 | `therain2020/cli/__init__.py` | 新建 |
| 2 | `therain2020/cli/tui.py` | 迁移 agent/cli/tui/ |
| 3 | `therain2020/cli/repl.py` | 迁移 agent/cli/repl.py |
| 4 | 删除旧 CLI 文件 | agent/cli/{add,info,providers,publish,status,display,run}.py |

## 验收标准

```bash
# 1. TUI 模式启动
therain2020 --tui

# 2. REPL 模式
therain2020 --repl

# 3. 直接模式仍然工作
therain2020 "list files"
```
