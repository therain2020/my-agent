# Phase 1: 基础核心 — 详细实施方案

## 目标

自底向上构建新 agent 框架的核心模块。每个模块独立可测，不互相依赖。

完成后，`therain2020` CLI 可以接受一个任务字符串，调用 LLM，执行工具，返回结果。

## 实施顺序（依赖关系）

```
jsonutil.py (无依赖)
    ↓
constants.py (无依赖)
    ↓
memory.py (无依赖，仅 sqlite3)
    ↓
safety.py (无依赖，仅 YAML)
    ↓
tools_md.py (无依赖)
    ↓
tools.py (依赖 tools_md.py)
    ↓
provider.py (无依赖，仅 httpx)
    ↓
session.py (依赖 memory/tools/safety/provider)
    ↓
agent.py (依赖 session/jsonutil)
    ↓
run.py (依赖 agent/session)
```

## 1.1 `therain2020/jsonutil.py` (~50 行)

**职责**: LLM 响应中安全提取 JSON。

**为什么需要**: 旧代码在 6 个地方用 `text[text.find("{"):text.rfind("}")+1]` 提取 JSON。一个错误输入就崩溃。需要统一、测试过的实现。

**实现**:

```python
import json
import re

def safe_parse_json(text: str) -> dict | list:
    """Extract the first complete JSON object or array from LLM response text.
    
    Handles:
    - Markdown code blocks (```json ... ```)
    - Leading/trailing text before/after JSON
    - Nested braces/brackets (counts depth)
    
    Raises ValueError if no valid JSON found.
    """
    # 1. Strip markdown code blocks
    text = re.sub(r'```(?:json)?\s*', '', text)
    text = text.strip()
    
    # 2. Find first { or [
    for start_char, end_char in [('{', '}'), ('[', ']')]:
        start = text.find(start_char)
        if start == -1:
            continue
        # 3. Count depth to find matching close
        depth = 0
        in_string = False
        escape = False
        for i, ch in enumerate(text[start:], start):
            if escape:
                escape = False
                continue
            if ch == '\\' and in_string:
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == start_char:
                depth += 1
            elif ch == end_char:
                depth -= 1
                if depth == 0:
                    return json.loads(text[start:i+1])
    
    raise ValueError(f"No valid JSON found in: {text[:200]}...")
```

**测试覆盖**:
- 纯 JSON 对象/数组
- markdown 代码块包裹
- 前后有文本
- 嵌套对象/数组
- 字符串中包含花括号
- 转义引号
- 多对象（只取第一个）
- 空字符串 → ValueError
- 无效 JSON → ValueError

## 1.2 `therain2020/constants.py` (~30 行)

**职责**: 集中管理所有魔法数字和常量。

```python
import os
from pathlib import Path

# Agent 行为
MAX_STEPS = 5
MAX_CONVERSATION_MESSAGES = 40

# Provider
DEFAULT_MAX_TOKENS = 4096

# Memory
MEMORY_DB_FILENAME = "memory.db"
SEMANTIC_SEARCH_LIMIT = 10
RECENT_EPISODES_LIMIT = 5

# Workspace
WORKSPACE_DIR = Path(os.environ.get("TRAIN2020_WORKSPACE", Path.cwd() / ".agent"))
GENERATED_DIR_NAME = ".generated"

# Safety
DONT_DO_HOOKS = ("PLAN", "PRE_ACTION", "POST_ACTION")
```

## 1.3 `therain2020/memory.py` (~250 行)

**职责**: 统一的 SQLite 记忆存储。一次写入一个地方。

**相比于旧代码**: 保留 MemoryStore 的 SQL schema 和 FTS5 搜索，删除 EventStore、events.py、memory_migrations.py、EpisodicMemory wrapper。

**实现**:

```python
import sqlite3
import json
import time
import uuid
from pathlib import Path
from dataclasses import dataclass, field

@dataclass
class Episode:
    task: str
    result: str = ""
    steps: int = 1
    tools: list[str] = field(default_factory=list)
    success: bool = False
    error: str = ""
    task_type: str = ""
    id: str = ""
    timestamp: str = ""

@dataclass
class SemanticEntry:
    type: str          # "preference" | "fact" | "pattern"
    content: str
    confidence: float = 0.5
    source_episodes: list[str] = field(default_factory=list)
    id: str = ""
    reference_count: int = 0

class Memory:
    def __init__(self, db_path: str | Path = ":memory:"):
        self.db = sqlite3.connect(str(db_path))
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self._migrate()
    
    def _migrate(self):
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS episodic (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                task TEXT NOT NULL,
                task_type TEXT DEFAULT '',
                result TEXT DEFAULT '',
                steps INTEGER DEFAULT 1,
                tools TEXT DEFAULT '[]',
                success INTEGER DEFAULT 0,
                error TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS semantic (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                content TEXT NOT NULL,
                confidence REAL DEFAULT 0.5,
                source_episodes TEXT DEFAULT '[]',
                created_at TEXT NOT NULL,
                reference_count INTEGER DEFAULT 0
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS semantic_fts 
                USING fts5(content, content=semantic);
        """)
    
    def log_episode(self, episode: Episode) -> str:
        ...
    def get_recent(self, limit: int = 5) -> list[Episode]:
        ...
    def search_semantic(self, query: str, limit: int = 10) -> list[SemanticEntry]:
        ...
    def upsert_semantic(self, entry: SemanticEntry) -> str:
        ...
    def get_semantic_by_type(self, type: str) -> list[SemanticEntry]:
        ...
    def consolidate(self, episode_ids: list[str], new_semantic: SemanticEntry) -> str:
        ...
    def stats(self) -> dict:
        ...
    def close(self):
        ...
```

**迁移的旧代码**: `agent/memory.py` MemoryStore 类的 SQL schema、FTS5 触发器、CRUD 方法。

**测试**: 使用 `:memory:` SQLite。测试 CRUD、FTS5 搜索、统计、整合。

## 1.4 `therain2020/safety.py` (~200 行)

**职责**: 统一的运行时安全执行引擎。iptables 风格的 hook 链。

**相比于旧代码**: 合并 DontDoEngine（正确的运行时模式）和 SecurityManager（错误的 prompt 注入方式）。保留 iptables 模式，合并受限路径检查。

**实现**:

```python
from dataclasses import dataclass, field
from enum import Enum
import yaml
from pathlib import Path

class HookPoint(Enum):
    PLAN = "PLAN"
    PRE_ACTION = "PRE_ACTION"
    POST_ACTION = "POST_ACTION"

class Verdict(Enum):
    ALLOW = "ALLOW"
    REJECT = "REJECT"
    WARN = "WARN"
    LOG = "LOG"

@dataclass
class Rule:
    id: str
    description: str
    hooks: list[HookPoint]
    match: dict         # 匹配条件: {"tool": "rm", "params.path": "/etc/*"}
    action: Verdict
    message: str = ""

@dataclass
class CheckResult:
    verdict: Verdict
    rule_id: str | None = None
    message: str = ""

class SafetyEngine:
    def __init__(self, rules_dir: Path | None = None):
        self.rules: list[Rule] = []
        self._load_builtin_rules()
        if rules_dir:
            self._load_rules_from_dir(rules_dir)
    
    def _load_builtin_rules(self):
        """始终生效的内置规则。"""
        # 受限路径规则（合并自旧 SecurityManager）
        ...
    
    def _load_rules_from_dir(self, dir: Path):
        """从 YAML 文件加载规则。"""
        ...
    
    def check(self, hook: HookPoint, context: dict) -> CheckResult:
        """首次匹配语义。LOG 继续到下一条规则。"""
        ...
    
    def add_rule(self, rule: Rule):
        """程序化添加规则（来自修正系统）。"""
        ...
    
    def safety_context(self) -> str:
        """生成供 LLM 使用的安全上下文文本。"""
        ...
```

**匹配引擎**（迁移自旧 DontDoEngine._matches()）:
- 精确匹配: `{"tool": "rm"}`
- 列表匹配: `{"tool": ["rm", "delete"]}`
- 布尔匹配: `{"params.force": True}`
- 比较匹配: `{"params.size_gt": 1000}`
- Glob 匹配: `{"params.path": "/etc/*"}`

**测试**: 加载规则，测试 hook 点匹配，判决链、受限路径。

## 1.5 `therain2020/tools_md.py` (~150 行)

**职责**: 解析 tool.md 文件（YAML frontmatter + Markdown body）。

**相比于旧代码**: 保留 `parse_tool_md()` 的核心解析逻辑（~100 行）。移除 ToolEvolutionManager、ImportedToolSupervisor。

**tool.md 格式**:

```markdown
---
name: file-reader
version: 1.0.0
objects: [file]
capabilities:
  - name: read
    description: Read the contents of a file
    parameters:
      path: string (required) — Absolute or relative file path
      encoding: string — File encoding, default utf-8
    verify:
      type: return_code
      expected: 0
---

# file-reader
...
```

**实现**:

```python
import yaml
import re
from dataclasses import dataclass, field

@dataclass
class Parameter:
    name: str
    type: str
    required: bool = False
    description: str = ""

@dataclass
class Capability:
    name: str
    description: str
    parameters: list[Parameter] = field(default_factory=list)
    verify: dict | None = None

@dataclass
class ToolDef:
    name: str
    version: str = "0.1.0"
    objects: list[str] = field(default_factory=list)
    capabilities: list[Capability] = field(default_factory=list)
    source_path: Path | None = None
    body: str = ""
    
    def to_openai_tools(self) -> list[dict]:
        """转换为 OpenAI function calling 格式。"""
        ...

def parse_tool_md(content: str, source: Path | None = None) -> ToolDef:
    """解析 tool.md 字符串。"""
    # 提取 YAML frontmatter（--- ... ---）
    # 解析 YAML 为 ToolDef
    # body = frontmatter 之后的 Markdown
    ...

def load_tool_from_file(path: Path) -> ToolDef:
    """从文件加载 tool.md。"""
    ...
```

## 1.6 `therain2020/tools.py` (~200 行)

**职责**: 扫描并注册工具的薄注册表。Agent 可以在 `workspace/.generated/` 中编写新工具。

**相比于旧代码**: 保留 ToolRegistry 结构（按对象类型索引的 dict），移除 ToolEvolutionManager 和 ImportedToolSupervisor。

**实现**:

```python
from pathlib import Path
from .tools_md import ToolDef, load_tool_from_file

class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolDef] = {}        # name → ToolDef
        self._by_object: dict[str, list[str]] = {}  # object_type → [tool_names]
    
    def register(self, tool: ToolDef):
        ...
    def get(self, name: str) -> ToolDef | None:
        ...
    def find_for_object(self, object_type: str) -> list[ToolDef]:
        ...
    def list_all(self) -> list[ToolDef]:
        ...
    def scan_directory(self, dir: Path):
        """扫描目录中的 tool.md 文件并注册。"""
        ...
    def scan_generated(self, workspace: Path):
        """扫描 workspace/.generated/ 中 Agent 自编的工具。"""
        ...

def load_builtin_tools() -> ToolRegistry:
    """加载内置工具（随包提供的 tool.md 文件）。"""
    ...
```

**Agent 可编写的新工具**: Agent 将新的 tool.md 文件写入 `workspace/.generated/tool-name.md`。下次执行时，`ToolRegistry.scan_generated()` 自动加载。

## 1.7 `therain2020/provider.py` (~250 行)

**职责**: LLM 提供者抽象 + 成本感知路由。薄 wrapper，无池化、无能力矩阵。

**实现**:

```python
from dataclasses import dataclass
from enum import Enum
import os
import httpx

class TaskComplexity(Enum):
    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"

@dataclass
class LLMResponse:
    content: str
    tool_calls: list[dict] | None = None
    finish_reason: str = "stop"
    model: str = ""
    tokens_used: int = 0

class LLMProvider:
    """单个 LLM 提供者的薄包装。"""
    def __init__(self, name: str, model: str, api_key: str, 
                 base_url: str | None = None, cost_per_1k: float = 0):
        ...
    async def complete(self, messages: list[dict], tools: list[dict] | None = None,
                       tool_choice: str = "auto", max_tokens: int = 4096) -> LLMResponse:
        ...
    def token_count(self, text: str) -> int:
        """粗略估计：len(text) // 4。"""
        ...

def detect_providers() -> list[LLMProvider]:
    """从环境变量自动探测可用的 LLM 提供者。按成本排序。"""
    providers = []
    for name, env_var, model, cost in [
        ("deepseek", "DEEPSEEK_API_KEY", "deepseek-chat", 0.14),
        ("openai-mini", "OPENAI_API_KEY", "gpt-4o-mini", 0.15),
        ("anthropic-small", "ANTHROPIC_API_KEY", "claude-haiku-4-5", 0.80),
        ("openai-large", "OPENAI_API_KEY", "gpt-4o", 2.50),
        ("anthropic-large", "ANTHROPIC_API_KEY", "claude-sonnet-4-6", 3.00),
    ]:
        if os.environ.get(env_var):
            providers.append(LLMProvider(name, model, os.environ[env_var], cost_per_1k=cost))
    return providers

def estimate_complexity(task: str) -> TaskComplexity:
    """关键字匹配评估任务复杂度（迁移自 CostRouter）。"""
    complex_keywords = ["refactor", "rewrite", "architecture", "design", "debug"]
    moderate_keywords = ["implement", "add", "create", "modify", "update"]
    ...

def route(task: str, providers: list[LLMProvider]) -> LLMProvider:
    """为给定任务选择正确的提供者。简单→最便宜，复杂→最强。"""
    ...

def escalate(current: LLMProvider, providers: list[LLMProvider]) -> LLMProvider | None:
    """升级到下一个更强的提供者。"""
    ...
```

## 1.8 `therain2020/session.py` (~200 行)

**职责**: 捆绑 Agent 需要的所有上下文。仅含数据 + 基本服务，无 daemon。

**实现**:

```python
from dataclasses import dataclass, field
from pathlib import Path
from .memory import Memory
from .tools import ToolRegistry, load_builtin_tools
from .safety import SafetyEngine
from .provider import LLMProvider, detect_providers, route

@dataclass
class Session:
    memory: Memory
    tools: ToolRegistry
    safety: SafetyEngine
    provider: LLMProvider
    conversation: list[dict] = field(default_factory=list)
    task_id: str = ""
    workspace: Path = Path(".agent")
    max_steps: int = 5

def create_session(
    task: str = "",
    workspace: Path | None = None,
    memory_path: str | Path = ":memory:",
    rules_dir: Path | None = None,
) -> Session:
    """创建会话的工厂函数。自动探测提供者并路由。"""
    providers = detect_providers()
    if not providers:
        raise RuntimeError("No LLM provider available. Set OPENAI_API_KEY or ANTHROPIC_API_KEY.")
    provider = route(task, providers) if task else providers[0]
    
    ws = workspace or Path(".agent")
    ws.mkdir(parents=True, exist_ok=True)
    
    tools = load_builtin_tools()
    tools.scan_generated(ws / ".generated")
    
    return Session(
        memory=Memory(memory_path),
        tools=tools,
        safety=SafetyEngine(rules_dir),
        provider=provider,
        workspace=ws,
    )
```

## 1.9 `therain2020/agent.py` (~300 行)

**职责**: 核心 Agent 事件循环。组合函数，非 god class。

**最关键的变更**: 1771 行 god class → ~300 行组合函数。

**实现**:

```python
import uuid
from .session import Session
from .memory import Episode
from .jsonutil import safe_parse_json

async def run(task: str, session: Session) -> str:
    """执行任务。返回结果字符串。"""
    session.task_id = uuid.uuid4().hex[:12]
    tools_used = []
    steps = 0
    
    # 构建系统消息
    system_msg = _build_system(session)
    session.conversation = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": task},
    ]
    
    # 事件循环
    for step in range(session.max_steps):
        steps = step + 1
        response = await _step(session, tools_used)
        if response.finish_reason == "stop":
            break
    
    # 记录事件
    session.memory.log_episode(Episode(
        task=task, result=response.content, steps=steps,
        tools=tools_used, success=True,
    ))
    
    return response.content

async def run_stream(task: str, session: Session):
    """流式变体，向 TUI 产生 StepEvent。"""
    ...

async def _step(session: Session, tools_used: list[str]) -> StepResult:
    """单次迭代。"""
    # 1. 准备 OpenAI 格式工具
    tool_schemas = [
        t for tool in session.tools.list_all()
        for t in tool.to_openai_tools()
    ]
    
    # 2. 调用 LLM
    response = await session.provider.complete(
        messages=session.conversation,
        tools=tool_schemas or None,
    )
    
    # 3. 检查是否为工具调用
    if response.tool_calls:
        for tc in response.tool_calls:
            _execute_tool(tc, session, tools_used)
        # 将工具结果添加到对话
        ...
    
    return StepResult(
        finish_reason=response.finish_reason,
        content=response.content,
        tool_calls=response.tool_calls,
    )

def _build_system(session: Session) -> str:
    """构建系统提示。"""
    parts = [
        "You are an AI assistant with access to tools.",
        session.safety.safety_context(),
        "Available tools:",
    ]
    for tool in session.tools.list_all():
        parts.append(f"- {tool.name}: {tool.capabilities[0].description}")
    return "\n".join(parts)

def _execute_tool(tool_call: dict, session: Session, tools_used: list[str]):
    """执行工具调用。先检查安全，再执行。"""
    name = tool_call["function"]["name"]
    args = safe_parse_json(tool_call["function"]["arguments"])
    
    # PRE_ACTION hook
    check = session.safety.check("PRE_ACTION", {"tool": name, "params": args})
    if check.verdict == "REJECT":
        return f"Rejected: {check.message}"
    
    # 执行
    tool = session.tools.get(name)
    result = _dispatch_tool(tool, args)  # 简单的 import 或 subprocess 分发
    
    # POST_ACTION hook
    session.safety.check("POST_ACTION", {"tool": name, "result": result})
    
    tools_used.append(name)
    return result
```

## 1.10 `therain2020/run.py` (~150 行)

**职责**: 最小 CLI 入口。参考 browser-harness `run.py`（130 行）。

**实现**:

```python
import sys
import asyncio
from pathlib import Path
from .agent import run
from .session import create_session

async def main():
    # 解析参数
    args = sys.argv[1:]
    if not args and sys.stdin.isatty():
        print("Usage: therain2020 <task>")
        print("       echo <task> | therain2020")
        sys.exit(1)
    
    task = " ".join(args) if args else sys.stdin.read().strip()
    if not task:
        print("Error: empty task")
        sys.exit(1)
    
    session = create_session(task=task)
    result = await run(task, session)
    print(result)

def cli():
    asyncio.run(main())
```

## 1.11 `therain2020/__init__.py`

```python
"""therain2020 — Thin agent harness."""
__version__ = "0.8.0"
```

## 测试（阶段 1）

每个模块的测试文件，1:1 对应：

```
tests/
├── __init__.py
├── test_jsonutil.py      # 8+ 测试用例
├── test_memory.py        # CRUD、FTS5、统计
├── test_safety.py        # 规则加载、hook 匹配
├── test_tools_md.py      # 解析 tool.md
├── test_tools.py         # 注册表、扫描
├── test_provider.py      # 路由、探测
├── test_session.py       # 创建会话
├── test_agent.py         # 模拟提供者，测试循环
└── test_run.py           # CLI 入口
```

## 文件创建清单

| # | 文件 | 状态 |
|---|------|------|
| 1 | `therain2020/__init__.py` | 新建 |
| 2 | `therain2020/jsonutil.py` | 新建 |
| 3 | `therain2020/constants.py` | 新建 |
| 4 | `therain2020/memory.py` | 新建（迁移 agent/memory.py） |
| 5 | `therain2020/safety.py` | 新建（合并 dont_do.py + security） |
| 6 | `therain2020/tools_md.py` | 新建（迁移 tools/loader.py） |
| 7 | `therain2020/tools.py` | 新建（迁移 tools/registry.py） |
| 8 | `therain2020/provider.py` | 新建（合并 router + autodetect） |
| 9 | `therain2020/session.py` | 新建 |
| 10 | `therain2020/agent.py` | 新建 |
| 11 | `therain2020/run.py` | 新建 |
| 12 | `therain2020/cli/__init__.py` | 占位 |
| 13 | `tests/test_jsonutil.py` | 新建 |
| 14 | `tests/test_memory.py` | 迁移 tests/unit/test_memory.py |
| 15 | `tests/test_safety.py` | 迁移 tests/unit/test_dont_do.py |
| 16 | `tests/test_tools.py` | 合并 test_registry + test_tool_loader |
| 17 | `tests/test_provider.py` | 合并 test_cost_router + test_capability |
| 18 | `tests/test_session.py` | 新建 |
| 19 | `tests/test_agent.py` | 新建 |
| 20 | `tests/test_run.py` | 新建 |

## 验收标准

```bash
# 1. 所有测试通过
pytest tests/ -v

# 2. 可以执行简单任务
therain2020 "say hello world"

# 3. 管道方式工作
echo "say hello" | therain2020

# 4. 每个模块可以独立导入
python -c "from therain2020.jsonutil import safe_parse_json"
python -c "from therain2020.memory import Memory"
python -c "from therain2020.safety import SafetyEngine"
python -c "from therain2020.tools import ToolRegistry"
python -c "from therain2020.provider import detect_providers"
python -c "from therain2020.session import create_session"
python -c "from therain2020.agent import run"
