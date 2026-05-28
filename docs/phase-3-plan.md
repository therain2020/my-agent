# Phase 3: 领域工具 — 详细实施方案

## 目标

构建两个领域工具模块：浏览器自动化（集成 browser-harness）和文件系统操作。它们是新框架的首批工具，也验证了 tool.md → ToolRegistry 路径。

## 3.1 `therain2020/domain/browser.py` (~300 行)

**职责**: 将 browser-harness daemon 集成为 Agent 工具。截图优先交互模型。

**设计理念**（直接取自 browser-harness SKILL.md）:
- 截图优先：`capture_screenshot()` → 找目标 → `click_at_xy(x, y)` → `capture_screenshot()` 验证
- 坐标点击穿透 iframe/Shadow DOM/跨域（合成层级别）
- 连接用户已运行的 Chrome，不自己启动浏览器
- 批量 HTTP 用 `http_get()` + ThreadPoolExecutor

**实现**:

```python
"""Browser domain tool — thin wrapper over browser-harness daemon."""
import asyncio
import json
import base64
import time
from pathlib import Path
from urllib.parse import urlparse

# CDP 原语（复制/适配自 browser-harness helpers.py）
def cdp(method, session_id=None, **params):
    """通过 IPC 发送原始 CDP 命令到 browser-harness daemon。"""
    ...

def click_at_xy(x, y, button="left", clicks=1):
    """合成层点击 — 穿透 iframe/Shadow DOM。"""
    cdp("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button=button, clickCount=clicks)
    cdp("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y, button=button, clickCount=clicks)

def capture_screenshot(path=None, full=False, max_dim=1800):
    """当前视口 PNG 截图。"""
    ...

def page_info():
    """{url, title, w, h, sx, sy, pw, ph}。"""
    ...

# 导航
def new_tab(url="about:blank"):
    ...
def goto_url(url):
    ...
def switch_tab(target):
    ...
def list_tabs(include_chrome=True):
    ...

# 工具
def js(expression):
    """在页面中运行 JS。"""
    ...
def http_get(url, headers=None, timeout=20):
    """纯 HTTP — 不走浏览器。"""
    ...

# 等待
def wait(seconds=1.0):
    ...
def wait_for_load(timeout=15):
    ...
def wait_for_element(selector, timeout=10, visible=False):
    ...

# 类型
def type_text(text):
    ...
def press_key(key, modifiers=0):
    ...

# 滚动
def scroll(x, y, dy=-300, dx=0):
    ...
```

**Agent 工作空间集成**:

```python
# Agent 可以在 workspace/.generated/ 中编写浏览器 playbook
# 格式：workspace/.generated/browser-amazon-search.md
```

**browser-harness 依赖**: 不直接依赖。通过 IPC 与已安装的 browser-harness daemon 通信。如果未安装，返回清晰的错误信息。

**安全**:
- 不自动输入凭据（auth wall → 停止并询问用户）
- 所有导航记录在内存中
- URL 白名单（来自 SafetyEngine）

## 3.2 `therain2020/domain/filesystem.py` (~150 行)

**职责**: 文件系统操作 — 读、写、列表、删除。Agent 最常用的工具。

**实现**:

```python
"""Filesystem domain tools."""
import os
import shutil
from pathlib import Path

def read_file(path: str) -> str:
    """读取文件内容。自动检测编码。"""
    p = Path(path).expanduser()
    if not p.is_file():
        raise FileNotFoundError(f"Not a file: {path}")
    try:
        return p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return p.read_text(encoding="latin-1")

def write_file(path: str, content: str) -> bool:
    """写入文件。如果父目录不存在则自动创建。"""
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return True

def list_files(dir: str = ".", pattern: str = "*") -> list[str]:
    """列出目录中的文件。"""
    p = Path(dir).expanduser()
    return sorted(str(f) for f in p.glob(pattern) if not f.name.startswith("."))

def delete_file(path: str) -> bool:
    """删除文件或空目录。"""
    ...

def search_files(dir: str, query: str) -> list[str]:
    """使用 ripgrep 搜索文件内容。回退到 Python。"""
    ...

def make_temp(content: str, suffix: str = "") -> str:
    """创建临时文件并返回路径。"""
    ...
```

## 3.3 领域工具注册

领域工具通过 tool.md 文件注册，而非硬编码：

```
therain2020/domain/
├── tools/
│   ├── file-reader.md
│   ├── file-writer.md
│   ├── file-lister.md
│   └── browser-control.md
└── browser.py
    filesystem.py
```

内置工具在 `ToolRegistry.load_builtin_tools()` 中注册：

```python
def load_builtin_tools() -> ToolRegistry:
    registry = ToolRegistry()
    builtin_dir = Path(__file__).parent / "domain" / "tools"
    registry.scan_directory(builtin_dir)
    return registry
```

## 文件创建清单

| # | 文件 | 状态 |
|---|------|------|
| 1 | `therain2020/domain/__init__.py` | 新建 |
| 2 | `therain2020/domain/browser.py` | 新建 |
| 3 | `therain2020/domain/filesystem.py` | 新建 |
| 4 | `therain2020/domain/tools/file-reader.md` | 新建 |
| 5 | `therain2020/domain/tools/file-writer.md` | 新建 |
| 6 | `therain2020/domain/tools/file-lister.md` | 新建 |
| 7 | `therain2020/domain/tools/browser-control.md` | 新建 |
| 8 | `tests/domain/test_filesystem.py` | 新建 |
| 9 | `tests/domain/test_browser.py` | 新建（集成测试，需要 Chrome） |

## 验收标准

```bash
# 1. 文件系统工具工作
therain2020 "read file pyproject.toml"

# 2. 浏览器工具列出标签页（需要 Chrome + browser-harness）
therain2020 "list my browser tabs"

# 3. Agent 可以在 .generated/ 中编写新工具
therain2020 "write a tool that counts lines in a file"
# → 检查 workspace/.generated/ 中是否有新文件
```
