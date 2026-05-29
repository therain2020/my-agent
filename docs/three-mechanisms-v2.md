# 三机制 V3：最全面的代码级自愈/自进化/记忆系统

## 当前问题诊断

| 症状 | 根因 | 缺失的能力 |
|------|------|-----------|
| Agent 每次都用 `which` | 不知自己在 Windows | **L0 平台感知** |
| Chrome 路径每次重新发现 | 没有缓存已知路径 | **L2 路径记忆** |
| 同样的修复每次重新想 | 修复不持久化到错误消息 | **L3 错误富含** |
| browser-harness 明明装了还重装 | 没有前置检查 | **L1 前置检查** |
| 跨会话零提升 | 没有从历史中学习 | **L2+L4 记忆+进化** |
| 修复过的复杂流程下次还要重来 | 不提取技能 | **L5 技能提取** |
| "daemon not running" vs "连接失败" 当成两个错误 | 没有模糊匹配 | **L6 语义匹配** |
| 生成的新工具可能写错 | 不测试就装 | **L7 安全测试** |
| 用户说"不对"后 Agent 不知道 | 没有反馈闭环 | **L8 用户反馈** |

## 八层架构

```
L8: 用户反馈  ── 用户说 ✓/✗ → 调整修复置信度
L7: 安全沙箱  ── 自生成的修复/工具先测试再安装
L6: 语义匹配  ── "daemon not running" ≈ "连接被拒绝" ≈ "WebSocket error"
L5: 技能提取  ── 多次成功的工具调用序列 → 提取为可复用技能
L4: 自进化    ── 高频修复自动升级为永久工具
L3: 错误富含  ── 工具失败时自动查 healing DB，错误消息带上修复命令
L2: 记忆DB    ── heal.json 持久化：修复方案 + 路径缓存 + 平台指纹
L1: 前置检查  ── 工具执行前检查依赖（browser 需要 daemon，bash 需要 shell）
L0: 平台感知  ── 启动时检测 OS，缓存正确命令和路径
```

---

## L0: 平台感知

```python
@dataclass
class Platform:
    os: str                   # 'windows' | 'darwin' | 'linux'
    shell_cmd: str            # 'cmd /c' | '/bin/bash -c'
    which_cmd: str            # 'where' | 'which'
    list_cmd: str             # 'dir' | 'ls'
    path_sep: str             # '\\' | '/'
    home: Path                # C:\Users\... | /home/...
    program_files: list[Path] # Windows: Program Files variants
    
    @classmethod
    def detect(cls) -> Platform:
        ...
```

注入到系统提示：
```
ENVIRONMENT: Windows 11 · shell=cmd /c · find_cmd=where · list_cmd=dir
  Chrome likely at: C:\Program Files\Google\Chrome\Application\chrome.exe
  Python scripts at: C:\Users\...\AppData\Local\Programs\Python\Python311\Scripts\
```

---

## L1: 前置检查

每个工具可以注册前置条件。Agent 不需要知道这些——工具内部自检。

```python
# domain/browser.py
_PRECONDITIONS = [
    ("daemon_alive", _check_daemon),
    ("chrome_running", _check_chrome_listening),
]

def _ensure_ready():
    """Auto-setup before any browser operation."""
    for name, check in _PRECONDITIONS:
        if not check():
            fix = healing.lookup(name, "browser")
            if fix:
                _apply_fix(fix)
                if not check():
                    raise ToolError(name, fix)
            else:
                raise ToolError(name, None)
```

`ToolError` 包含前置条件名 + 修复方案。LLM 看到后可以直接调修复。

```
→ 所有 browser__* 函数调用前先跑 _ensure_ready()
→ 如果 daemon 没运行，自动查 healing DB 找启动命令
→ 如果找不到修复，抛 ToolError 带 HEAL 标签
→ LLM 看到 HEAL 后调 bash__run(...)
→ 成功 → healing.record() 保存
```

---

## L2: 记忆DB

### `~/.therain2020-agent/heal.json`

```json
{
  "version": 2,
  "platform": {"os": "windows", "shell": "cmd /c", "which": "where", ...},
  "paths": {
    "chrome": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "browser_harness": "C:\\Users\\...\\Scripts\\browser-harness.exe"
  },
  "fixes": {
    "daemon_alive": {
      "patterns": ["daemon not running", "connection refused", ...
      "fix": "start \"\" \"CHROME\" --remote-debugging-port=9222 ...",
      "tool": "browser", "platform": "windows",
      "success": 23, "fail": 1,
      "last_used": "...", "first_seen": "..."
    }
  },
  "skills": {
    "open-browser": {
      "description": "Install browser-harness + find Chrome + launch + open tab",
      "steps": [
        {"tool": "bash__run", "args": {"command": "pip install browser-harness"}},
        {"tool": "bash__run", "args": {"command": "start chrome ..."}},
        {"tool": "browser__new_tab", "args": {"url": "..."}}
      ],
      "success": 5, "fail": 0
    }
  },
  "learnings": {
    "windows-no-which": {
      "pattern": "is not recognized as an internal",
      "fix": "Use 'where' not 'which', 'dir' not 'ls' on Windows",
      "permanent": true
    }
  }
}
```

### API

```python
class HealingDB:
    # 基础 CRUD
    def load() -> HealingDB
    def save()
    
    # 修复
    def record(pattern: str, fix: str, tool: str, success: bool)
    def lookup(error_text: str, tool: str = "") -> Fix | None
    def enrich_error(error_text: str, tool: str) -> str
    def get_confidence(pattern: str) -> float  # success / (success + fail)
    
    # 路径
    def remember_path(name: str, path: str)
    def get_path(name: str) -> str | None
    
    # 技能
    def extract_skill(steps: list[ToolStep]) -> Skill | None
    def get_skill(description: str) -> Skill | None
    
    # 平台
    def platform() -> Platform
    def platform_context() -> str
    
    # 提示
    def system_context() -> str
```

---

## L3: 错误富含

```python
def enrich_error(error_text: str, tool_name: str) -> str:
    """给错误消息追加修复方案。支持模糊匹配。"""
    
    # 1. 精确匹配
    fix = healing.lookup(error_text, tool_name)
    if fix and fix.confidence > 0.5:
        return f"{error_text}\n\n  HEAL ({fix.success}/{fix.success+fix.fail}): {fix.command}"

    # 2. 模糊匹配（关键词提取）
    keywords = _extract_keywords(error_text)
    for kw in keywords:
        fix = healing.lookup(kw, tool_name)
        if fix and fix.confidence > 0.7:
            return f"{error_text}\n\n  HEAL ({fix.confidence:.0%} match): {fix.command}"
    
    # 3. 平台知识
    if "not recognized" in error_text or "不是内部" in error_text:
        return f"{error_text}\n\n  HEAL: On {healing.platform.os}, use '{healing.platform.which_cmd}' not 'which', and '{healing.platform.list_cmd}' not 'ls'."
    
    return error_text
```

LLM 看到的实际效果：
```
✗ browser__new_tab(): [ERROR] browser daemon not running

  HEAL (23/24 success): bash__run('start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222')
```

LLM 只需要决定"是否执行这个 HEAL 命令"。答案几乎总是"是"。

---

## L4: 自进化 — 三级升级

| 级别 | 触发条件 | 动作 |
|------|---------|------|
| **L4a: 强置信度** | success ≥ 5, confidence > 0.9 | HEAL 标签带 ⭐ 标记，LLM 优先选择 |
| **L4b: 自动应用** | success ≥ 15, fail = 0 | `_ensure_ready()` 内部自动执行，不经过 LLM |
| **L4c: 永久工具** | success ≥ 30, 跨 5+ 不同任务 | 生成 `.generated/{name}-auto-fix.py` 永久工具 |

```python
def auto_apply_if_confident(error_text, tool_name):
    """如果修复置信度足够高，直接自动执行，不通知 LLM。"""
    fix = healing.lookup(error_text, tool_name)
    if fix and fix.success >= 15 and fix.fail == 0:
        result = bash__run(fix.command)
        healing.record(error_text, fix.command, tool_name, result.ok)
        return True
    return False
```

---

## L5: 技能提取

多次成功的工具调用序列 → 提取为可复用技能。

```python
def extract_skill(session: Session) -> Skill | None:
    """如果同一任务成功了 3 次以上，提取为技能。"""
    recent = session.memory.get_recent(limit=10)
    tasks = [ep for ep in recent if ep.success]
    
    # 找到重复出现的成功任务
    from collections import Counter
    task_counts = Counter(ep.task for ep in tasks)
    
    for task, count in task_counts.most_common(3):
        if count >= 3:
            # 提取工具序列
            episodes = [ep for ep in tasks if ep.task == task]
            common_tools = _find_common_tool_sequence(episodes)
            if common_tools:
                return Skill(
                    name=_slugify(task),
                    description=task,
                    steps=common_tools,
                    confidence=count / len(tasks),
                )
    return None
```

Agent 下次遇到 "打开谷歌浏览器" → 查技能 → 直接执行工具序列，不需要 LLM 逐步推理。

---

## L6: 语义匹配

```python
# 同义词表
_SYNONYMS = {
    "daemon not running": [
        "connection refused", "cannot connect", "WebSocket",
        "not alive", "no daemon", "daemon is dead",
        "连接被拒绝", "无法连接",
    ],
    "not found": [
        "not installed", "no such file", "cannot find",
        "not recognized", "找不到",
    ],
    "permission denied": [
        "access denied", "not permitted", "EACCES",
        "拒绝访问", "权限不足",
    ],
}

def _normalize_error(error_text: str) -> str:
    """标准化错误消息，方便匹配。"""
    lower = error_text.lower()
    for canonical, synonyms in _SYNONYMS.items():
        if any(s.lower() in lower for s in [canonical] + synonyms):
            return canonical
    return error_text[:80]
```

---

## L7: 安全沙箱

自生成的修复/工具先测试再安装。

```python
def safe_install_auto_fix(name: str, code: str, test_input: str) -> bool:
    # 1. 写到临时文件
    tmp = Path(tempfile.mkdtemp()) / f"{name}.py"
    tmp.write_text(code)
    
    # 2. 在子进程中测试
    result = subprocess.run(
        [sys.executable, str(tmp), test_input],
        capture_output=True, text=True, timeout=10,
    )
    
    # 3. 测试通过 → 安装到 .generated/
    if result.returncode == 0:
        dest = WORKSPACE_DIR / ".generated" / f"{name}.py"
        dest.write_text(code)
        return True
    
    # 4. 测试失败 → 记录到 healing DB（标记为不可靠）
    healing.record("auto-fix failed: " + name, result.stderr, "system", False)
    return False
```

---

## L8: 用户反馈

```python
def apply_feedback(task_id: str, rating: str):
    """用户反馈：'good' | 'bad' | 'skip'"""
    if rating == "good":
        healing.boost_confidence(task_id)
    elif rating == "bad":
        healing.decrease_confidence(task_id)
```

REPL 中每次任务完成后显示 `[✓ good / ✗ bad / → skip]`（1.5 秒内按键，否则默认 good）。

---

## 改动清单

| 文件 | 操作 | 行数 |
|------|------|------|
| `therain2020/healing.py` | 新建 — HealingDB + Platform + Skill | ~250 |
| `therain2020/agent.py` | 改 — _execute_tool, _step, _build_system, run_stream | ~80 |
| `therain2020/domain/browser.py` | 改 — _ensure_ready() + 前置检查 | ~60 |
| `therain2020/domain/bash.py` | 改 — Platform-aware command wrapping | ~20 |
| `therain2020/cli/app.py` | 改 — 用户反馈快捷键 | ~15 |
| `tests/test_healing.py` | 新建 | ~80 |
| **合计** | | **~505** |

## 实施优先级

| 优先级 | 层 | 效果 |
|--------|----|------|
| **P0 立即**| L0+L1+L2+L3 | Agent 第二次遇到同一错误就知道怎么修 |
| **P1 本周**| L4+L6 | 高频修复自动应用，不再烦 LLM |
| **P2 下周**| L5+L7+L8 | 技能提取、安全测试、用户反馈 |
