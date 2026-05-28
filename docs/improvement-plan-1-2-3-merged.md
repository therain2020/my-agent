# Agent 改进方案：原始 IDEA vs 当前实现的差距分析及改进路线

> 基于原始设计理念的逐项深度改进方案
> 2026-05-27

---

## 一、非集 (Don't-Do) 深度改进方案

### 1.1 现状诊断

当前非集系统存在**双层架构但仅一层生效**的问题：

| 层 | 组件 | 是否在 agent loop 中调用 |
|----|------|------------------------|
| Prompt 注入层 | `SecurityManager` | ✅ `get_constraints_prompt()` 在每次构建 prompt 时调用 |
| 运行时引擎 | `DontDoEngine` | ❌ **从未被调用** — `Agent.__init__` 中未创建实例 |

`agent/core.py` 中搜索 `DontDoEngine`、`dont_do`、`HookPoint`：结果为 0。

`EpisodeEntry.non_set_changes` 字段在 `memory.py:23` 定义，在 `memory.py:76,111` 读写，但在 `agent/core.py` 的 `run()` 和 `goal_run()` 中**从未赋值**——始终为空列表 `[]`。

### 1.2 根因分析

1. `DontDoEngine` 与 `SecurityManager` 职责重叠但不互通
2. 开发时先做了 prompt 注入（Phase 1），再做运行时引擎（Phase 2），但**运行时引擎未接入 agent loop**——属于典型的集成遗漏
3. 没有"用户纠正 → 规则生成"的触发机制

### 1.3 改进方案

#### 1.3.1 Agent 中集成 DontDoEngine

**改动文件**: `agent/core.py`

```python
# 新增 import
from .dont_do import DontDoEngine, HookPoint, Verdict

class Agent:
    def __init__(self, config_path=None):
        # ... 现有初始化 ...
        self.dont_do = DontDoEngine()  # 新增：运行时规则引擎

    def setup(self):
        self.registry.scan()
        self.security.load_rules()       # prompt 注入层
        self.dont_do.load_rules(         # 运行时引擎（同数据源，不同用途）
            self.config["security"]["dont_do_paths"]
        )
        self.interrupt.setup()
```

#### 1.3.2 Hook 点接入

在三个关键位置调用 `dont_do.check()`：

**位置 1 — PLAN hook（`_plan_goal()` 之后）**:
```python
async def _plan_goal(self, goal, observation, conversation):
    plan = await self._plan_goal_raw(goal, observation, conversation)
    # 新增：检查计划中的每一步
    filtered_plan = []
    for step in plan:
        verdict, msg = self.dont_do.check(HookPoint.PLAN, {
            "object": step.get("object", "unknown"),
            "operation": step.get("action", ""),
            "tool": step.get("tool", ""),
        })
        if verdict == Verdict.REJECT:
            logger.warning("plan_step_rejected", step=step, reason=msg)
            self._track_non_set_change("hit", "plan_reject", msg, step)
            continue  # 跳过被拒绝的步骤
        elif verdict == Verdict.WARN:
            logger.warning("plan_step_warned", step=step, reason=msg)
            step["_warning"] = msg
        filtered_plan.append(step)
    return filtered_plan
```

**位置 2 — PRE_ACTION hook（工具执行前）**:
```python
# 在 executor.execute() 调用前
for tc in tool_calls:
    verdict, msg = self.dont_do.check(HookPoint.PRE_ACTION, {
        "object": tc.get("object", tool_def.objects[0] if tool_def.objects else "unknown"),
        "operation": tc["capability"],
        "tool": tc["tool"],
        "params": tc.get("params", {}),
    })
    if verdict == Verdict.REJECT:
        conversation += f"\n[Blocked] {msg}"
        continue
    elif verdict == Verdict.WARN:
        conversation += f"\n[Warning] {msg}"
    # 继续执行...
```

**位置 3 — POST_ACTION hook（工具执行后）**:
```python
# 在获取工具结果后
result = await self.executor.execute(tool_def, tc["capability"], tc.get("params", {}))
verdict, msg = self.dont_do.check(HookPoint.POST_ACTION, {
    "object": tool_def.objects[0] if tool_def.objects else "unknown",
    "operation": tc["capability"],
    "result": str(result)[:500],
})
if verdict == Verdict.REJECT:
    # 回滚或警告
    pass
```

#### 1.3.3 非集变动追踪

在 Agent 中维护变动列表：

```python
class Agent:
    def __init__(self):
        self._non_set_changes: list[dict] = []

    def _track_non_set_change(self, action: str, rule_id: str,
                               reason: str, context: dict):
        self._non_set_changes.append({
            "time": datetime.now(UTC).isoformat(),
            "action": action,     # "add" | "hit" | "modify" | "remove"
            "rule_id": rule_id,
            "reason": reason,
            "context": context,
        })
```

在 `log_episode` 时传入：
```python
self.memory.log_episode(EpisodeEntry(
    ...
    non_set_changes=self._non_set_changes,  # 之前为空
))
```

#### 1.3.4 规则按对象划分的细化

当前 `dont-do/file-system.yaml` 已经是按对象划分的。需要：

1. **统一命名规范**：对象名与 `AgentObject.type` 对齐（见第二节）
2. **自动归类**：`add_rule()` 时根据 match.object 自动确定规则文件归属
3. **查询接口**：`dont_do.list_rules_by_object(object_type)` — 按对象类型查询规则

```python
def list_rules_by_object(self, object_type: str) -> list[Rule]:
    """按对象类型查询规则"""
    rules = []
    for chain in self._chains.values():
        for rule in chain:
            if rule.match.get("object") == object_type:
                rules.append(rule)
    return rules
```

### 1.4 改动量估算

| 文件 | 改动类型 | 行数 |
|------|---------|------|
| `agent/core.py` | 新增 DontDoEngine 集成 | ~80 行 |
| `agent/dont_do.py` | 新增 `list_rules_by_object()` | ~10 行 |
| `agent/memory.py` | 无改动（schema 已支持） | 0 |
| `dont-do/*.yaml` | 规范化 object 字段 | ~20 行 |

---

## 二、角色 (Role) + 观察 (Observe) 深度改进方案

### 2.1 现状诊断

`agent/core.py:129-139` 的 role 定义：
```python
role_text = (
    "你是一个编程助手。按照用户的任务指令逐步执行。\n\n"
    "当你需要使用工具时，必须用以下格式输出：\n..."
)
```

**核心问题**：Role 是纯文本字符串，没有结构化的对象关注列表和观察工具映射。

`_observe()` (line 348-371) 的实现：让 LLM 自由调用工具 → 拼接结果字符串。缺少：
- 对象识别：不知道 goal 涉及哪些对象
- 工具筛选：所有工具都给 LLM，而非只给相关观察工具
- 状态结构化：结果是文本拼接，不是结构化状态快照

`ToolRegistry.find_by_object()` 方法存在但 `_plan_goal()` 中从未调用。

### 2.2 改进方案

#### 2.2.1 对象模型

**新增文件**: `agent/objects.py`

```python
"""Agent object model — 代理对世界的认知模型."""

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class ObjectState:
    """单个对象的状态快照."""
    observed_at: str
    properties: dict  # e.g. {"exists": True, "size": 1024, "branch": "main"}


@dataclass
class AgentObject:
    """代理认知中的对象."""
    uri: str              # 统一资源标识 "file://src/main.py", "git://repo"
    type: str             # "file" | "directory" | "git-repo" | "database" | "service" | "process"
    display_name: str     # 人类可读名称
    state_before: ObjectState | None = None  # 操作前状态
    state_after: ObjectState | None = None   # 操作后状态
    observation_tools: list[str] = field(default_factory=list)  # 可观察此对象的工具
    manipulation_tools: list[str] = field(default_factory=list)  # 可操作此对象的工具
    parent: str | None = None  # 父对象 URI

    @property
    def state_changed(self) -> bool:
        if not self.state_before or not self.state_after:
            return False
        return self.state_before.properties != self.state_after.properties

    @property
    def diff(self) -> dict:
        """计算状态变化差异."""
        if not self.state_before or not self.state_after:
            return {}
        before = self.state_before.properties
        after = self.state_after.properties
        changes = {}
        all_keys = set(before.keys()) | set(after.keys())
        for k in all_keys:
            if before.get(k) != after.get(k):
                changes[k] = {"before": before.get(k), "after": after.get(k)}
        return changes
```

#### 2.2.2 角色结构化定义

**扩展 tool.md 格式或新增 role.md**:

```yaml
---
name: backend-developer
version: "1.0"
description: "后端开发助手，专注于代码、数据库和版本控制"
focus_objects:
  - type: file
    observation: [read_file, list_directory, search_content]
    manipulation: [write_file, delete_file, rename_file]
  - type: git-repo
    observation: [git_status, git_diff, git_log]
    manipulation: [git_commit, git_branch, git_checkout]
  - type: database
    observation: [db_describe, db_query_select]
    manipulation: [db_query_write, db_migrate]
behavior_rules:
  - "修改代码前先读文件"
  - "数据库写操作前先备份"
  - "commit 前运行测试"
dont_do:
  - object: database
    operations: [DROP, TRUNCATE]
    unless: "用户明确确认"
---

# 后端开发助手

你是一个后端开发助手...
```

#### 2.2.3 结构化观察流程

**改动文件**: `agent/core.py` — 重写 `_observe()`：

```python
async def _observe_structured(self, goal: str) -> dict[str, AgentObject]:
    """Phase 1 V2: 结构化观察。

    1. LLM 识别 goal 涉及的对象类型
    2. 根据角色定义找到每个对象对应的观察工具
    3. 系统性调用观察工具获取状态快照
    4. 返回 {uri: AgentObject} 映射
    """
    # Step 1: 识别对象
    obj_types = await self._identify_objects_in_goal(goal)
    # obj_types = ["file", "git-repo"]

    # Step 2: 从角色获取观察工具
    focus = self.role.get_focus_for_types(obj_types)
    # focus = {"file": ["read_file", "list_directory"], "git-repo": ["git_status"]}

    # Step 3: 让 LLM 使用限定工具集进行观察
    # 关键改进：不是给所有工具，而是只给每种对象类型的观察工具
    objects = {}
    for obj_type, obs_tools in focus.items():
        tools = self.registry.find_by_object(obj_type)
        obs_only = [t for t in tools if any(c.name in obs_tools for c in t.capabilities)]

        prompt = self.prompt_assembler.assemble(PromptInputs(
            role=f"观察所有 {obj_type} 类型对象的状态。使用提供的工具。完成后输出 <final>done</final>。",
            tool_summaries=format_tool_summary(obs_only),  # 只给观察工具
            task=f"目标: {goal}\n\n观察 {obj_type} 对象的当前状态。",
        ))

        resp = await retry(self._get_provider().complete, prompt, max_tokens=4096)
        tool_calls = self._parse_tool_calls(resp.content)

        for tc in tool_calls:
            tool_def = self.registry.get(tc["tool"])
            if tool_def:
                result = await self.executor.execute(
                    tool_def, tc["capability"], tc.get("params", {})
                )
                # 构建 AgentObject
                uri = self._resolve_object_uri(tc, result)
                objects[uri] = AgentObject(
                    uri=uri,
                    type=obj_type,
                    display_name=tc.get("params", {}).get("path", uri),
                    state_before=ObjectState(
                        observed_at=datetime.now(UTC).isoformat(),
                        properties=self._extract_state_properties(result),
                    ),
                    observation_tools=obs_tools,
                    manipulation_tools=self.role.get_manipulation_tools(obj_type),
                )

    return objects

async def _identify_objects_in_goal(self, goal: str) -> list[str]:
    """LLM 识别 goal 涉及哪些对象类型."""
    prompt = f"""分析以下目标涉及哪些对象类型。

目标: {goal}

可用对象类型: {', '.join(self.role.known_object_types)}

只回复 JSON 数组: ["type1", "type2"]"""
    resp = await self._get_provider().complete(prompt, max_tokens=100)
    try:
        return json.loads(resp.content.strip())
    except json.JSONDecodeError:
        return self.role.default_object_types

def _extract_state_properties(self, tool_result) -> dict:
    """从工具结果中提取结构化的状态属性."""
    if isinstance(tool_result, dict):
        return tool_result
    if isinstance(tool_result, str):
        # 尝试解析 JSON
        try:
            return json.loads(tool_result)
        except (json.JSONDecodeError, ValueError):
            return {"raw_output": tool_result[:500]}
    return {"raw_output": str(tool_result)[:500]}
```

### 2.3 改动量估算

| 文件 | 改动类型 | 行数 |
|------|---------|------|
| `agent/objects.py` | **新增** | ~120 行 |
| `agent/core.py` | 重写 `_observe()` + 新增辅助方法 | ~150 行 |
| `agent/role.py` | **新增** 角色定义和管理 | ~100 行 |
| `agent/prompt.py` | `PromptInputs` 新增 `role_focus` 字段 | ~15 行 |

---

## 三、纠正 (用户纠正→非集团环) 深度改进方案

### 3.1 现状诊断

当前中断处理仅 `agent/interrupt.py` 中的 SIGINT 捕获。用户无法：
- 在执行过程中提供结构化纠正
- 让纠正内容自动生成 dont-do 规则
- 让纠正内容驱动重新规划

### 3.2 改进方案

#### 3.2.1 纠正数据模型

**新增文件**: `agent/correction.py`

```python
"""Correction system — 用户纠正的结构化表示和处理."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum


class CorrectionSource(Enum):
    USER = "user"
    AUTO_VERIFY = "auto_verify"
    RULE_ENGINE = "rule_engine"


class Severity(Enum):
    BLOCKER = "blocker"   # 必须修复才能继续
    WARNING = "warning"   # 建议修复
    INFO = "info"         # 仅供参考


@dataclass
class Correction:
    """一次纠正记录."""
    id: str
    timestamp: str
    source: CorrectionSource
    target_uri: str           # 被纠正的对象 URI，如 "file://src/main.py"
    target_step: str | None   # 被纠正的执行步骤
    issue_type: str           # "wrong_action" | "wrong_object" | "wrong_plan"
                              # | "wrong_result" | "missing_step" | "extra_step"
    description: str          # 问题描述
    suggestion: str           # 建议的修正方式
    severity: Severity
    generated_rule_id: str | None = None  # 由此纠正生成的非集规则 ID
    applied: bool = False

    def to_dont_do_rule_context(self) -> dict:
        """转换为 DontDoEngine 可以理解的上下文，用于规则匹配."""
        return {
            "object": self.target_uri,
            "issue": self.issue_type,
            "description": self.description,
        }
```

#### 3.2.2 纠正处理器

**在 `agent/core.py` 中新增**:

```python
class Agent:
    def __init__(self):
        self._corrections: list[Correction] = []
        self._pending_corrections: list[Correction] = []

    async def _check_for_corrections(self) -> list[Correction]:
        """检查是否有新的用户纠正。

        在以下时机检查：
        - 每次迭代开始前
        - 工具执行出错后
        - 验证失败后

        用户可通过以下方式提供纠正：
        - CLI 输入（交互模式）
        - 文件监听（watch 模式，监听 corrections/ 目录）
        - API 接口（HTTP server 模式）
        """
        # 监听 corrections/ 目录中的新文件
        corrections_dir = Path("corrections")
        if corrections_dir.exists():
            for f in sorted(corrections_dir.glob("*.yaml")):
                correction = self._parse_correction_file(f)
                if correction and not correction.applied:
                    self._pending_corrections.append(correction)
                    f.unlink()  # 消费后删除

        return self._pending_corrections

    def _parse_correction_file(self, path: Path) -> Correction | None:
        """解析纠正文件."""
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            return Correction(
                id=data.get("id", f"corr-{uuid.uuid4().hex[:8]}"),
                timestamp=datetime.now(UTC).isoformat(),
                source=CorrectionSource.USER,
                target_uri=data["target"],
                target_step=data.get("step"),
                issue_type=data["issue_type"],
                description=data["description"],
                suggestion=data.get("suggestion", ""),
                severity=Severity(data.get("severity", "blocker")),
            )
        except Exception as e:
            logger.error("correction_parse_error", path=str(path), error=str(e))
            return None

    async def _apply_correction(self, correction: Correction) -> Rule | None:
        """应用纠正：生成非集规则 + 调整计划."""
        # Step 1: LLM 分析纠正 → 生成 dont-do 规则
        rule = await self._correction_to_rule(correction)
        if rule:
            # Step 2: 加入运行时引擎
            self.dont_do.add_rule(rule)
            # Step 3: 持久化
            self._persist_dont_do_rule(rule)
            # Step 4: 记录关联
            correction.generated_rule_id = rule.id
            # Step 5: 追踪变动
            self._track_non_set_change(
                "add", rule.id,
                f"用户纠正: {correction.description[:100]}",
                correction.to_dont_do_rule_context()
            )

        correction.applied = True
        self._corrections.append(correction)
        return rule

    async def _correction_to_rule(self, correction: Correction) -> Rule | None:
        """LLM 分析纠正内容，生成结构化 dont-do 规则."""
        prompt = f"""基于以下用户纠正，生成一个 dont-do 规则（YAML 格式）。

用户纠正:
- 对象: {correction.target_uri}
- 问题类型: {correction.issue_type}
- 问题描述: {correction.description}
- 建议: {correction.suggestion}

规则要求:
- id: 使用格式 "corr-{{short_hash}}"
- description: 清晰描述禁止什么
- hook: 选择合适的 hook 点 [PLAN, PRE_ACTION, POST_ACTION]
- match: 包含 object 和 operation 条件
- action: REJECT 或 WARN
- message: 给用户的解释信息

只输出有效的 YAML，不要包含其他内容:
```yaml
rules:
  - id: corr-xxxxx
    description: "..."
    hook: [PRE_ACTION]
    match:
      object: "..."
      operation: "..."
    action: REJECT
    message: "..."
```"""
        resp = await self._get_provider().complete(prompt, max_tokens=500)
        try:
            text = resp.content.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[:-3]
            data = yaml.safe_load(text)
            rule_data = data["rules"][0]
            return Rule(
                id=rule_data["id"],
                description=rule_data["description"],
                hook=rule_data["hook"],
                match=rule_data["match"],
                action=rule_data["action"],
                message=rule_data["message"],
                source=f"correction:{correction.id}",
            )
        except Exception as e:
            logger.error("correction_to_rule_failed", error=str(e))
            return None

    def _persist_dont_do_rule(self, rule: Rule) -> Path:
        """持久化 dont-do 规则到文件.

        按对象的 type 确定保存目录.
        """
        obj_type = rule.match.get("object", "general")
        target_dir = Path("dont-do") / obj_type
        target_dir.mkdir(parents=True, exist_ok=True)

        # 如果文件已存在，追加规则；否则创建新文件
        existing = list(target_dir.glob("*.yaml"))
        if existing:
            path = existing[0]
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            data.setdefault("rules", []).append({
                "id": rule.id,
                "description": rule.description,
                "hook": rule.hook,
                "match": rule.match,
                "action": rule.action,
                "message": rule.message,
                "source": rule.source,
            })
            path.write_text(yaml.dump(data, allow_unicode=True, default_flow_style=False),
                           encoding="utf-8")
        else:
            path = target_dir / f"{obj_type}.yaml"
            path.write_text(yaml.dump({
                "rules": [{
                    "id": rule.id,
                    "description": rule.description,
                    "hook": rule.hook,
                    "match": rule.match,
                    "action": rule.action,
                    "message": rule.message,
                    "source": rule.source,
                }]
            }, allow_unicode=True, default_flow_style=False), encoding="utf-8")

        return path
```

#### 3.2.3 纠正驱动重规划

当存在用户纠正时，重规划需要：
1. 将纠正内容注入 planning prompt
2. 让 LLM 避开已被纠正的方案
3. 参考纠正中的建议方向

```python
async def _replan_with_corrections(self, goal: str, observation: str,
                                     corrections: list[Correction],
                                     conversation: str) -> list[dict]:
    """考虑纠正内容后重新规划."""
    corrections_text = "\n".join(
        f"- [{c.severity.value}] {c.target_uri}: {c.description}\n  建议: {c.suggestion}"
        for c in corrections
    )

    prompt = self.prompt_assembler.assemble(PromptInputs(
        role=(
            "基于观察结果和用户纠正，重新制定执行计划。"
            "避开用户纠正中指出的问题，采纳用户建议。"
            "输出 JSON 格式的计划数组。"
        ),
        task=(
            f"目标: {goal}\n\n"
            f"观察结果:\n{observation}\n\n"
            f"用户纠正（必须遵守）:\n{corrections_text}\n\n"
            f"之前的执行记录:\n{conversation[-2000:]}"
        ),
    ))

    resp = await retry(self._get_provider().complete, prompt, max_tokens=2048)
    return self._parse_plan_json(resp.content)
```

### 3.3 改动量估算

| 文件 | 改动类型 | 行数 |
|------|---------|------|
| `agent/correction.py` | **新增** | ~80 行 |
| `agent/core.py` | 新增纠正处理逻辑 | ~120 行 |

---

## 四、反馈/验证 (Verify) 深度改进方案

### 4.1 现状诊断

`agent/core.py:404-412` 的 `_verify_goal()`:
```python
async def _verify_goal(self, goal: str, conversation: str) -> bool:
    prompt = self.prompt_assembler.assemble(PromptInputs(
        role="根据执行结果判断目标是否已达成。只回复 YES 或 NO。",
        task=f"目标: {goal}\n\n执行结果:\n{conversation[-3000:]}",
    ))
    resp = await retry(provider.complete, prompt, max_tokens=16)
    return "YES" in resp.content.upper()
```

**问题**：
1. **不观察对象终态** — 只靠对话历史做判断，对话历史可能过时
2. **不对比初始状态** — 不知道发生了什么变化
3. **不验证每步 verify 条件** — plan 中的 `verify` 字段被完全忽略
4. **没有证据** — 只返回 bool，无法解释为什么判定成功/失败

### 4.2 改进方案

#### 4.2.1 结构化验证流程

```python
async def _verify_goal_v2(
    self,
    goal: str,
    plan: list[dict],
    objects_before: dict[str, AgentObject],
    conversation: str,
) -> dict:
    """Phase 4 V2: 结构化验证。

    Returns:
        {
            "achieved": bool,
            "confidence": float,       # 0.0 - 1.0
            "state_diff": {...},       # 对象状态变化
            "step_results": [...],     # 每步验证结果
            "evidence": {...},         # 证据
            "unmet_criteria": [...],   # 未满足的条件
        }
    """
    # Step 1: 重新观察所有相关对象的当前状态
    objects_after = await self._observe_structured(goal)

    # Step 2: 将 before → after 状态更新到 AgentObject
    for uri, obj in objects_before.items():
        if uri in objects_after:
            obj.state_after = objects_after[uri].state_before

    # Step 3: 计算状态差异
    state_diff = {}
    for uri, obj in objects_before.items():
        if obj.state_changed:
            state_diff[uri] = obj.diff

    # Step 4: 验证 plan 中每步的 verify 条件
    step_results = []
    for step in plan:
        if step.get("verify") and step["verify"] != "manual":
            ok, evidence = await self._verify_step_condition(
                step["verify"], objects_before
            )
            step_results.append({
                "step": step.get("action", str(step))[:200],
                "verify_condition": step["verify"],
                "met": ok,
                "evidence": evidence,
            })

    # Step 5: LLM 综合判断
    verification_prompt = self._build_verification_prompt(
        goal, state_diff, step_results, objects_before
    )
    resp = await self._get_provider().complete(
        verification_prompt, max_tokens=500
    )
    llm_judgment = self._parse_verification_response(resp.content)

    # Step 6: 汇总
    all_steps_ok = all(r["met"] for r in step_results) if step_results else True
    return {
        "achieved": llm_judgment["achieved"] and all_steps_ok,
        "confidence": llm_judgment.get("confidence", 0.5),
        "state_diff": state_diff,
        "step_results": step_results,
        "evidence": {
            "objects_after": {
                uri: obj.state_after.properties if obj.state_after else {}
                for uri, obj in objects_before.items()
            }
        },
        "unmet_criteria": llm_judgment.get("unmet_criteria", []),
        "explanation": llm_judgment.get("explanation", ""),
    }

async def _verify_step_condition(self, condition: str,
                                  objects: dict[str, AgentObject]) -> tuple[bool, str]:
    """验证单个步骤的验证条件.

    条件可以是:
    - 自然语言: "文件 src/config.py 已创建"
    - 表达式: "file://src/config.py.exists == true"
    - 比较: "file://src/config.py.size > 0"
    """
    # 对于自然语言条件，使用 LLM 判断
    objects_state = {
        uri: obj.state_after.properties if obj.state_after
        else obj.state_before.properties if obj.state_before
        else {}
        for uri, obj in objects.items()
    }

    prompt = f"""判断以下条件是否满足。

条件: {condition}

当前对象状态:
{json.dumps(objects_state, ensure_ascii=False, indent=2)}

只回复 YES 或 NO，然后简短说明。"""
    resp = await self._get_provider().complete(prompt, max_tokens=100)
    content = resp.content.upper()
    return "YES" in content, resp.content[:200]

def _build_verification_prompt(self, goal: str, diff: dict,
                                 step_results: list, objects: dict) -> str:
    """构建结构化验证 prompt."""
    diff_text = json.dumps(diff, ensure_ascii=False, indent=2) if diff else "(无变化)"
    steps_text = "\n".join(
        f"- [{('OK' if r['met'] else 'FAIL')}] {r['step']}"
        for r in step_results
    ) if step_results else "(无步骤验证条件)"

    return self.prompt_assembler.assemble(PromptInputs(
        role=(
            "你是验证器。基于证据判断目标是否已达成。\n"
            "输出 JSON:\n"
            '{"achieved": true/false, "confidence": 0.0-1.0, '
            '"unmet_criteria": [...], "explanation": "..."}'
        ),
        task=(
            f"目标: {goal}\n\n"
            f"对象状态变化:\n{diff_text}\n\n"
            f"步骤验证结果:\n{steps_text}\n\n"
            f"如果未达成，列出未满足的具体条件。"
        ),
    ))

def _parse_verification_response(self, response: str) -> dict:
    """解析验证响应."""
    try:
        text = response.strip()
        if "{" in text and "}" in text:
            text = text[text.find("{"):text.rfind("}") + 1]
        return json.loads(text)
    except json.JSONDecodeError:
        achieved = "YES" in response.upper()
        return {
            "achieved": achieved,
            "confidence": 0.3,
            "unmet_criteria": [],
            "explanation": response[:300],
        }
```

#### 4.2.2 在 Goal Mode 中集成

```python
async def goal_run(self, goal: str) -> dict:
    # ... 前面相同 ...

    objects_before = {}  # 记录初始状态

    for iteration in range(max_iterations):
        await self.interrupt.check()

        if iteration == 0:
            # Phase 1: 结构化观察
            objects_before = await self._observe_structured(goal)

            # Phase 2: 基于对象状态制定计划
            plan = await self._plan_goal_v2(goal, objects_before, conversation)
        else:
            # 检查用户纠正
            corrections = await self._check_for_corrections()
            for corr in corrections:
                await self._apply_correction(corr)

            # 重新规划（考虑纠正）
            plan = await self._replan_with_corrections(
                goal, objects_before, corrections, conversation
            )

        # Phase 3: 执行
        for step in plan:
            # ... 执行逻辑 ...
            pass

        # Phase 4: 结构化验证
        verification = await self._verify_goal_v2(
            goal, plan, objects_before, conversation
        )

        if verification["achieved"] and verification["confidence"] >= 0.7:
            break

        # 未达成：记录未满足条件 → 下一轮重规划
        conversation += (
            f"\n[Verification Failed] "
            f"confidence={verification['confidence']}, "
            f"unmet={verification['unmet_criteria']}"
        )
```

### 4.3 改动量估算

| 文件 | 改动类型 | 行数 |
|------|---------|------|
| `agent/core.py` | 重写 `_verify_goal()` + 新增辅助方法 | ~200 行 |

---

## 五、TODO 导向完整闭环 深度改进方案

### 5.1 现状诊断

TODO 模式（`agent/core.py:95-237`）是差距最大的部分。当前流程：

```
收到 TODO → 构建 prompt → LLM 响应 → 解析工具调用 → 执行 → 循环(最多3次)
```

缺失：
1. **验收标准分析** — 不检查 TODO 是否清晰、是否有验收标准
2. **主动询问** — 发现不合理或缺失时不询问用户
3. **对象状态观察** — 不观察 TODO 涉及的对象初始状态
4. **终态比对** — 完成后不对比验收标准
5. **最终验证** — 没有 verify 步骤，LLM 不调工具了就算完成

### 5.2 改进方案

#### 5.2.1 TODO 分析器

```python
async def _analyze_todo(self, task: str) -> dict:
    """分析 TODO 的完整性和清晰度。

    返回:
        {
            "is_clear": bool,
            "has_acceptance_criteria": bool,
            "objects_involved": [{"uri": "...", "type": "..."}],
            "acceptance_criteria": ["criterion 1", "criterion 2"],
            "issues": [
                {"type": "unclear|missing|unreasonable|ambiguous",
                 "severity": "blocker|warning|info",
                 "description": "...",
                 "suggested_fix": "..."}
            ],
            "suggested_approach": "简要建议的执行方式",
        }
    """
    prompt = f"""分析以下 TODO 任务。

TODO: {task}

请判断：
1. 任务描述是否清晰？需要做什么是否明确？
2. 是否包含验收标准？如何判断任务完成？
3. 任务涉及哪些对象（文件、数据库、服务等）？
4. 任务是否合理？有没有明显不合理的地方？
5. 如果有缺失信息，具体是什么？

输出 JSON（不要包含其他内容）:
{{
  "is_clear": true/false,
  "has_acceptance_criteria": true/false,
  "objects_involved": [{{"uri": "file://path/to/file", "type": "file"}}],
  "acceptance_criteria": ["完成标准1", "完成标准2"],
  "issues": [
    {{"type": "unclear", "severity": "blocker", "description": "...", "suggested_fix": "..."}}
  ],
  "suggested_approach": "..."
}}"""
    resp = await self._get_provider().complete(prompt, max_tokens=1000)
    try:
        text = resp.content.strip()
        if "{" in text and "}" in text:
            text = text[text.find("{"):text.rfind("}") + 1]
        return json.loads(text)
    except json.JSONDecodeError:
        return {
            "is_clear": True,
            "has_acceptance_criteria": False,
            "objects_involved": [],
            "acceptance_criteria": [],
            "issues": [],
            "suggested_approach": "",
        }
```

#### 5.2.2 主动询问机制

```python
async def _ask_user_for_clarification(self, analysis: dict) -> dict | None:
    """如果 TODO 有问题，生成问题并获取用户回答。

    返回用户补充后的信息，或 None（用户选择忽略）。
    """
    blocking_issues = [
        i for i in analysis["issues"]
        if i["severity"] == "blocker"
    ]

    if not blocking_issues and analysis["is_clear"]:
        return None

    # 构建问题
    questions = []
    for issue in analysis["issues"]:
        q = f"- [{issue['severity']}] {issue['description']}"
        if issue.get("suggested_fix"):
            q += f"\n  建议: {issue['suggested_fix']}"
        questions.append(q)

    if not analysis["has_acceptance_criteria"]:
        questions.append(
            "- [blocker] 缺少验收标准。请问如何判断任务已完成？"
        )

    question_text = "\n".join(questions)
    full_question = (
        f"TODO 分析发现问题:\n\n{question_text}\n\n"
        f"请补充说明，或输入 'skip' 继续执行（可能结果不如预期）。"
    )

    # 根据运行模式获取用户输入
    # CLI 模式: print + input()
    # API 模式: 返回问题，等待回调
    # 非交互模式: 记录 warning，继续执行

    if self._interactive:
        print(f"\n{'='*60}")
        print(full_question)
        print(f"{'='*60}")
        user_input = input("> ").strip()
        if user_input.lower() == "skip":
            return None
        return {"user_response": user_input, "questions": questions}
    else:
        logger.warning("todo_clarification_needed",
                        task=analysis.get("task", ""),
                        issues=len(analysis["issues"]))
        return None
```

#### 5.2.3 增强版 TODO 执行

```python
async def run_v2(self, task_description: str) -> dict:
    """TODO 模式 V2 — 完整闭环."""
    task_id = str(uuid.uuid4())[:8]
    tools_used: list[str] = []
    steps_taken = 0
    start_time = time.time()
    last_error = ""

    logger.info("task_start_v2", task_id=task_id, task=task_description[:200])

    # ===== Phase 0: 分析 TODO =====
    analysis = await self._analyze_todo(task_description)

    # 记录初始分析
    acceptance_criteria = analysis.get("acceptance_criteria", [])
    objects_involved = analysis.get("objects_involved", [])

    # ===== Phase 0.5: 询问用户（如有问题） =====
    if analysis["issues"] or not analysis["has_acceptance_criteria"]:
        user_clarification = await self._ask_user_for_clarification(analysis)
        if user_clarification:
            # 将用户补充合并到任务描述
            task_description = (
                f"{task_description}\n\n"
                f"用户补充说明:\n{user_clarification['user_response']}"
            )
            # 重新分析以获得更新后的验收标准
            analysis = await self._analyze_todo(task_description)
            acceptance_criteria = analysis.get("acceptance_criteria", [])

    # ===== Phase 1: 观察对象初始状态 =====
    objects_before = {}
    for obj_info in objects_involved[:5]:  # 最多观察5个对象
        try:
            obj_type = obj_info["type"]
            uri = obj_info["uri"]
            obs_tools = self.registry.find_by_object(obj_type)
            if obs_tools:
                # 使用匹配的观察工具
                pass  # 具体实现取决于工具可用性
        except Exception:
            pass

    # ===== Phase 2-3: 执行循环 =====
    max_iterations = self.config["agent"].get("max_loop_iterations", 3)
    conversation = ""
    result_summary = ""

    for iteration in range(max_iterations):
        await self.interrupt.check()

        # 检查用户中途纠正
        corrections = await self._check_for_corrections()
        for corr in corrections:
            await self._apply_correction(corr)

        # 构建 prompt（含验收标准）
        tools = self.registry.list_all()
        relevant_objects = list(set(
            obj for t in tools for obj in t.objects
        ))

        criteria_text = ""
        if acceptance_criteria:
            criteria_text = (
                "\n\n验收标准（必须全部满足）:\n" +
                "\n".join(f"- {c}" for c in acceptance_criteria)
            )

        role_text = (
            "你是一个编程助手。按照用户的任务指令逐步执行。\n\n"
            "当你需要使用工具时，必须用以下格式输出：\n"
            "<function_call>\n"
            "<name>工具名称</name>\n"
            "<capability>能力名称</capability>\n"
            "<parameters>{\"参数名\": \"参数值\"}</parameters>\n"
            "</function_call>\n\n"
            "收到工具结果后，根据结果继续执行或给出最终回答。\n"
            "如果任务已完成，给出最终回答，不要继续调用工具。\n"
            "完成所有验收标准后再结束。"
        )

        prompt = self.prompt_assembler.assemble(PromptInputs(
            role=role_text,
            dont_do_rules=self.security.get_constraints_prompt(relevant_objects),
            tool_summaries=format_tool_summary(tools),
            task=task_description + criteria_text,
            conversation_summary=result_summary if iteration > 0 else "",
            recent_messages=conversation,
        ))

        # LLM 调用
        provider = self._get_provider()
        try:
            response = await retry(
                provider.complete, prompt, max_tokens=4096,
                context={"task_id": task_id, "iteration": iteration + 1},
            )
        except Exception as e:
            last_error = str(e)
            break

        conversation += f"\n[Step {iteration + 1}] {response.content[:500]}"

        # 解析工具调用
        tool_calls = self._parse_tool_calls(response.content)
        if not tool_calls:
            result_summary = response.content[:500]
            break

        # 执行工具
        for tc in tool_calls:
            await self.interrupt.check()
            # PRE_ACTION dont-do 检查
            verdict, msg = self.dont_do.check(HookPoint.PRE_ACTION, {
                "object": tc.get("object", "unknown"),
                "operation": tc["capability"],
                "tool": tc["tool"],
            })
            if verdict == Verdict.REJECT:
                conversation += f"\n[Blocked] {msg}"
                self._track_non_set_change("hit", "pre_action_block", msg, tc)
                continue

            try:
                tool_def = self.registry.get(tc["tool"])
                if not tool_def:
                    continue
                result = await self.executor.execute(
                    tool_def, tc["capability"], tc.get("params", {})
                )
                tools_used.append(f"{tc['tool']}.{tc['capability']}")
                steps_taken += 1
                conversation += (
                    f"\n[Result from {tc['tool']}.{tc['capability']}]: "
                    f"{str(result)[:500]}"
                )
            except InterruptSignal:
                raise
            except Exception as e:
                last_error = str(e)
                conversation += f"\n[Error] {tc['tool']}.{tc['capability']}: {e}"

    # ===== Phase 4: 验证验收标准 =====
    verification = None
    if acceptance_criteria:
        verification = await self._verify_against_criteria(
            acceptance_criteria, conversation
        )

    # ===== 记录 episode =====
    success = (
        not last_error
        and (verification["all_met"] if verification else True)
    )

    self.memory.log_episode(EpisodeEntry(
        task_id=task_id,
        task_type="todo",
        task_summary=task_description[:200],
        tools_used=list(set(tools_used)),
        steps=steps_taken,
        success=success,
        error=last_error,
        non_set_changes=self._non_set_changes,
    ))

    # ... consolidation ...

    return {
        "task_id": task_id,
        "success": success,
        "steps": steps_taken,
        "tools_used": list(set(tools_used)),
        "duration_seconds": round(time.time() - start_time, 1),
        "result": result_summary,
        "error": last_error,
        "analysis": analysis,
        "verification": verification,
    }

async def _verify_against_criteria(self, criteria: list[str],
                                     conversation: str) -> dict:
    """逐条比对验收标准."""
    results = []
    for criterion in criteria:
        prompt = f"""基于执行记录，判断以下验收标准是否满足。

验收标准: {criterion}
执行记录（最后 3000 字符）: {conversation[-3000:]}

只回复 YES 或 NO，然后简短说明原因。"""
        resp = await self._get_provider().complete(prompt, max_tokens=100)
        content = resp.content.upper()
        results.append({
            "criterion": criterion,
            "met": "YES" in content,
            "evidence": resp.content[:200],
        })

    return {
        "all_met": all(r["met"] for r in results),
        "criteria_results": results,
        "met_count": sum(1 for r in results if r["met"]),
        "total_count": len(results),
    }
```

### 5.3 改动量估算

| 文件 | 改动类型 | 行数 |
|------|---------|------|
| `agent/core.py` | 重写 `run()` → `run_v2()` | ~250 行 |

---

## 六、记忆-对象状态变化 深度改进方案

### 6.1 现状诊断

当前 `EpisodeEntry` 不记录对象状态变化。SQLite episodic 表有 `non_set_changes` 列但无对象状态列。

### 6.2 改进方案

#### 6.2.1 扩展数据模型

**改动文件**: `agent/memory.py`

```python
@dataclass
class EpisodeEntry:
    task_id: str
    task_type: str
    task_summary: str
    tools_used: list[str] = field(default_factory=list)
    steps: int = 0
    success: bool = False
    error: str = ""
    non_set_changes: list[str] = field(default_factory=list)
    timestamp: str = ""
    # === 新增 ===
    objects_before: dict = field(default_factory=dict)   # {uri: state_properties}
    objects_after: dict = field(default_factory=dict)    # {uri: state_properties}
    object_changes: list[dict] = field(default_factory=list)
    # [{"uri": "...", "field": "size", "before": 1024, "after": 2048}]
```

#### 6.2.2 SQLite Schema 升级

```sql
-- 新增列
ALTER TABLE episodic ADD COLUMN objects_before TEXT DEFAULT '{}';
ALTER TABLE episodic ADD COLUMN objects_after TEXT DEFAULT '{}';
ALTER TABLE episodic ADD COLUMN object_changes TEXT DEFAULT '[]';

-- 为对象 URI 建立索引，支持按对象查询历史
CREATE INDEX IF NOT EXISTS idx_episodic_task_type ON episodic(task_type);
```

**但 SQLite 不支持 `ALTER TABLE ADD COLUMN IF NOT EXISTS`**，所以要用 try/except：

```python
def _migrate_schema(self):
    """增量 schema 迁移."""
    migrations = [
        "ALTER TABLE episodic ADD COLUMN objects_before TEXT DEFAULT '{}'",
        "ALTER TABLE episodic ADD COLUMN objects_after TEXT DEFAULT '{}'",
        "ALTER TABLE episodic ADD COLUMN object_changes TEXT DEFAULT '[]'",
    ]
    for sql in migrations:
        try:
            self.conn.execute(sql)
            logger.info("schema_migration", sql=sql[:60])
        except sqlite3.OperationalError:
            pass  # 列已存在
    self.conn.commit()
```

#### 6.2.3 按对象查询历史

新增查询能力——这对于"对象状态变化"记忆的核心价值：

```python
def get_object_history(self, uri: str, limit: int = 10) -> list[dict]:
    """查询某个对象在所有 episode 中的状态变化历史."""
    rows = self.conn.execute(
        """SELECT id, timestamp, task_type, task_summary, success,
                  objects_before, objects_after, object_changes
           FROM episodic
           WHERE objects_before LIKE ? OR objects_after LIKE ?
           ORDER BY timestamp DESC
           LIMIT ?""",
        (f"%{uri}%", f"%{uri}%", limit),
    ).fetchall()

    history = []
    for row in rows:
        changes = json.loads(row["object_changes"])
        obj_changes = [c for c in changes if c.get("uri") == uri]
        history.append({
            "task_id": row["id"],
            "timestamp": row["timestamp"],
            "task_type": row["task_type"],
            "task_summary": row["task_summary"],
            "success": bool(row["success"]),
            "changes": obj_changes,
        })
    return history
```

#### 6.2.4 Agent Loop 中捕获对象状态

```python
class Agent:
    def _capture_object_states(self, objects: dict[str, AgentObject]) -> tuple[dict, dict, list]:
        """从 AgentObject 字典中提取可序列化的状态快照."""
        before = {}
        after = {}
        changes = []

        for uri, obj in objects.items():
            if obj.state_before:
                before[uri] = obj.state_before.properties
            if obj.state_after:
                after[uri] = obj.state_after.properties
            if obj.state_changed:
                changes.extend([
                    {"uri": uri, "field": k, "before": v["before"], "after": v["after"]}
                    for k, v in obj.diff.items()
                ])

        return before, after, changes

    # 在 log_episode 时使用:
    objects_before, objects_after, object_changes = self._capture_object_states(
        self._observed_objects
    )
    self.memory.log_episode(EpisodeEntry(
        ...
        objects_before=objects_before,
        objects_after=objects_after,
        object_changes=object_changes,
    ))
```

### 6.3 改动量估算

| 文件 | 改动类型 | 行数 |
|------|---------|------|
| `agent/memory.py` | 扩展 `EpisodeEntry` + schema 迁移 + 新增查询 | ~80 行 |
| `agent/core.py` | 在 run/goal_run 中捕获对象状态 | ~30 行 |

---

## 七、记忆-非集变动 深度改进方案

### 7.1 现状诊断

`EpisodeEntry.non_set_changes` 字段存在但从未被赋值。改进方案已在第一节中详细说明（`_track_non_set_change()` 方法 + 在 `log_episode` 时传入）。

### 7.2 补充：非集变动的查询和分析

```python
def get_non_set_history(self, limit: int = 20) -> list[dict]:
    """查询所有非集变动历史."""
    rows = self.conn.execute(
        """SELECT id, timestamp, task_type, non_set_changes
           FROM episodic
           WHERE non_set_changes != '[]'
           ORDER BY timestamp DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()

    history = []
    for row in rows:
        changes = json.loads(row["non_set_changes"])
        for change in changes:
            change["task_id"] = row["id"]
            change["task_type"] = row["task_type"]
            history.append(change)
    return history

def get_rules_by_object(self, object_type: str) -> list[dict]:
    """查询与特定对象类型相关的非集变动."""
    rows = self.conn.execute(
        """SELECT id, timestamp, non_set_changes
           FROM episodic
           WHERE non_set_changes != '[]'
           ORDER BY timestamp DESC""",
    ).fetchall()

    related = []
    for row in rows:
        changes = json.loads(row["non_set_changes"])
        for change in changes:
            ctx = change.get("context", {})
            if ctx.get("object", "").startswith(object_type):
                related.append(change)
    return related
```

### 7.3 改动量估算

| 文件 | 改动类型 | 行数 |
|------|---------|------|
| `agent/memory.py` | 新增非集查询方法 | ~40 行 |
| `agent/core.py` | 已计入第一节 | — |

---

## 八、文献格式 + 渐进式披露 深度改进方案

### 8.1 概述

原 IDEA 中的最后一条：**"强制性的文献格式和渐进式披露必须做进系统里面"**。

这不是一个独立模块，而是横切关注点——它影响：
- Prompt 组装（输出格式约束注入）
- 输出验证（格式合规检查）
- Role 定义（角色特定的格式要求）
- 系统级约束（不可被覆盖的格式规则）

### 8.2 改进方案

#### 8.2.1 输出格式规则引擎

**新增文件**: `agent/output_format.py`

```python
"""Output format rules — 强制性的输出文献格式和渐进式披露."""

from dataclasses import dataclass, field
from enum import Enum
import re


class DisclosureLevel(Enum):
    """渐进式披露的层次."""
    SUMMARY = "summary"       # 一句话总结
    KEY_DETAILS = "details"   # 关键细节
    FULL = "full"             # 完整说明


@dataclass
class CitationRule:
    """引用格式规则."""
    name: str
    pattern: str              # 正则或模板
    description: str
    example: str
    required: bool = True     # 是否强制执行


@dataclass
class OutputFormatProfile:
    """输出格式配置文件."""
    name: str
    citation_rules: list[CitationRule] = field(default_factory=list)
    disclosure_required: bool = True
    section_separator: str = "---"
    report_format: str = "action_report"  # "action_report" | "none"


# === 预定义的引用格式规则 ===

FILE_REFERENCE = CitationRule(
    name="file_reference",
    pattern=r"(?:[\w\-]+/)*[\w\-]+\.[a-z]{1,6}(?::\d+)?",
    description="引用文件时使用 path/to/file:line_number 格式",
    example="src/auth.py:42",
    required=True,
)

FUNCTION_REFERENCE = CitationRule(
    name="function_reference",
    pattern=r"[\w]+(?:\.[\w]+)*\(\)",
    description="引用函数时使用 module.function_name() 格式",
    example="auth.login()",
    required=False,
)

CONFIG_REFERENCE = CitationRule(
    name="config_reference",
    pattern=r"config\.[\w.]+",
    description="引用配置时使用 config.key.subkey 格式",
    example="config.database.host",
    required=False,
)

DEFAULT_FORMAT_PROFILE = OutputFormatProfile(
    name="default",
    citation_rules=[FILE_REFERENCE, FUNCTION_REFERENCE, CONFIG_REFERENCE],
    disclosure_required=True,
    section_separator="---",
    report_format="action_report",
)


class OutputFormatManager:
    """输出格式管理器.

    双重作用：
    1. 在 prompt 中注入格式要求（约束 LLM 输出）
    2. 验证 LLM 输出是否符合格式规范（后验检查）
    """

    def __init__(self, profile: OutputFormatProfile = DEFAULT_FORMAT_PROFILE):
        self.profile = profile
        self._violations: list[dict] = []

    # ——— Prompt 注入 ———

    def get_format_prompt(self) -> str:
        """生成注入到 system prompt 的格式要求."""
        rules_text = []
        for rule in self.profile.citation_rules:
            tag = "【强制】" if rule.required else "【建议】"
            rules_text.append(
                f"{tag} {rule.description}\n"
                f"  格式: {rule.pattern}\n"
                f"  示例: {rule.example}"
            )

        disclosure_text = ""
        if self.profile.disclosure_required:
            disclosure_text = f"""
## 渐进式披露要求

回答问题时必须遵循以下层次结构，用 `{self.profile.section_separator}` 分隔：

1. **总结层**: 1-2 句话概括结论
2. **关键细节层**: 列出核心论据或关键步骤
3. **完整说明层**: 详细的解释和背景信息（仅在需要时提供）

示例格式:
```
文件已成功修改。

---

- 修改了 src/auth.py:42 的 login() 函数
- 添加了密码验证逻辑
- 更新了对应的测试

---

完整的修改包括...（详细说明）
```
"""

        report_text = ""
        if self.profile.report_format == "action_report":
            report_text = """
## 行动报告格式

每个工具调用完成后，必须输出以下格式的报告:
<action_report>
<action>执行了什么操作</action>
<result>操作结果（一句话）</result>
<evidence>验证方式 / 证据</evidence>
</action_report>
"""

        return f"""## 输出格式规范（系统级约束，不可违反）

{rules_text}
{disclosure_text}
{report_text}
"""

    # ——— 输出验证 ———

    def validate(self, response: str) -> dict:
        """验证 LLM 输出是否符合格式规范."""
        self._violations = []
        issues = []

        # 检查引用的文件引用格式
        for rule in self.profile.citation_rules:
            if rule.required:
                self._check_citation_compliance(response, rule, issues)

        # 检查渐进式披露
        if self.profile.disclosure_required:
            self._check_disclosure_compliance(response, issues)

        # 检查行动报告
        if self.profile.report_format == "action_report":
            self._check_report_compliance(response, issues)

        return {
            "valid": len([i for i in issues if i["severity"] == "error"]) == 0,
            "issues": issues,
            "warning_count": len([i for i in issues if i["severity"] == "warning"]),
            "error_count": len([i for i in issues if i["severity"] == "error"]),
        }

    def _check_citation_compliance(self, response: str, rule: CitationRule,
                                     issues: list):
        """检查引用格式合规性.

        如果 LLM 提到了文件但没有使用规范的引用格式，记录违规.
        """
        # 检查是否存在不规范的文件引用
        # 例如：提到 "main.py" 但没有行号 → 违反引用规范
        loose_file_pattern = re.compile(
            r'(?<![`"\'\w/\\])'  # 不在引号或路径中
            r'([\w\-]+\.(?:py|js|ts|go|rs|java|yaml|json|toml|md|sql))\b'
            r'(?![\d:])'         # 后面没有行号
        )

        loose_matches = loose_file_pattern.findall(response)
        if loose_matches:
            violations = list(set(loose_matches))[:5]
            issues.append({
                "severity": "warning",
                "type": "citation_format",
                "message": (
                    f"引用了文件 {violations} 但没有使用规范的 "
                    f"`file:line` 格式（如 {rule.example}）"
                ),
            })

    def _check_disclosure_compliance(self, response: str, issues: list):
        """检查渐进式披露合规性."""
        separator = self.profile.section_separator
        parts = response.split(separator)

        if len(parts) < 2 and len(response) > 500:
            issues.append({
                "severity": "warning",
                "type": "disclosure",
                "message": (
                    f"回答超过 500 字符但未使用 `{separator}` 分隔，"
                    f"不符合渐进式披露要求"
                ),
            })

    def _check_report_compliance(self, response: str, issues: list):
        """检查行动报告格式合规性."""
        # 如果响应中包含工具调用，检查是否有对应的行动报告
        if "<function_call>" in response:
            report_count = response.count("<action_report>")
            call_count = response.count("<function_call>")

            if report_count < call_count:
                issues.append({
                    "severity": "warning",
                    "type": "report_format",
                    "message": (
                        f"有 {call_count} 个工具调用但只有 {report_count} 个 "
                        f"行动报告，每个工具调用必须附带 <action_report>"
                    ),
                })

    def get_violations(self) -> list[dict]:
        """获取最近一次验证的违规列表."""
        return self._violations
```

#### 8.2.2 集成到 PromptAssembler

**改动文件**: `agent/prompt.py`

```python
class PromptAssembler:
    def __init__(self, output_format: OutputFormatManager | None = None):
        self.output_format = output_format or OutputFormatManager()

    def assemble(self, inputs: PromptInputs, reserve_tokens: int = 30000) -> str:
        parts = []

        # TEXT — system prompt
        parts.append(f"<system>\n{inputs.role}\n</system>")

        # === 新增：输出格式规范（系统级，不可被覆盖） ===
        format_prompt = self.output_format.get_format_prompt()
        parts.append(f"<format_rules immutable=\"true\">\n{format_prompt}\n</format_rules>")

        # ... 其余部分不变 ...
```

#### 8.2.3 在 Agent 中启用输出验证

```python
class Agent:
    def __init__(self, config_path=None):
        # ... 现有初始化 ...
        self.output_format = OutputFormatManager()

    async def run(self, task_description: str) -> dict:
        # ... LLM 调用后 ...

        # 验证输出格式
        format_result = self.output_format.validate(response.content)
        if not format_result["valid"]:
            logger.warning("output_format_violations",
                           task_id=task_id,
                           errors=format_result["error_count"],
                           warnings=format_result["warning_count"])
            # 将违规信息加入 conversation，让 LLM 在下一轮修正
            violations_text = "\n".join(
                f"- [{i['severity']}] {i['message']}"
                for i in format_result["issues"]
            )
            conversation += (
                f"\n[Format Violations — 下一轮请修正以下格式问题]\n"
                f"{violations_text}"
            )
```

### 8.3 改动量估算

| 文件 | 改动类型 | 行数 |
|------|---------|------|
| `agent/output_format.py` | **新增** | ~200 行 |
| `agent/prompt.py` | 集成 OutputFormatManager | ~15 行 |
| `agent/core.py` | 在 LLM 响应后调用 validate | ~15 行 |

---

## 汇总：全部改动量估算

| 模块 | 新增文件 | 修改文件 | 预估代码行数 |
|------|---------|---------|------------|
| 一、非集集成 | — | `core.py`, `dont_do.py` | ~110 |
| 二、角色+观察 | `objects.py`, `role.py` | `core.py`, `prompt.py` | ~385 |
| 三、纠正闭环 | `correction.py` | `core.py` | ~200 |
| 四、验证改进 | — | `core.py` | ~200 |
| 五、TODO 闭环 | — | `core.py` | ~250 |
| 六、对象状态记忆 | — | `memory.py`, `core.py` | ~110 |
| 七、非集记忆 | — | `memory.py` | ~40 |
| 八、文献格式 | `output_format.py` | `prompt.py`, `core.py` | ~230 |
| **合计** | **4 个新文件** | **5 个文件修改** | **~1,525 行** |

## 实施顺序建议

```
Phase 1 (基础)    一、非集集成        → dont-do 规则在 agent loop 中真正生效
                  六、对象状态记忆     → 扩展 EpisodeEntry + schema

Phase 2 (核心)    二、角色+观察       → 对象模型 + 结构化观察
                  四、验证改进        → 主动重新观察 + 状态对比

Phase 3 (闭环)    三、纠正闭环        → 用户纠正 → 规则生成 → 重规划
                  五、TODO 闭环       → 验收标准分析 + 询问 + 比对
                  七、非集记忆        → 非集变动记录和查询

Phase 4 (增强)    八、文献格式        → 输出格式约束 + 验证
```

---

## 九、自愈工具运行时（Browser Harness 启发 — Self-Healing Agent Harness）

### 9.1 BH 洞察

Browser Harness 的核心主张：**每一个 `click()`、`type()`、`scroll()` 包装器都是开发者强加给模型的抽象。LLM 已经在数百万个 CDP token 上训练过——删除抽象层，让代理编写它需要的东西。**

BH 的自愈演示：代理忘记添加 `upload_file()` → grep `helpers.py` → 用原始 `DOM.setFileInputFiles` 编写 → 对于 12MB 文件切换到分块上传 → 全部自主完成。

通用模式：
```
检测缺失能力 → grep 现有代码 → 编写缺失函数 → 重试 → harness 永久变强
```

代理不是从头编写代码，而是编写恰好缺失的那个函数。`helpers.py`（~500 行）是所有工具函数的可编辑表面，代理通过编辑（而非扩展）来添加能力。

### 9.2 当前项目现状

`therain2020-agent` 的工具系统是**完全静态的**：

| 组件 | 当前行为 | 问题 |
|------|---------|------|
| `registry.py` | `scan()` 扫描 `tool.md` 文件，`register()` 注册 | 只有开发时能添加工具 |
| `executor.py` | 通过 import/mcp/subprocess 三种运行时执行 | 没有"代理编写新工具"的路径 |
| `loader.py` | 解析 YAML frontmatter 格式的 tool.md | 格式对开发者友好，但对 LLM 不友好 |

代理永远无法扩展自己的能力。遇到未知操作时只能失败。

### 9.3 方案 A：最小方案 — 可编辑工具辅助文件

**核心思路**：借鉴 BH 的 `agent_helpers.py`，在项目中添加一个 `tools/user_helpers.py`，代理可以读取和编辑它。

```
tools/
├── user_helpers.py          # ← 新增：代理可编辑的工具函数
├── file-system/
│   └── tool.md
└── .generated/
    └── ...
```

**实现**：
1. 新增 `write_helper` + `read_helper` 两个内置工具能力
2. `user_helpers.py` 中的函数自动注册为 import 运行时工具
3. 代理发现缺失能力 → 读 `user_helpers.py` → 编写新函数 → 自动注册 → 重试

**新增/改动文件**：

| 文件 | 改动 | 行数 |
|------|------|------|
| `tools/user_helpers.py` | **新增** — 空模板文件 | ~20 |
| `agent/tools/executor.py` | 新增 `_load_user_helpers()` | ~30 |
| `agent/tools/registry.py` | 新增 `reload_user_helpers()` | ~20 |
| `tools/file-system/tool.md` | 新增 `write_helper` / `read_helper` 能力 | ~15 |

**优势**：
- 改动量极小（~85 行），风险低
- 与 BH 的 `agent_helpers.py` 模式直接对齐
- 代理获得自愈能力的最小路径
- 不破坏现有工具系统

**劣势**：
- 无沙箱——代理可以写任意 Python 代码
- 无版本控制——无法回滚代理的错误修改
- 仅限 Python import 运行时，不适用于 MCP/subprocess 工具
- 代理可能写出有 bug 的代码导致后续调用失败

---

### 9.4 方案 B：中等方案 — 运行时工具注册 + 沙箱

**核心思路**：在方案 A 基础上增加安全边界和版本管理。

**实现**：
1. 代理编写的工具函数在**受限沙箱**中执行（` RestrictedPython ` 或 subprocess 隔离）
2. 新增 `register_tool` 能力——代理可以动态注册工具（不仅是写文件）
3. 工具版本管理——每次修改保存为 `user_helpers.v{N}.py`，支持回滚
4. dont-do 规则自动应用于代理编写的工具

**新增/改动文件**：

| 文件 | 改动 | 行数 |
|------|------|------|
| `agent/tools/sandbox.py` | **新增** — 受限执行环境 | ~150 |
| `agent/tools/runtime_registry.py` | **新增** — 运行时工具注册管理 | ~100 |
| `agent/tools/executor.py` | 新增沙箱执行路径 | ~40 |
| `agent/tools/registry.py` | 新增 `register_runtime()` / `rollback()` | ~50 |
| `agent/core.py` | 在 dont-do 检查中纳入动态工具 | ~15 |

**优势**：
- 有安全边界——代理不能执行任意系统命令
- 可回滚——错误修改不会永久破坏系统
- 与 dont-do 引擎集成——运行时工具也受规则约束
- 工具版本可审计

**劣势**：
- 沙箱实现复杂（RestrictedPython 有限制，subprocess 有性能开销）
- 版本管理增加存储和复杂度
- 中等改动量（~350 行）
- 沙箱可能限制代理编写有用工具的能力

---

### 9.5 方案 C：激进方案 — 全自修改工具系统

**核心思路**：代理不仅是工具的使用者，也是工具的**共同开发者**。整个工具系统对代理开放读写。

**实现**：
1. 代理可以编辑 `tool.md` 文件、修改适配器、编写新能力
2. Git 版本控制所有代理修改——每次修改自动 commit 到 `tools/.generated/` 分支
3. 工具进化历史可追溯——哪些工具是代理创建的、哪些被修改过、修改原因
4. 跨会话工具累积——代理 A 创建的工具，代理 B 可以直接使用

**新增/改动文件**：

| 文件 | 改动 | 行数 |
|------|------|------|
| `agent/tools/evolution.py` | **新增** — 工具进化管理器 | ~200 |
| `agent/tools/editor.py` | **新增** — 代理工具编辑接口 | ~150 |
| `agent/tools/registry.py` | 新增热重载 + 版本追踪 | ~80 |
| `agent/core.py` | 自愈循环集成 | ~60 |
| `agent/memory.py` | 工具进化事件记录 | ~30 |

**优势**：
- 最大灵活性——代理可以修改工具系统的任何层面
- 跨会话累积学习——工具能力随使用增长
- 完整审计追踪——每次修改都有 git history
- 与 BH 的"agent as programmer"哲学最一致

**劣势**：
- 安全风险最高——代理可以修改安全关键的工具定义
- 复杂度高——需要设计工具进化的治理规则
- 测试困难——代理生成的工具行为不确定
- 可能产生技术债务——代理写的代码质量不如人类

---

### 9.6 三方案对比

| 维度 | 方案 A（最小） | 方案 B（中等） | 方案 C（激进） |
|------|-------------|-------------|-------------|
| 改动量 | ~85 行 | ~350 行 | ~520 行 |
| 安全边界 | 无 | 沙箱隔离 | Git 审计 + dont-do |
| 可回滚 | 否 | 版本文件 | Git history |
| 跨会话累积 | 手动 | 半自动 | 全自动 |
| 代理可修改范围 | 仅 `user_helpers.py` | user_helpers + 动态注册 | 整个工具系统 |
| 风险等级 | 低 | 中 | 高 |
| 与 BH 对齐度 | 中 | 高 | 最高 |

---

## 十、静默失败检测（Browser Harness 启发 — Silent Failure Detection）

### 10.1 BH 洞察

**静默失败模式**是 AI 代理中抽象的最大隐藏成本：

```
LLM: "点击结账按钮"
工具包装器: 报告成功（HTTP 200 / Promise resolved）
实际: 不可见覆盖层拦截了点击
渲染引擎状态: 未改变
LLM 的 world model: "我们在结账页面了"（错误的）
→ 后续所有决策基于错误前提 → 级联失败
```

通用原则：**任何工具在没有真实验证的情况下报告状态的代理系统都存在这个问题**——ORM、文件系统包装器、API 客户端、云 SDK。

BH 的解决方案：截图 → 点击 → 再截图 → 像素对比验证。代理不信任工具的成功报告，而是直接观察真实状态。

### 10.2 当前项目现状

`executor.py` 的执行流程：
```python
result = await self.executor.execute(tool_def, cap_name, params)
# result 直接返回给 LLM，无验证
```

- `ToolExecutor.execute()` 只关心执行是否抛异常，不关心**状态是否真的改变了**
- `_execute_import()` 返回函数返回值，但函数可能返回 "OK" 而实际什么都没做
- 没有 `POST_ACTION` 状态验证机制

### 10.3 方案 A：最小方案 — Post-Action 验证钩子

**核心思路**：在工具执行后增加一个轻量验证步骤——"你说你改了文件，文件真的变了吗？"

**实现**：
1. 每个工具能力可以声明一个可选的 `verify` 钩子
2. 执行后自动调用验证钩子，对比声明效果与实际状态
3. 验证失败 → 结果中附带 `[WARNING: verification failed]` 标记

```yaml
# tool.md 扩展示例
capabilities:
  - name: write_file
    params: {path: {type: string}, content: {type: string}}
    runtime: import
    entry_point: write.py:write_file
    verify: read.py:file_exists  # ← 新增：验证钩子
```

**优势**：改动小（~60 行），向后兼容，可逐步为现有工具添加验证
**劣势**：需要开发者手动为每个工具定义验证方法；只对简单操作有效

### 10.4 方案 B：中等方案 — 结构化验证框架

**核心思路**：将验证提升为工具系统的一等概念。工具执行 = 操作 + 观察 + 对比。

**实现**：
1. `ToolExecutor` 新增 `execute_and_verify()` 方法
2. 对于有副作用的能力，自动在操作前后各做一次观察
3. 对比 state diff，判定操作是否真的生效
4. 验证失败时返回 `VerificationResult` 包含实际状态和期望状态的 diff

**优势**：系统化，与"观察→操作→验证"循环一致，可检测细微的状态不一致
**劣势**：中等改动量（~200 行），两次观察增加 token 消耗

### 10.5 方案 C：激进方案 — 持续状态监控 + 异常检测

**核心思路**：维护一个"影子世界模型"——代理认为世界是什么状态 vs 实际观察到的是什么状态。持续对比，发现偏离即告警。

**实现**：
1. `WorldModel` 组件维护代理对每个对象状态的信念
2. 每次工具调用后，自动采样验证世界模型的准确性
3. 偏离超过阈值 → 触发纠正流程（回滚 + 重试 + 通知用户）
4. 异常模式学习——哪些工具/操作组合容易出现静默失败

**优势**：最健壮，能捕获最隐蔽的静默失败，长期可自我改进
**劣势**：复杂度很高（~500 行），需要持续状态追踪，token 开销大

### 10.6 三方案对比

| 维度 | 方案 A（验证钩子） | 方案 B（结构化验证） | 方案 C（世界模型） |
|------|-----------------|-------------------|-----------------|
| 改动量 | ~60 行 | ~200 行 | ~500 行 |
| 需要工具改造 | 是（每个工具加 verify） | 部分 | 否 |
| Token 开销 | 低 | 中（两次观察） | 高（持续监控） |
| 检测能力 | 粗粒度 | 中粒度 | 细粒度 |
| 误报风险 | 低 | 中 | 高（初期） |
| 与现有观察-操作-验证循环的集成 | 松耦合 | 紧耦合 | 完全融合 |

---

## 十一、上下文窗口安全压缩（Browser Harness 启发 — Context Window Optimization Pitfalls）

### 11.1 BH 洞察

**Hermes 环境失败（Issue #155）** 是一个经典的上下文优化适得其反的案例：

- 惰性加载压缩了 skill 摘要，隐藏了"阅读 helpers.py"指令
- 代理从未发现现有的优化工具，浪费 token 重新发明它们
- 结果比不优化更差——既花了压缩的 token，又花了重新发明的 token

**核心教训**：
- **程序指令是全有或全无的**——要么完整呈现，要么完全不呈现。不能安全压缩。
- 可安全压缩：事实参考材料、文档、示例、背景上下文
- 不可安全压缩：程序指令、"先读这个"指令、工具发现机制、预检查清单

### 11.2 当前项目现状

`context.py` 的 LRU 驱逐和 `compress_conversation()` 对所有内容一视同仁：
- `ContextPage.priority` 只有 1-4 级，没有区分"内容类型"
- `compress_conversation()` 基于简单启发式（`[Step` 前缀），不理解语义
- `prompt.py` 的 `ToolResultManager` 对大于 5000 token 的结果做截断，可能截掉关键信息

### 11.3 方案 A：最小方案 — 不可变标记 + 安全区

**核心思路**：在现有 priority 系统上增加一个维度——`compressible` 标记。

**实现**：
1. `ContextPage` 新增 `compressible: bool = True` 字段
2. 程序指令、角色定义、工具发现指令标记为 `compressible=False`
3. 压缩/驱逐时跳过 `compressible=False` 的页面
4. `prompt.py` 的 `<format_rules immutable="true">` 已经部分做到了这一点——扩展为通用机制

**优势**：极简改动（~30 行），直接防止 Hermes 类 bug
**劣势**：需要开发者手动标记，容易遗漏；不解决压缩质量的问题

### 11.4 方案 B：中等方案 — 基于内容类型的智能压缩

**核心思路**：区分内容类型，对不同类型的上下文应用不同的压缩策略。

**实现**：
1. 内容分类器——将上下文分为 `procedural`（程序指令）、`reference`（参考材料）、`conversation`（对话历史）、`evidence`（工具结果）
2. `procedural` 永远不压缩；`reference` 可以摘要；`conversation` 保留最后 N 轮；`evidence` 按重要性截断
3. 与现有 `ContextPage` 系统集成——不同的 `eviction_policy` 对应不同的内容类型

**优势**：更精细的控制，不依赖开发者手动标记（自动分类）
**劣势**：中等改动量（~150 行），分类器可能出错

### 11.5 方案 C：激进方案 — LLM 驱动的语义感知压缩

**核心思路**：用 LLM 来做压缩决策——LLM 最理解什么内容是关键的。

**实现**：
1. 压缩时调用一个轻量 LLM（如 Haiku 或便宜模型）来判断哪些内容可安全压缩
2. 指令感知摘要——保留"how to"部分，压缩"what is"部分
3. 自动检测指令类内容并标记为不可压缩
4. 压缩质量反馈循环——如果代理因缺少信息而失败，反向调整压缩策略

**优势**：压缩质量最高，能理解语义细微差别，可自我改进
**劣势**：每次压缩需要额外的 LLM 调用（增加成本和延迟），复杂度高（~400 行）

### 11.6 三方案对比

| 维度 | 方案 A（不可变标记） | 方案 B（内容分类） | 方案 C（LLM 压缩） |
|------|-------------------|------------------|------------------|
| 改动量 | ~30 行 | ~150 行 | ~400 行 |
| 额外 LLM 调用 | 0 | 0 | 每次压缩 1 次 |
| 防 Hermes 类 bug | 是（手动） | 是（自动） | 是（语义理解） |
| 压缩质量 | 取决于标记 | 取决于分类器 | 最高 |
| 实施风险 | 极低 | 低 | 中 |

---

## 十二、技能持续学习网络（Browser Harness 启发 — Skills as Continuous Learning）

### 12.1 BH 洞察

Browser Use 的技能系统是一个**社交网络模型**：

```
创建 → 消费 → 评分（附书面理由）→ 迭代 → 
  → 退役（分数 < -3 自动淘汰）→ 合并（近重复项去重）
```

**关键设计决策**：

1. **书面反馈比评分更重要**。"选择器 `.btn-submit` 在重新设计的结账页面上不再存在"——这个理由准确告诉技能代理要修复什么。
2. **PII 门控**。一个专用 LLM 过滤器拒绝包含电子邮件、API 令牌、会话标识符的技能。
3. **探索成本摊销**。每个 Web 代理任务有两个阶段——探索（昂贵）和利用（廉价）。技能将探索转化为一次性投资。`每次任务成本 = exploration_cost / n_runs + exploitation_cost`
4. **超越 UI 的层级**。Level 1 = UI 交互。Level 2 = HTTP API 逆向工程。Level 3 = 代理重写整个交互模式。

**Duo 2FA 案例**：第一个代理花了 8 次额外调用发现按钮有稳定的 DOM ID `dont-trust-browser-button`。254 个代理之后，没有人需要再次发现它。

### 12.2 当前项目现状

项目已经有记忆系统的基础设施：

| 组件 | 功能 | 与技能网络的关系 |
|------|------|----------------|
| `memory.py` | 情节记忆 + 语义记忆（FTS5） | 可以存储技能及其成功率 |
| `consolidation.py` | 情节→语义蒸馏 | 可以从成功轨迹中提取技能 |
| `pattern_miner.py` | 错误/纠正聚类 | 可以识别"需要技能"的模式 |
| `correction.py` | 用户纠正→规则闭环 | 可以提供技能反馈机制 |

但缺少：
- 技能的结构化表示格式
- 技能的共享/消费机制
- 技能的评分和生命周期管理
- 探索成本的追踪和摊销计算

### 12.3 方案 A：最小方案 — 成功模式提取

**核心思路**：利用现有的 consolidation 基础设施，从成功的 episode 中提取可复用的"技能"。

**实现**：
1. 当一个 episode 成功完成，LLM 分析执行轨迹，提取关键方法（"这个任务是怎么完成的"）
2. 存储为语义记忆条目，类型标记为 `skill`，包含：触发条件、执行步骤、成功率
3. 未来相似任务时，在 memory_context 中注入匹配的技能
4. 如果技能被使用且任务成功 → 成功率上升；失败 → 成功率下降；低于阈值 → 不再推荐

**优势**：改动量小（~120 行），复用现有记忆基础设施
**劣势**：技能是纯文本描述，不是可执行代码；不能跨 agent 实例共享；无结构化反馈

### 12.4 方案 B：中等方案 — 结构化技能仓库 + 反馈

**核心思路**：为技能定义结构化格式，建立独立的技能仓库，支持评分和迭代。

**实现**：
1. 新增 `agent/skill.py` — 技能数据模型 + 仓库管理
2. 技能格式：
```yaml
---
id: skill-abc123
task_type: web-automation
domain: github-login
triggers: ["登录 GitHub", "GitHub OAuth"]
approach: |
  1. 导航到 github.com/login
  2. 使用 #login_field 输入用户名
  3. ...
success_rate: 0.94
uses: 47
created_by: agent-2026-05-28
last_used: 2026-05-28T10:00:00Z
feedback:
  - rating: +1
    reason: "在 GitHub 重新设计后仍然有效"
    timestamp: 2026-05-28
---
```
3. 评分机制：+1（有效）/ -1（无效），附书面理由
4. 自动退役：评分 < -3 或成功率 < 50% 时归档
5. PII 门控：保存前用规则+LLM 双重检查过滤敏感信息

**优势**：结构化、可量化、有质量保证、与 BH 技能网络模型对齐
**劣势**：中等改动量（~300 行），需要设计技能格式和评分 UI/API

### 12.5 方案 C：激进方案 — 全社交学习网络

**核心思路**：多 agent 实例之间共享技能，形成网络效应。技能不仅来自自身经验，也来自其他 agent。

**实现**：
1. 技能存储在后端服务（SQLite/PostgreSQL/S3），多 agent 实例共享
2. 技能合并——检测近重复技能，合并为更通用的版本
3. HTTP 级别技能提取——代理观察网络流量，逆向工程底层 API，保存原始 HTTP 请求
4. 三层技能体系：Level 1 (UI 交互) → Level 2 (API 调用) → Level 3 (模式重写)
5. 探索成本追踪——显示每个技能节省了多少 token/时间

**优势**：网络效应，探索成本真正摊销到所有用户，最接近 BH 的完整愿景
**劣势**：复杂度极高（~800 行 + 后端服务），需要基础设施，PII 风险增大，技能质量控制困难

### 12.6 三方案对比

| 维度 | 方案 A（模式提取） | 方案 B（技能仓库） | 方案 C（社交网络） |
|------|-----------------|-----------------|-----------------|
| 改动量 | ~120 行 | ~300 行 | ~800 行 + 后端 |
| 跨会话累积 | 是 | 是 | 是 |
| 跨 agent 共享 | 否 | 手动 | 自动 |
| 质量控制 | 无 | 评分+退役 | 评分+退役+合并 |
| PII 防护 | 无 | 规则过滤 | LLM 双重检查 |
| 探索成本可见 | 否 | 否 | 是 |

---

## 十三、探索 vs 利用经济学（Browser Harness 启发 — Exploration vs Exploitation Economics）

### 13.1 BH 洞察

每个 agent 任务都可以分解为两个阶段：

| 阶段 | 成本 | 描述 |
|------|------|------|
| 探索（Exploration） | 高 — 多次 LLM 调用、页面交互、试错 | "这个网站是怎么工作的？" |
| 利用（Exploitation） | 低 — 已知路径、缓存的选择器、已验证的流程 | "按已知路径执行" |

**没有共享记忆时**：每次任务都支付完整的探索成本。`总成本 = exploration_cost × n_runs`

**有技能共享时**：探索转为一次性投资。`总成本 = exploration_cost + exploitation_cost × n_runs`

**代币经济学公式**（Alex Hitt）：
```
总成本 = (base_inference_cost × n_runs) + (recovery_cost × n_failures)

盈亏平衡: developer_hours_saved × hourly_rate > n_runs × (recovery_tokens × token_price)
```

### 13.2 当前项目现状

项目有 provider 成本路由（`agent/providers/router.py`），但它是**单次任务视角**的：

- 三种策略：`performance`（最贵但最好）、`powersave`（最便宜）、`ondemand`（默认，成本优化）
- 能力感知路由：选择成功率 ≥ 85% 的最便宜模型
- 熔断器：5 次连续失败 → 30 秒冷却 → 半开探测

**缺失**：没有"这个任务之前做过吗？可以跳过探索直接用已知方法吗？"的判断。

### 13.4 方案 A：最小方案 — 任务相似度匹配

**核心思路**：在语义记忆中搜索与当前任务最相似的历史成功 episode。如果找到高相似度的，注入其执行方法作为提示。

**实现**：
1. 利用现有 FTS5 搜索引擎，对任务描述做语义检索
2. 返回 top-3 最相似的成功 episode
3. 在 prompt 中注入："类似任务之前按以下方式完成：..."
4. 让 LLM 自己决定是否复用

**优势**：改动小（~50 行），复用现有 FTS5
**劣势**：FTS5 是关键词匹配，不是语义匹配；没有量化的成本节省追踪

### 13.5 方案 B：中等方案 — 探索/利用双模式调度

**核心思路**：为任务执行增加一个"模式选择"步骤——先判断这是新任务（探索模式）还是已知任务（利用模式）。

**实现**：
1. 任务分类器：LLM 判断任务属于"已知领域"还是"新领域"
2. 已知领域 → 利用模式：使用便宜模型 + 注入历史成功方法 + 减少 max_iterations
3. 新领域 → 探索模式：使用强模型 + 更多迭代 + 记录所有尝试（为未来利用做准备）
4. 追踪每次任务的探索/利用分类和实际成本

**优势**：直接节省成本（已知任务用便宜模型），与 provider router 配合
**劣势**：分类器可能误判（新任务被当作已知任务），中等改动量（~180 行）

### 13.6 方案 C：激进方案 — 全成本会计 + 技能 ROI 追踪

**核心思路**：为每个技能/方法计算 ROI。追踪创建技能花费了多少 token，后续使用节省了多少 token。

**实现**：
1. 每次任务执行追踪完整 token 消耗（含探索阶段的试错）
2. 技能创建时记录"研发成本"（创建这个技能花了多少 token）
3. 技能使用时计算"节省成本"（比从头探索少花了多少 token）
4. ROI = 节省成本 / 研发成本
5. 在 provider 路由决策中纳入技能可用性——有技能的领域优先用便宜模型

**优势**：可量化的投资回报，数据驱动决策，长期优化
**劣势**：复杂度高（~350 行），token 追踪需要全链路插桩

### 13.7 三方案对比

| 维度 | 方案 A（相似度匹配） | 方案 B（双模式调度） | 方案 C（ROI 追踪） |
|------|-------------------|-------------------|------------------|
| 改动量 | ~50 行 | ~180 行 | ~350 行 |
| 成本节省 | 间接（给 LLM 提示） | 直接（选便宜模型） | 量化（数据驱动） |
| 需要语义搜索 | 否（用 FTS5） | 否 | 是 |
| Token 追踪 | 无 | 基础 | 全链路 |

---

## 十四、新增浏览器能力（Browser Harness 启发 — 新功能域）

### 14.1 BH 洞察

Browser Harness 提供了一个经过实战验证的浏览器自动化架构，设计决策明确：

| 设计决策 | 原因 |
|---------|------|
| **坐标点击默认** | `Input.dispatchMouseEvent` 在合成器级别穿过 iframe/shadow/cross-origin。视觉基础比选择器更健壮 |
| **截图优先交互** | `capture_screenshot() → 读像素 → click_at_xy(x,y) → 再截图验证`。像人类一样浏览 |
| **守护进程持久连接** | `daemon.py` 在 LLM 认知暂停期间保持 CDP WebSocket 存活 |
| **4 文件约 600 行** | `run.py`(13) + `helpers.py`(192) + `daemon.py`(220) + `SKILL.md`。极简运行时 |
| **清洁基线版本控制** | 592 行基线做版本控制，运行时差异记录为仅追加日志 |
| **直接 CDP 非框架** | LLM → CDP → Chrome，而非 LLM → click(selector) → Playwright → CDP → Chrome |

### 14.2 当前项目现状

项目**完全没有浏览器能力**。工具仅限于文件系统 I/O、MCP 集成、子进程执行。没有 DOM 交互、网页抓取、JavaScript 执行、截图或任何形式的浏览器自动化。

### 14.3 方案 A：最小方案 — CDP 浏览器工具 via MCP

**核心思路**：不写原生浏览器代码，通过现有的 MCP 基础设施接入外部浏览器服务。

**实现**：
1. 使用 `browser-use` 或 `puppeteer` 的 MCP server
2. 通过 `agent/tools/adapters/mcp.py` 自动发现和注册浏览器工具
3. 零原生浏览器代码——全部通过 MCP JSON-RPC 调用

**优势**：
- 最快实现——现有 MCP 基础设施完全支持
- 零维护成本——浏览器服务由外部项目维护
- 立即可用——browser-use MCP server 已经存在

**劣势**：
- 受限于 MCP server 的能力边界——无法控制架构
- 无法实现自愈工具（MCP 工具是远程的，代理不能编辑）
- 无法实现技能共享网络（依赖外部服务的技能系统）
- 性能——多一层 JSON-RPC 序列化
- 无法应用坐标点击默认模式（除非 MCP server 支持）

### 14.4 方案 B：中等方案 — 原生 Browser Harness 适配器

**核心思路**：在项目中创建一个 `agent/tools/adapters/browser_harness.py`，直接实现 BH 的核心模式。

**实现**：
1. 新增 `agent/tools/adapters/browser_harness.py` — 适配器，将 BH 模式转化为 tool.md 定义
2. 新增 `agent/tools/browser/` 目录 — 浏览器工具实现：
   - `daemon.py` — CDP 守护进程（借鉴 BH，适配 Windows TCP 回环）
   - `helpers.py` — 浏览器操作辅助函数（代理可编辑）
   - `tool.md` — 工具定义（导航、点击、输入、截图、JS 执行、CDP 原始通道）
3. 遵循 BH 的设计决策——坐标点击默认、截图优先、helpers.py 可编辑
4. 使用 `chromedp` 或直接 CDP WebSocket（Python 的 `websockets` + `cdp` 库）

**新增/改动文件**：

| 文件 | 改动 | 行数 |
|------|------|------|
| `agent/tools/adapters/browser_harness.py` | **新增** — 适配器 | ~80 |
| `agent/tools/browser/tool.md` | **新增** — 工具定义 | ~60 |
| `agent/tools/browser/daemon.py` | **新增** — CDP 守护进程 | ~200 |
| `agent/tools/browser/helpers.py` | **新增** — 可编辑辅助函数 | ~150 |
| `agent/tools/browser/user_helpers.py` | **新增** — 代理可编辑扩展 | ~20 |
| `pyproject.toml` | 新增依赖 `websockets` | ~5 |

**优势**：
- 完全控制架构——可以应用所有 BH 设计模式
- 自愈工具——代理可以编辑 `user_helpers.py`
- 与现有工具系统深度集成——dont-do 规则、验证框架、记忆系统
- 约 500 行——与 BH 自身规模相当
- 截图优先 + 坐标点击默认——视觉基础更健壮

**劣势**：
- 需要 Chrome/Chromium 运行环境
- 新增外部依赖（`websockets`、CDP 协议知识）
- Windows 上 CDP 连接管理比 Unix 复杂（TCP 回环 vs Unix socket）
- 浏览器版本兼容性——Chrome 147+ 的配置文件锁定等问题需要处理

### 14.5 方案 C：激进方案 — 完整浏览器代理子系统 + 技能网络

**核心思路**：构建完整的浏览器代理子系统，包含自愈运行时、技能网络、探索成本摊销、HTTP 级别技能提取。

**实现**：
1. 方案 B 的所有内容
2. 新增 `agent/tools/browser/skills.py` — 浏览器技能管理
3. 新增 `agent/tools/browser/explorer.py` — 探索模式（自动发现网站结构）
4. 新增 `agent/tools/browser/http_skills.py` — HTTP 级别技能提取（监控网络流量 → 逆向工程 API）
5. 新增 `agent/tools/browser/anti_detect.py` — 反机器人检测（行为熵注入）
6. 技能市场——本地技能仓库 + 可选远程同步

**优势**：
- 最完整的解决方案
- 网络效应——技能在多个 agent 间共享
- HTTP 级别技能——对于稳定 API 的网站，跳过 UI 直接调用 API，极大节省 token

**劣势**：
- 工作量大（~2000 行 + 后端服务）
- 维护负担重
- HTTP 技能提取有法律/合规风险
- 反检测是军备竞赛——需要持续更新
- 可能分散核心 agent 功能的开发精力

### 14.6 三方案对比

| 维度 | 方案 A（MCP） | 方案 B（原生适配器） | 方案 C（完整子系统） |
|------|------------|------------------|------------------|
| 代码量 | ~20 行 | ~500 行 | ~2000 行 |
| 开发时间 | 几小时 | 几天 | 几周 |
| 自愈工具 | 否 | 是（user_helpers.py） | 是 |
| 技能网络 | 依赖外部 | 本地技能 | 全网技能 |
| HTTP 技能 | 否 | 否 | 是 |
| 反检测 | 依赖外部 | 基础 | 行为熵注入 |
| 架构控制 | 低 | 高 | 高 |
| 维护成本 | 低 | 中 | 高 |

---

## Browser Harness 启发汇总

### 洞察→模块映射

| BH 永久笔记 | 核心洞察 | 映射到当前模块 | 优化方向 |
|-----------|---------|-------------|---------|
| `self-healing-agent-harness` | 代理编辑自己的工具代码 | `executor.py`, `registry.py` | 九、自愈工具运行时 |
| `agent-as-programmer-runtime-tool-creation` | 工具调用 vs 工具编写 | `executor.py` | 九、自愈工具运行时 |
| `silent-failure-modes-in-agent-tool-abstraction` | 包装器报告成功但状态未变 | `executor.py` | 十、静默失败检测 |
| `context-window-optimization-pitfalls` | 压缩可能隐藏关键指令 | `context.py`, `prompt.py` | 十一、上下文安全 |
| `shared-agent-skills-learning-network` | 技能社交网络 + PII 门控 | `memory.py`, `consolidation.py` | 十二、技能学习网络 |
| `web-agent-exploration-vs-exploitation` | 探索昂贵，利用廉价 | `providers/router.py` | 十三、探索vs利用 |
| `token-economics-of-self-healing-agents` | 自愈的盈亏平衡方程 | `providers/router.py` | 十三、探索vs利用 |
| `cdp-direct-access-vs-framework-abstraction` | 删除抽象层，给 LLM 原始表面 | —（新功能域） | 十四、浏览器能力 |
| `coordinate-click-default-pattern-for-agent-browsers` | 视觉优先，截图→点击→验证 | —（新功能域） | 十四、浏览器能力 |
| `bot-detection-vs-ai-agent-behavioral-entropy` | 行为分析取代签名检测 | `security/` | 十四、浏览器能力 |

### 与已有 8 节的协同关系

```
已有优化                          BH 启发的新优化
────────                          ──────────────
一、非集集成        ←────────→    十、静默失败检测（POST_ACTION 验证可用 dont-do 规则表达）
二、角色+观察       ←────────→    十、静默失败检测（观察→操作→验证循环的第三环）
三、纠正闭环        ←────────→    十二、技能学习网络（纠正可触发技能更新）
四、验证改进        ←────────→    十、静默失败检测（验证是检测静默失败的关键机制）
五、TODO 闭环       ←────────→    十三、探索vs利用（已知 TODO 走利用模式，新 TODO 走探索模式）
六、对象状态记忆     ←────────→    十、静默失败检测（对象状态变化是判断操作是否生效的证据）
八、文献格式        ←────────→    十一、上下文安全（格式规则属于不可压缩的程序指令）
```

### 实施维度总览

| # | 优化方向 | 方案 A（最小） | 方案 B（中等） | 方案 C（激进） | 独立可做？ |
|---|---------|-------------|-------------|-------------|----------|
| 九 | 自愈工具运行时 | ~85 行 | ~350 行 | ~520 行 | 是 |
| 十 | 静默失败检测 | ~60 行 | ~200 行 | ~500 行 | 是 |
| 十一 | 上下文安全 | ~30 行 | ~150 行 | ~400 行 | 是 |
| 十二 | 技能学习网络 | ~120 行 | ~300 行 | ~800 行+后端 | 建议在九之后 |
| 十三 | 探索vs利用 | ~50 行 | ~180 行 | ~350 行 | 建议在十二之后 |
| 十四 | 浏览器能力 | ~20 行 | ~500 行 | ~2000 行 | 是 |

---

# 最终优化方案（基于选型决策）

> 选型结果：九→C, 十→A(与九协同), 十一→C, 十二→C, 十三→B, 十四→B
> 2026-05-28

---

## 架构总览：六项优化的系统关系

```
                        ┌──────────────────────┐
                        │   十二-C: 技能社交网络   │
                        │   (跨会话知识积累)      │
                        └──────────┬───────────┘
                                   │ 技能注入
                                   ▼
┌──────────────────┐    ┌──────────────────────┐
│  十三-B: 双模式调度 │◄───│   任务执行决策         │
│  (探索 vs 利用)    │    │                      │
└────────┬─────────┘    └──────────────────────┘
         │ 模式选择
         ▼
┌──────────────────────────────────────────────┐
│               Agent Core Loop                  │
│  ┌──────────────────────────────────────┐    │
│  │  九-C: 自愈工具运行时                   │    │
│  │  ┌──────────────────────────────┐    │    │
│  │  │ 工具执行 → 失败/缺失能力       │    │    │
│  │  │   ↓                          │    │    │
│  │  │ 十-A: 验证钩子检测静默失败      │    │    │
│  │  │   ↓                          │    │    │
│  │  │ 九-C: 代理写 verify/新工具     │    │    │
│  │  │   ↓                          │    │    │
│  │  │ 重试 → 成功 → 工具永久增强     │    │    │
│  │  └──────────────────────────────┘    │    │
│  └──────────────────────────────────────┘    │
└──────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────┐    ┌──────────────────┐
│  十一-C: 语义压缩      │    │  十四-B: 浏览器能力 │
│  (安全上下文管理)      │    │  (新功能域)        │
└──────────────────────┘    └──────────────────┘
```

---

## 关键协同分析：九-C × 十-A — 自愈验证闭环

这是整个方案中最重要的协同关系。单独看十-A 有一个致命缺陷——"需要开发者手动为每个工具定义验证方法"。但和九-C 结合后，这个缺陷被自愈机制自动补上。

### 问题

十-A 的 `verify` 钩子是一个可选字段。如果没有定义，静默失败就检测不到。期望开发者提前为所有工具写好验证是不现实的。

### 解决方案：代理自己写验证

```
Step 1: 工具执行 → 返回 "success"
Step 2: 十-A 查找该工具的 verify 钩子 → 不存在 → 跳过验证
Step 3: 后续步骤因状态不一致而失败（隐式检测到静默失败）
Step 4: 九-C 自愈循环触发：
  a. 代理读取工具实现（e.g. write.py:write_file）
  b. 代理分析：这个工具的预期效果是什么？如何验证？
  c. 代理编写 verify 函数（e.g. 检查文件是否存在、内容 hash 是否匹配）
  d. 代理更新 tool.md，添加 verify: read.py:verify_write
  e. 代理重新执行原任务
Step 5: 重试时，verify 钩子已存在 → 十-A 正常执行验证 → 静默失败不再漏过
```

### 协同设计的四个关键元素

**1. 验证钩子协议（十-A）**

```yaml
# tool.md 扩展
capabilities:
  - name: write_file
    params: {path: {type: string}, content: {type: string}}
    runtime: import
    entry_point: write.py:write_file
    verify:                          # ← 新增字段
      function: read.py:verify_write  # 验证函数
      auto_generated: true            # 标记为代理生成（可被覆盖）
      generated_by: episode-abc123    # 追溯来源
      generated_at: 2026-05-28T10:00:00Z
```

**2. 验证失败信号**

验证结果不只是 bool。需要足够的信息让代理理解"哪里出错了"并修复：

```python
@dataclass
class VerificationResult:
    verified: bool
    expected_effect: str      # "文件 /path/to/file 应被创建"
    actual_state: dict         # 观察到的实际状态
    expected_state: dict       # 期望状态（从工具参数推断）
    diff: dict                 # 差异
    suggestion: str | None     # LLM 生成的修复建议（可选）
```

**3. 自愈触发器**

什么时候触发自愈循环来补充验证？

| 触发条件 | 说明 |
|---------|------|
| 验证失败（verify 存在但未通过） | 代理分析失败原因 → 改进 verify 或改进工具 |
| verify 缺失 + 后续步骤失败 | 推断此工具需要验证 → 代理编写 verify 并回填 |
| episode 成功但状态 diff 异常 | 工具声称成功但状态变化与预期不符 → 代理补充验证 |
| 用户纠正涉及工具结果 | "这个文件内容不对" → 代理为该工具添加验证 |

**4. 验证函数的自动生成**

代理编写 verify 函数的模板：

```python
# 代理生成的 verify_write.py
def verify_write(path: str, content: str) -> dict:
    """Verify that write_file actually wrote the content.
    
    Auto-generated by agent (episode: abc123, 2026-05-28).
    """
    import os
    if not os.path.exists(path):
        return {
            "verified": False,
            "expected_effect": f"File {path} should exist",
            "actual_state": {"exists": False},
            "expected_state": {"exists": True},
            "suggestion": "File was not created. Check directory permissions."
        }
    
    with open(path, 'r', encoding='utf-8') as f:
        actual = f.read()
    
    return {
        "verified": actual == content,
        "expected_effect": f"File {path} should contain specified content",
        "actual_state": {"size": len(actual), "hash": hash(actual)},
        "expected_state": {"size": len(content), "hash": hash(content)},
        "suggestion": None if actual == content else "Content mismatch. Retry write."
    }
```

对于复杂操作（数据库迁移、API 调用），代理可以组合多个观察工具来做验证，不只是简单的文件检查。

**此协同消除了十-A 的原始劣势**：不再需要开发者手动定义验证方法。代理在运行中遇到静默失败时，自主学习如何验证。

---

## Phase 1: 基础 — 自愈工具运行时 + 静默验证

### 1.1 `agent/tools/evolution.py` — 工具进化管理器（新增，~220 行）

**OS 内核类比**：kpatch（内核热补丁）——运行时修改内核代码而无需重启。

```python
"""Tool evolution manager. 类比: kpatch — runtime kernel patching.

Manages the lifecycle of agent-created and agent-modified tools:
- Safe read/write of tool definitions and implementations
- Git-based version control for all agent modifications
- Validation gate before hot-reload
- Rollback on failure
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
import hashlib
import subprocess
import uuid

import structlog
import yaml

logger = structlog.get_logger()


class EvolutionAction(Enum):
    CREATE = "create"        # New tool/capability
    MODIFY = "modify"        # Change existing
    ADD_VERIFY = "add_verify"  # Add verification hook
    DELETE = "delete"        # Remove (with tombstone)
    ROLLBACK = "rollback"   # Revert to previous version


@dataclass
class EvolutionRecord:
    """A single tool modification record."""
    id: str
    timestamp: str
    action: EvolutionAction
    target: str              # tool name or "tool.md:capability"
    episode_id: str          # Which episode triggered this
    description: str         # Why this change was made
    diff: str                # Git diff of the change
    snapshot_hash: str       # SHA256 of tool state before change
    verified: bool = False   # Has this change been verified working?


class ToolEvolutionManager:
    """Manages agent-driven tool evolution. 类比: kpatch runtime patching."""

    def __init__(self, tools_dir: Path, generated_dir: Path):
        self.tools_dir = Path(tools_dir)
        self.generated_dir = Path(generated_dir)
        self.generated_dir.mkdir(parents=True, exist_ok=True)
        self._history: list[EvolutionRecord] = []
        self._pending: dict[str, EvolutionRecord] = {}  # Staged but unverified

    # === Safe editing API for agents ===

    def read_tool_source(self, tool_name: str) -> dict:
        """Read complete source of a tool (tool.md + implementations).
        
        Returns a structured dict the agent can understand and modify.
        """
        tool_md = self.tools_dir / tool_name / "tool.md"
        if not tool_md.exists():
            # Check generated
            tool_md = self.generated_dir / tool_name / "tool.md"
        
        if not tool_md.exists():
            return {"error": f"Tool '{tool_name}' not found"}
        
        raw = tool_md.read_text(encoding="utf-8")
        # Split YAML frontmatter from markdown body
        parts = raw.split("---", 2)
        meta = yaml.safe_load(parts[1]) if len(parts) >= 2 else {}
        body = parts[2] if len(parts) >= 3 else ""
        
        # Also read implementation files
        impls = {}
        tool_dir = tool_md.parent
        for py_file in tool_dir.glob("*.py"):
            impls[py_file.name] = py_file.read_text(encoding="utf-8")
        
        return {
            "name": tool_name,
            "metadata": meta,
            "body": body,
            "implementations": impls,
            "path": str(tool_md),
        }

    def stage_change(
        self,
        tool_name: str,
        action: EvolutionAction,
        changes: dict,         # {"tool.md": "new content", "helpers.py": "new content"}
        episode_id: str,
        description: str,
    ) -> EvolutionRecord:
        """Stage a tool change. Does NOT apply yet — goes through validation gate."""
        # Take snapshot before change
        snapshot = self._compute_state_hash(tool_name)
        
        record = EvolutionRecord(
            id=f"evol-{uuid.uuid4().hex[:12]}",
            timestamp=datetime.now(UTC).isoformat(),
            action=action,
            target=tool_name,
            episode_id=episode_id,
            description=description,
            diff="",  # Computed on commit
            snapshot_hash=snapshot,
            verified=False,
        )
        
        # Write changes to staging area (generated dir, not live tools)
        for file_path, content in changes.items():
            stage_path = self.generated_dir / tool_name / file_path
            stage_path.parent.mkdir(parents=True, exist_ok=True)
            stage_path.write_text(content, encoding="utf-8")
        
        self._pending[record.id] = record
        return record

    def validate_and_commit(self, record_id: str) -> bool:
        """Validation gate before applying agent changes.
        
        Checks:
        1. YAML validity for tool.md
        2. Python syntax for .py files
        3. dont-do rules don't block this change
        4. Registry can load the modified tool
        """
        record = self._pending.get(record_id)
        if not record:
            return False
        
        stage_dir = self.generated_dir / record.target
        
        # Validate YAML
        tool_md = stage_dir / "tool.md"
        if tool_md.exists():
            try:
                raw = tool_md.read_text(encoding="utf-8")
                if "---" in raw:
                    parts = raw.split("---", 2)
                    yaml.safe_load(parts[1])
            except yaml.YAMLError as e:
                logger.error("evolution_validation_yaml", error=str(e))
                return False
        
        # Validate Python syntax
        for py_file in stage_dir.glob("*.py"):
            try:
                compile(py_file.read_text(encoding="utf-8"), str(py_file), "exec")
            except SyntaxError as e:
                logger.error("evolution_validation_syntax", file=str(py_file), error=str(e))
                return False
        
        # Compute diff
        record.diff = self._compute_diff(record.target, stage_dir)
        
        # Git commit the change
        self._git_commit(record)
        
        # Move from staging to live
        # (actual hot-reload handled by registry)
        record.verified = True
        self._history.append(record)
        del self._pending[record_id]
        
        logger.info("evolution_committed", record_id=record_id, action=record.action.value)
        return True

    def rollback(self, tool_name: str, steps: int = 1) -> EvolutionRecord | None:
        """Rollback N evolution steps. Uses git history."""
        tool_dir = self.tools_dir / tool_name
        try:
            subprocess.run(
                ["git", "checkout", f"HEAD~{steps}", "--", str(tool_dir)],
                capture_output=True, text=True, check=True,
            )
            record = EvolutionRecord(
                id=f"evol-rollback-{uuid.uuid4().hex[:8]}",
                timestamp=datetime.now(UTC).isoformat(),
                action=EvolutionAction.ROLLBACK,
                target=tool_name,
                episode_id="",
                description=f"Rolled back {steps} step(s)",
                diff="",
                snapshot_hash="",
                verified=True,
            )
            self._history.append(record)
            return record
        except subprocess.CalledProcessError as e:
            logger.error("evolution_rollback_failed", error=str(e))
            return None

    def get_history(self, tool_name: str | None = None) -> list[EvolutionRecord]:
        """Get evolution history, optionally filtered by tool."""
        if tool_name:
            return [r for r in self._history if r.target == tool_name]
        return list(self._history)

    # === Internal ===

    def _compute_state_hash(self, tool_name: str) -> str:
        tool_dir = self.tools_dir / tool_name
        if not tool_dir.exists():
            return ""
        hasher = hashlib.sha256()
        for f in sorted(tool_dir.rglob("*")):
            if f.is_file():
                hasher.update(f.read_bytes())
        return hasher.hexdigest()[:16]

    def _compute_diff(self, tool_name: str, stage_dir: Path) -> str:
        tool_dir = self.tools_dir / tool_name
        try:
            result = subprocess.run(
                ["git", "diff", "--no-index", str(tool_dir), str(stage_dir)],
                capture_output=True, text=True,
            )
            return result.stdout[:5000]
        except subprocess.CalledProcessError:
            return "(diff unavailable)"

    def _git_commit(self, record: EvolutionRecord) -> None:
        stage_dir = self.generated_dir / record.target
        tool_dir = self.tools_dir / record.target
        
        # Copy staged files to live
        import shutil
        if tool_dir.exists():
            shutil.rmtree(tool_dir)
        shutil.copytree(stage_dir, tool_dir)
        
        # Git add + commit
        try:
            subprocess.run(
                ["git", "add", str(tool_dir)],
                capture_output=True, check=True,
            )
            msg = f"tool(evolution): {record.action.value} {record.target}\n\n{record.description}\n\nEpisode: {record.episode_id}"
            subprocess.run(
                ["git", "commit", "-m", msg],
                capture_output=True, check=True,
            )
        except subprocess.CalledProcessError as e:
            logger.error("evolution_git_failed", error=str(e))
```

### 1.2 `agent/tools/editor.py` — 代理工具编辑接口（新增，~150 行）

**OS 内核类比**：`ptrace`——允许一个进程（代理）安全地检查和修改另一个进程（工具系统）的代码。

```python
"""Agent tool editing interface. 类比: ptrace system call.

Provides the agent with structured read/write access to the tool system.
This is the surface through which the agent performs self-healing.
"""

from dataclasses import dataclass
from pathlib import Path

import structlog

from .evolution import ToolEvolutionManager, EvolutionAction

logger = structlog.get_logger()


@dataclass
class EditCapability:
    """What the agent can do to the tool system."""
    name: str
    description: str
    safety_level: str  # "safe" | "caution" | "dangerous"


# The agent's editing capabilities
EDIT_CAPABILITIES = [
    EditCapability("read_tool", "Read a tool's full source code", "safe"),
    EditCapability("write_verify", "Add or update a verify hook on a capability", "safe"),
    EditCapability("write_helper", "Add a new helper function to a tool", "caution"),
    EditCapability("modify_capability", "Modify an existing capability's implementation", "caution"),
    EditCapability("create_capability", "Create a new capability on an existing tool", "caution"),
    EditCapability("create_tool", "Create an entirely new tool definition", "dangerous"),
    EditCapability("rollback", "Rollback a tool to a previous version", "dangerous"),
]


class AgentToolEditor:
    """Safe editing surface for agent-driven tool evolution.
    
    类比: ptrace — one process safely inspects/modifies another.
    """

    def __init__(self, evolution: ToolEvolutionManager):
        self.evolution = evolution

    # === Public API (exposed as tool capabilities to the agent) ===

    def read_tool(self, tool_name: str) -> dict:
        """Read a tool's complete source. Agent uses this to understand existing code."""
        return self.evolution.read_tool_source(tool_name)

    def add_verify(
        self,
        tool_name: str,
        capability_name: str,
        verify_function: str,     # Python code for the verify function
        episode_id: str,
        reason: str,
    ) -> dict:
        """Add a verification hook to a capability.
        
        This is the primary path for 十-A auto-healing:
        Agent detects silent failure → writes verify → commits.
        """
        source = self.evolution.read_tool_source(tool_name)
        if "error" in source:
            return source
        
        # 1. Write the verify function to a .py file
        verify_filename = f"verify_{capability_name}.py"
        changes = {verify_filename: verify_function}
        
        # 2. Update tool.md to add the verify field
        meta = source["metadata"]
        for cap in meta.get("capabilities", []):
            if cap["name"] == capability_name:
                cap["verify"] = {
                    "function": f"{verify_filename}:verify_{capability_name}",
                    "auto_generated": True,
                    "generated_by": episode_id,
                }
                break
        
        new_tool_md = self._rebuild_tool_md(meta, source["body"])
        changes["tool.md"] = new_tool_md
        
        # 3. Stage and validate
        record = self.evolution.stage_change(
            tool_name=tool_name,
            action=EvolutionAction.ADD_VERIFY,
            changes=changes,
            episode_id=episode_id,
            description=f"Add verify hook for {capability_name}: {reason}",
        )
        
        ok = self.evolution.validate_and_commit(record.id)
        return {
            "success": ok,
            "record_id": record.id,
            "message": f"Verify hook for {tool_name}.{capability_name} {'added' if ok else 'failed validation'}",
        }

    def add_helper(
        self,
        tool_name: str,
        helper_name: str,
        helper_code: str,
        episode_id: str,
        reason: str,
    ) -> dict:
        """Add a new helper function to a tool. Core self-healing path."""
        source = self.evolution.read_tool_source(tool_name)
        if "error" in source:
            return source
        
        filename = f"{helper_name}.py"
        changes = {filename: helper_code}
        
        # Update tool.md metadata
        meta = source["metadata"]
        if "agent_helpers" not in meta:
            meta["agent_helpers"] = []
        meta["agent_helpers"].append({
            "name": helper_name,
            "file": filename,
            "added_by": episode_id,
            "reason": reason,
        })
        
        changes["tool.md"] = self._rebuild_tool_md(meta, source["body"])
        
        record = self.evolution.stage_change(
            tool_name=tool_name,
            action=EvolutionAction.CREATE,
            changes=changes,
            episode_id=episode_id,
            description=f"Add helper {helper_name}: {reason}",
        )
        
        ok = self.evolution.validate_and_commit(record.id)
        return {
            "success": ok,
            "record_id": record.id,
            "message": f"Helper {helper_name} {'added' if ok else 'failed validation'}",
        }

    def get_edit_history(self, tool_name: str | None = None) -> list[dict]:
        """Get history of all agent edits."""
        records = self.evolution.get_history(tool_name)
        return [
            {
                "id": r.id,
                "timestamp": r.timestamp,
                "action": r.action.value,
                "target": r.target,
                "episode_id": r.episode_id,
                "description": r.description,
                "verified": r.verified,
            }
            for r in records
        ]

    def _rebuild_tool_md(self, meta: dict, body: str) -> str:
        """Rebuild tool.md from metadata dict and markdown body."""
        yaml_str = yaml.dump(meta, allow_unicode=True, default_flow_style=False)
        return f"---\n{yaml_str}---\n{body}"
```

### 1.3 `agent/tools/executor.py` — 集成十-A 验证钩子（修改，~50 行新增）

在 `ToolExecutor` 中增加验证步骤：

```python
# executor.py 新增

@dataclass
class VerificationResult:
    verified: bool
    expected_effect: str
    actual_state: dict
    expected_state: dict
    diff: dict
    suggestion: str | None = None

class ToolExecutor:
    # ... existing code ...
    
    async def execute_and_verify(
        self,
        tool_def: ToolDefinition,
        capability_name: str,
        params: dict[str, Any],
        timeout_ms: int | None = None,
    ) -> tuple[Any, VerificationResult | None]:
        """Execute and verify in one step. Post-action verification hook."""
        # Step 1: Execute
        result = await self.execute(tool_def, capability_name, params, timeout_ms)
        
        # Step 2: Check if this capability has a verify hook
        cap = self._find_capability(tool_def, capability_name)
        verify_config = getattr(cap, 'verify', None)
        
        if verify_config is None:
            return result, None  # No verification configured (yet)
        
        # Step 3: Run verification
        try:
            verify_result = await self._run_verify(
                tool_def, verify_config, params, result
            )
            return result, verify_result
        except Exception as e:
            logger.warning("verify_execution_failed",
                          tool=tool_def.name, capability=capability_name, error=str(e))
            return result, VerificationResult(
                verified=False,
                expected_effect="(verify function failed to execute)",
                actual_state={"error": str(e)},
                expected_state={},
                diff={},
                suggestion="Verify function needs to be fixed or rewritten",
            )
    
    async def _run_verify(
        self, tool_def, verify_config: dict, params: dict, result: Any
    ) -> VerificationResult:
        """Execute the verify function."""
        verify_entry = verify_config["function"]
        module_path, func_name = verify_entry.split(":", 1)
        
        spec = importlib.util.spec_from_file_location(
            f"verify_{tool_def.name}_{func_name}",
            str(tool_def.tool_dir / module_path)
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        verify_func = getattr(mod, func_name)
        
        raw = verify_func(**params, result=result)
        return VerificationResult(**raw)
```

### 1.4 `agent/core.py` — 自愈循环集成（修改，~80 行新增）

在 agent loop 中增加自愈触发逻辑：

```python
class Agent:
    def __init__(self, config_path=None):
        # ... existing ...
        self.evolution = ToolEvolutionManager(
            tools_dir=Path("tools"),
            generated_dir=Path("tools/.generated"),
        )
        self.tool_editor = AgentToolEditor(self.evolution)
    
    async def _handle_tool_failure(
        self,
        error: Exception,
        tool_name: str,
        capability_name: str,
        params: dict,
        conversation: str,
    ) -> bool:
        """Attempt self-healing on tool failure.
        
        Returns True if healing was applied (should retry).
        """
        # Only attempt healing for certain error types
        from agent.errors import ToolNotFoundError, ToolExecutionError
        
        if isinstance(error, ToolNotFoundError):
            # Missing capability — agent needs to create it
            logger.info("self_heal_missing_capability",
                       tool=tool_name, capability=capability_name)
            prompt = self._build_healing_prompt(
                "missing_capability", tool_name, capability_name, params, conversation
            )
            resp = await self._get_provider().complete(prompt, max_tokens=2000)
            healing_action = self._parse_healing_response(resp.content)
            
            if healing_action["action"] == "write_helper":
                result = self.tool_editor.add_helper(
                    tool_name=tool_name,
                    helper_name=healing_action["helper_name"],
                    helper_code=healing_action["code"],
                    episode_id=self._current_episode_id,
                    reason=healing_action["reason"],
                )
                if result["success"]:
                    self.registry.scan()  # Reload registry
                    return True
            
        elif isinstance(error, ToolExecutionError):
            # Existing tool failed — might need verify hook or improvement
            logger.info("self_heal_execution_error",
                       tool=tool_name, capability=capability_name)
            # Check if silent failure (no verify hook)
            tool_def = self.registry.get(tool_name)
            cap = self.registry.find_capability(tool_name, capability_name)
            if cap and not getattr(cap, 'verify', None):
                # Missing verify hook — this could be a silent failure
                prompt = self._build_healing_prompt(
                    "missing_verify", tool_name, capability_name, params, conversation
                )
                resp = await self._get_provider().complete(prompt, max_tokens=2000)
                healing_action = self._parse_healing_response(resp.content)
                
                if healing_action["action"] == "add_verify":
                    result = self.tool_editor.add_verify(
                        tool_name=tool_name,
                        capability_name=capability_name,
                        verify_function=healing_action["code"],
                        episode_id=self._current_episode_id,
                        reason=healing_action["reason"],
                    )
                    if result["success"]:
                        return True  # Retry — verify hook now in place
        
        return False
    
    async def _handle_verification_failure(
        self,
        verify_result: VerificationResult,
        tool_name: str,
        capability_name: str,
        params: dict,
        conversation: str,
    ) -> bool:
        """Handle a verification failure. Trigger self-healing to fix the verify hook."""
        logger.warning("verification_failed",
                      tool=tool_name, capability=capability_name,
                      diff=verify_result.diff)
        
        # The verify hook exists but detected a problem.
        # The agent can either:
        # 1. Improve the verify function (if it's wrong)
        # 2. Fix the tool implementation (if the tool is broken)
        # 3. Accept the state and proceed (if verify is too strict)
        
        prompt = self._build_verification_failure_prompt(
            verify_result, tool_name, capability_name, params, conversation
        )
        resp = await self._get_provider().complete(prompt, max_tokens=1000)
        decision = self._parse_healing_response(resp.content)
        
        if decision["action"] == "fix_verify":
            result = self.tool_editor.add_verify(
                tool_name=tool_name,
                capability_name=capability_name,
                verify_function=decision["code"],
                episode_id=self._current_episode_id,
                reason=f"Fixed inaccurate verify: {decision['reason']}",
            )
            return result["success"]
        elif decision["action"] == "fix_tool":
            # Agent rewrites the tool implementation
            # ... similar to add_helper pattern ...
            pass
        elif decision["action"] == "accept":
            # Verification too strict — log and proceed
            logger.info("verification_accepted_with_warning",
                       tool=tool_name, capability=capability_name)
            return False  # Don't retry, but mark as known issue
        
        return False
    
    def _build_healing_prompt(self, issue_type: str, tool_name: str,
                              capability_name: str, params: dict,
                              conversation: str) -> str:
        """Build a prompt for the self-healing LLM call."""
        if issue_type == "missing_capability":
            return self.prompt_assembler.assemble(PromptInputs(
                role=(
                    "你是工具系统修复专家。代理在执行任务时发现缺少一个工具能力。\n"
                    "请编写缺失的工具函数（Python）。\n"
                    "输出 JSON: {\"action\": \"write_helper\", \"helper_name\": \"...\", "
                    "\"code\": \"...\", \"reason\": \"...\"}"
                ),
                task=(
                    f"缺失的能力: {tool_name}.{capability_name}\n"
                    f"调用参数: {params}\n"
                    f"最近的对话:\n{conversation[-2000:]}\n\n"
                    f"编写一个 Python 函数来实现这个缺失的能力。"
                    f"参考工具目录中现有代码的风格。"
                ),
            ))
        elif issue_type == "missing_verify":
            return self.prompt_assembler.assemble(PromptInputs(
                role=(
                    "你是验证函数编写专家。代理执行工具后无法确认操作是否真正生效（静默失败风险）。\n"
                    "请为该工具编写一个 verify 函数。\n"
                    "输出 JSON: {\"action\": \"add_verify\", \"code\": \"...\", \"reason\": \"...\"}"
                ),
                task=(
                    f"工具: {tool_name}.{capability_name}\n"
                    f"参数: {params}\n"
                    f"最近的对话:\n{conversation[-2000:]}\n\n"
                    f"编写一个 verify 函数，接收工具参数和返回值，判断操作是否真的生效。\n"
                    f"返回值格式: {{'verified': bool, 'expected_effect': str, "
                    f"'actual_state': dict, 'expected_state': dict, 'suggestion': str}}"
                ),
            ))
        # ... other issue types ...
        return ""
```

### 1.5 Phase 1 文件改动汇总

| 文件 | 类型 | 行数 | 说明 |
|------|------|------|------|
| `agent/tools/evolution.py` | **新增** | ~220 | 工具进化管理器（kpatch 类比） |
| `agent/tools/editor.py` | **新增** | ~150 | 代理工具编辑接口（ptrace 类比） |
| `agent/tools/executor.py` | 修改 | +50 | 集成十-A 验证钩子 + execute_and_verify |
| `agent/tools/registry.py` | 修改 | +30 | 热重载 + 版本追踪 |
| `agent/core.py` | 修改 | +80 | 自愈循环 + 验证失败处理 |
| `agent/memory.py` | 修改 | +15 | EvolutionRecord 事件记录 |
| **Phase 1 合计** | | **~545 行** | |

---

## Phase 2: 智能 — 语义压缩 + 双模式调度

### 2.1 `agent/context_compressor.py` — LLM 驱动语义压缩（新增，~250 行）

**OS 内核类比**：zswap + KSM（压缩交换 + 同页合并）——能理解内容的智能压缩。

```python
"""Semantic-aware context compression. 类比: zswap + KSM.

Uses a cheap LLM to decide what's safe to compress and how.
Procedural instructions are NEVER compressed — only reference material.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger()


class ContentType(Enum):
    PROCEDURAL = "procedural"      # Instructions, rules — NEVER compress
    REFERENCE = "reference"        # Docs, facts — safe to summarize
    CONVERSATION = "conversation"  # Dialog — keep recent, summarize old
    EVIDENCE = "evidence"          # Tool results — extract key findings


class CompressionDecision(Enum):
    KEEP_INTACT = "keep_intact"
    SUMMARIZE = "summarize"
    TRUNCATE = "truncate"
    DISCARD = "discard"


@dataclass
class CompressionFeedback:
    """Records outcome of a compression decision for learning."""
    content_id: str
    content_type: ContentType
    decision: CompressionDecision
    was_referenced: bool         # Did agent later need this content?
    episode_success: bool
    tokens_saved: int


class SemanticCompressor:
    """LLM-driven semantic compression with feedback learning.
    
    类比: zswap — compresses pages before swapping.
    KSM — merges semantically similar pages.
    """

    def __init__(self, provider, max_compression_tokens: int = 500):
        self.provider = provider  # Should be a cheap model (e.g. Haiku)
        self.max_compression_tokens = max_compression_tokens
        self._feedback: list[CompressionFeedback] = []
        self._bad_patterns: set[str] = set()  # Content patterns that should NOT be compressed

    async def classify(self, content_id: str, text: str) -> ContentType:
        """Classify content by type. Uses fast heuristics first, LLM as fallback."""
        # Fast heuristics
        if any(marker in text[:200] for marker in [
            "<format_rules", "immutable=", "你必须", "不要", "禁止",
            "先读", "always", "never", "must", "步骤",
        ]):
            return ContentType.PROCEDURAL
        
        if any(marker in text[:200] for marker in [
            "[Step", "[Result from", "[Error]", "[Tool",
            "<function_call>", "<action_report>",
        ]):
            return ContentType.CONVERSATION
        
        if any(marker in text[:200] for marker in [
            "文档", "参考", "API", "手册", "spec", "reference", "doc",
        ]):
            return ContentType.REFERENCE
        
        # For ambiguous content, use LLM classifier (cheap model, ~50 tokens)
        if len(text) > 500:
            try:
                prompt = (
                    "Classify this text as one of: PROCEDURAL (instructions/rules), "
                    "REFERENCE (facts/docs), CONVERSATION (dialog), EVIDENCE (results). "
                    "Reply with one word.\n\n"
                    f"Text (first 300 chars): {text[:300]}"
                )
                resp = await self.provider.complete(prompt, max_tokens=10)
                for ct in ContentType:
                    if ct.value.upper() in resp.content.upper():
                        return ct
            except Exception:
                pass
        
        return ContentType.REFERENCE  # Default: safe to compress

    async def compress(
        self, content_id: str, text: str, content_type: ContentType | None = None,
    ) -> tuple[str, CompressionFeedback]:
        """Compress content based on its type."""
        if content_type is None:
            content_type = await self.classify(content_id, text)
        
        decision = self._decide_compression(content_type, text)
        
        if decision == CompressionDecision.KEEP_INTACT:
            return text, CompressionFeedback(
                content_id=content_id, content_type=content_type,
                decision=decision, was_referenced=False, episode_success=True,
                tokens_saved=0,
            )
        
        if decision == CompressionDecision.DISCARD:
            return "", CompressionFeedback(
                content_id=content_id, content_type=content_type,
                decision=decision, was_referenced=False, episode_success=True,
                tokens_saved=len(text) // 4,
            )
        
        if decision == CompressionDecision.TRUNCATE:
            truncated = text[:1000] + "\n[...truncated...]"
            return truncated, CompressionFeedback(
                content_id=content_id, content_type=content_type,
                decision=decision, was_referenced=False, episode_success=True,
                tokens_saved=(len(text) - len(truncated)) // 4,
            )
        
        # SUMMARIZE — use LLM for smart summarization
        try:
            prompt = (
                "Summarize the following content. "
                "Keep all key facts, numbers, file paths, function names. "
                "Discard narrative filler and repetition.\n\n"
                f"{text[:3000]}"
            )
            resp = await self.provider.complete(prompt, max_tokens=self.max_compression_tokens)
            summary = resp.content
            
            return summary, CompressionFeedback(
                content_id=content_id, content_type=content_type,
                decision=decision, was_referenced=False, episode_success=True,
                tokens_saved=(len(text) - len(summary)) // 4,
            )
        except Exception as e:
            logger.error("compression_llm_failed", error=str(e))
            # Fallback: simple truncation
            return text[:500], CompressionFeedback(
                content_id=content_id, content_type=content_type,
                decision=CompressionDecision.TRUNCATE, was_referenced=False,
                episode_success=True, tokens_saved=(len(text) - 500) // 4,
            )

    def _decide_compression(self, content_type: ContentType, text: str) -> CompressionDecision:
        """Decide compression strategy based on content type."""
        if content_type == ContentType.PROCEDURAL:
            return CompressionDecision.KEEP_INTACT  # NEVER compress
        
        if len(text) < 200:
            return CompressionDecision.KEEP_INTACT  # Too short to compress
        
        if content_type == ContentType.EVIDENCE:
            if len(text) > 2000:
                return CompressionDecision.SUMMARIZE
            return CompressionDecision.KEEP_INTACT
        
        if content_type == ContentType.CONVERSATION:
            if len(text) > 3000:
                return CompressionDecision.SUMMARIZE
            return CompressionDecision.TRUNCATE
        
        if content_type == ContentType.REFERENCE:
            if len(text) > 1000:
                return CompressionDecision.SUMMARIZE
            return CompressionDecision.KEEP_INTACT
        
        return CompressionDecision.KEEP_INTACT

    def record_feedback(self, content_id: str, was_referenced: bool,
                        episode_success: bool):
        """Record whether compressed content was later needed.
        
        If compressed content was referenced but unavailable → the compression
        was too aggressive → adjust future decisions.
        """
        for fb in self._feedback:
            if fb.content_id == content_id:
                fb.was_referenced = was_referenced
                fb.episode_success = episode_success
                
                if was_referenced and not episode_success:
                    # Compression caused harm — learn from this
                    pattern = self._extract_pattern(content_id)
                    self._bad_patterns.add(pattern)
                    logger.warning("compression_caused_failure",
                                  content_id=content_id, pattern=pattern)
                break

    def _extract_pattern(self, content_id: str) -> str:
        """Extract a fingerprint of content that should NOT be compressed."""
        return content_id.split(":")[0] if ":" in content_id else content_id
```

### 2.2 `agent/context.py` — 集成语义压缩（修改，~40 行）

```python
# context.py 修改

class ContextManager:
    def __init__(self, max_tokens: int = 100000, compressor: SemanticCompressor | None = None):
        # ... existing ...
        self.compressor = compressor
    
    async def compress_conversation_async(self, conversation_text: str,
                                          keep_last_n: int = 5) -> str:
        """Async version using semantic compressor when available."""
        if self.compressor:
            content_id = f"conversation:{hash(conversation_text)}"
            content_type = await self.compressor.classify(content_id, conversation_text)
            
            if content_type == ContentType.PROCEDURAL:
                # NEVER compress procedural content (Hermes bug prevention)
                return conversation_text
            
            compressed, feedback = await self.compressor.compress(
                content_id, conversation_text, content_type
            )
            self.compressor.record_feedback(content_id, False, True)
            return compressed
        
        # Fallback to original simple compression
        return self.compress_conversation(conversation_text, keep_last_n)
```

### 2.3 `agent/core.py` — 双模式调度器集成（修改，~100 行）

```python
# core.py 新增

from enum import Enum

class ExecutionMode(Enum):
    EXPLORE = "explore"  # New domain — use strong model, more iterations, record everything
    EXPLOIT = "exploit"  # Known domain — use cheap model, fewer iterations, inject skills


class Agent:
    # ... existing ...
    
    async def _select_mode(self, task_description: str) -> tuple[ExecutionMode, dict]:
        """Classify task as known domain (exploit) or new domain (explore).
        
        Decision factors:
        1. Matching skills in skill repository
        2. Similar successful episodes in memory
        3. Explicit user hint ("像上次那样...")
        """
        mode_info = {
            "mode": ExecutionMode.EXPLORE,
            "confidence": 0.0,
            "matched_skills": [],
            "similar_episodes": [],
            "reason": "",
        }
        
        # Factor 1: Skill match
        matching_skills = await self._find_matching_skills(task_description)
        if matching_skills:
            mode_info["matched_skills"] = matching_skills
            mode_info["confidence"] += 0.4
        
        # Factor 2: Similar episodes
        similar = self.memory.search_similar_episodes(task_description, limit=3)
        successful = [e for e in similar if e.get("success")]
        if successful:
            mode_info["similar_episodes"] = successful
            mode_info["confidence"] += 0.3
        
        # Factor 3: Explicit hint
        if any(hint in task_description for hint in ["像上次", "和之前一样", "同样的", "再次"]):
            mode_info["confidence"] += 0.2
        
        if mode_info["confidence"] >= 0.5:
            mode_info["mode"] = ExecutionMode.EXPLOIT
            mode_info["reason"] = (
                f"Matched {len(matching_skills)} skills and "
                f"{len(successful)} similar episodes (confidence: {mode_info['confidence']:.0%})"
            )
        else:
            mode_info["mode"] = ExecutionMode.EXPLORE
            mode_info["reason"] = (
                f"No strong matches found (confidence: {mode_info['confidence']:.0%})"
            )
        
        logger.info("mode_selected", mode=mode_info["mode"].value, reason=mode_info["reason"])
        return mode_info["mode"], mode_info
    
    def _get_provider_for_mode(self, mode: ExecutionMode):
        """Select provider based on execution mode."""
        if mode == ExecutionMode.EXPLOIT:
            # Known domain → use cheapest capable model
            return self.provider_pool.get_cheapest(min_capability_score=0.7)
        else:
            # New domain → use strongest model
            return self.provider_pool.get_strongest()
    
    async def _inject_mode_context(self, mode: ExecutionMode, mode_info: dict) -> str:
        """Build mode-specific context for the prompt."""
        if mode == ExecutionMode.EXPLOIT:
            parts = ["## 已知领域 — 利用模式\n"]
            parts.append("以下是历史上成功完成类似任务的方法，请优先参考：\n")
            
            for skill in mode_info.get("matched_skills", []):
                parts.append(f"\n### 技能: {skill['name']}")
                parts.append(f"成功率: {skill.get('success_rate', '?')}%")
                parts.append(f"方法:\n{skill.get('approach', '')}")
            
            for ep in mode_info.get("similar_episodes", [])[:2]:
                parts.append(f"\n### 历史任务: {ep.get('task_summary', '')[:200]}")
                parts.append(f"使用的工具: {', '.join(ep.get('tools_used', []))}")
            
            return "\n".join(parts)
        else:
            return (
                "## 新领域 — 探索模式\n"
                "这是新的任务类型，没有可直接复用的历史方法。\n"
                "请仔细探索，记录所有尝试过程，为未来的类似任务积累经验。"
            )
    
    async def _find_matching_skills(self, task: str) -> list[dict]:
        """Search skill repository for matching skills."""
        # Uses FTS5 for now, will be replaced by skill system in Phase 3
        results = self.memory.search_semantic(task, entry_type="skill", limit=5)
        return [
            {
                "name": r.get("title", ""),
                "success_rate": r.get("success_rate", 0),
                "approach": r.get("content", ""),
                "triggers": r.get("triggers", []),
            }
            for r in results
            if r.get("success_rate", 0) > 50  # Only return reliable skills
        ]
```

### 2.4 Phase 2 文件改动汇总

| 文件 | 类型 | 行数 | 说明 |
|------|------|------|------|
| `agent/context_compressor.py` | **新增** | ~250 | LLM 语义压缩引擎 |
| `agent/context.py` | 修改 | +40 | 集成语义压缩 |
| `agent/core.py` | 修改 | +100 | 双模式调度 + 模式感知 provider 选择 |
| `agent/providers/router.py` | 修改 | +20 | 新增 `get_cheapest(min_capability_score)` 方法 |
| **Phase 2 合计** | | **~410 行** | |

---

## Phase 3: 学习 — 技能社交网络

### 3.1 技能数据模型与仓库

**`agent/skills/__init__.py`**（新增，~20 行）:

```python
"""Agent skill system. 类比: shared libraries (.so) + ld.so.cache.

Skills are reusable knowledge units accumulated across episodes.
They form a social network: create → consume → rate → iterate → retire → merge.
"""

from .models import Skill, SkillFeedback, SkillLevel
from .repository import SkillRepository
from .lifecycle import SkillLifecycle
from .pii_gate import PIIGate
```

**`agent/skills/models.py`**（新增，~80 行）:

```python
"""Skill data models."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
import uuid


class SkillLevel(Enum):
    L1_UI = 1           # Step-by-step UI interaction instructions
    L2_API = 2          # HTTP API calls (reverse-engineered from browser traffic)
    L3_META = 3         # Pattern rewrites (meta-skills that create other skills)


@dataclass
class SkillFeedback:
    rating: int          # +1 (worked) or -1 (didn't work)
    reason: str          # Written reason — more important than rating
    episode_id: str
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class Skill:
    id: str
    name: str
    task_type: str       # "web-automation", "file-manipulation", "data-processing", ...
    domain: str          # "github-login", "csv-parsing", "db-migration", ...
    triggers: list[str]  # Keywords that should trigger this skill
    level: SkillLevel
    approach: str        # Step-by-step instructions
    preconditions: list[str] = field(default_factory=list)
    postconditions: list[str] = field(default_factory=list)
    success_rate: float = 0.0
    uses: int = 0
    created_by: str = ""    # episode_id
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    last_used: str = ""
    feedback: list[SkillFeedback] = field(default_factory=list)
    score: int = 0          # Sum of feedback ratings. < -3 → retired
    retired: bool = False
    merged_from: list[str] = field(default_factory=list)  # IDs of merged skills
    pii_checked: bool = False
    tags: list[str] = field(default_factory=list)
    
    @property
    def is_active(self) -> bool:
        return not self.retired and self.score >= -3
    
    @property
    def quality_score(self) -> float:
        """Composite quality score."""
        if self.uses == 0:
            return 0.5  # Neutral for new skills
        feedback_score = max(0, (self.score / max(1, len(self.feedback))) + 3) / 6
        usage_bonus = min(0.3, self.uses / 100)
        return min(1.0, feedback_score + usage_bonus)
```

**`agent/skills/repository.py`**（新增，~200 行）:

```python
"""Skill storage and retrieval. SQLite-backed with FTS5 search."""

import json
import sqlite3
from pathlib import Path

import structlog

from .models import Skill, SkillFeedback, SkillLevel

logger = structlog.get_logger()


class SkillRepository:
    """Skill storage with full-text search."""
    
    def __init__(self, db_path: str = "data/skills.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()
    
    def _init_schema(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS skills (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                task_type TEXT NOT NULL,
                domain TEXT NOT NULL,
                triggers TEXT NOT NULL DEFAULT '[]',
                level INTEGER NOT NULL DEFAULT 1,
                approach TEXT NOT NULL,
                preconditions TEXT DEFAULT '[]',
                postconditions TEXT DEFAULT '[]',
                success_rate REAL DEFAULT 0.0,
                uses INTEGER DEFAULT 0,
                created_by TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                last_used TEXT DEFAULT '',
                score INTEGER DEFAULT 0,
                retired INTEGER DEFAULT 0,
                merged_from TEXT DEFAULT '[]',
                pii_checked INTEGER DEFAULT 0,
                tags TEXT DEFAULT '[]'
            );
            
            CREATE TABLE IF NOT EXISTS skill_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                skill_id TEXT NOT NULL,
                rating INTEGER NOT NULL,
                reason TEXT NOT NULL,
                episode_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (skill_id) REFERENCES skills(id)
            );
            
            CREATE VIRTUAL TABLE IF NOT EXISTS skills_fts USING fts5(
                name, task_type, domain, triggers, approach, tags,
                content='skills', content_rowid='rowid'
            );
            
            CREATE INDEX IF NOT EXISTS idx_skills_task_type ON skills(task_type);
            CREATE INDEX IF NOT EXISTS idx_skills_domain ON skills(domain);
            CREATE INDEX IF NOT EXISTS idx_skills_score ON skills(score);
            CREATE INDEX IF NOT EXISTS idx_skills_retired ON skills(retired);
        """)
        self.conn.commit()
    
    def save(self, skill: Skill) -> bool:
        try:
            self.conn.execute("""
                INSERT OR REPLACE INTO skills
                (id, name, task_type, domain, triggers, level, approach,
                 preconditions, postconditions, success_rate, uses, created_by,
                 created_at, last_used, score, retired, merged_from, pii_checked, tags)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                skill.id, skill.name, skill.task_type, skill.domain,
                json.dumps(skill.triggers, ensure_ascii=False),
                skill.level.value, skill.approach,
                json.dumps(skill.preconditions, ensure_ascii=False),
                json.dumps(skill.postconditions, ensure_ascii=False),
                skill.success_rate, skill.uses, skill.created_by,
                skill.created_at, skill.last_used, skill.score,
                1 if skill.retired else 0,
                json.dumps(skill.merged_from),
                1 if skill.pii_checked else 0,
                json.dumps(skill.tags, ensure_ascii=False),
            ))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error("skill_save_failed", error=str(e))
            return False
    
    def search(self, query: str, limit: int = 5,
               task_type: str | None = None) -> list[Skill]:
        """Full-text search for skills matching the query."""
        sql = """
            SELECT s.* FROM skills s
            JOIN skills_fts fts ON s.rowid = fts.rowid
            WHERE skills_fts MATCH ?
            AND s.retired = 0
        """
        params = [query]
        if task_type:
            sql += " AND s.task_type = ?"
            params.append(task_type)
        sql += " ORDER BY s.score DESC, s.success_rate DESC LIMIT ?"
        params.append(limit)
        
        rows = self.conn.execute(sql, params).fetchall()
        return [self._row_to_skill(r) for r in rows]
    
    def find_by_triggers(self, text: str, limit: int = 5) -> list[Skill]:
        """Find skills whose triggers match the input text."""
        # Simple substring match on trigger keywords (complementary to FTS)
        rows = self.conn.execute(
            "SELECT * FROM skills WHERE retired = 0 ORDER BY score DESC"
        ).fetchall()
        
        matched = []
        for row in rows:
            skill = self._row_to_skill(row)
            for trigger in skill.triggers:
                if trigger.lower() in text.lower():
                    matched.append(skill)
                    break
        
        matched.sort(key=lambda s: s.quality_score, reverse=True)
        return matched[:limit]
    
    def find_near_duplicates(self, skill: Skill, threshold: float = 0.7) -> list[Skill]:
        """Find skills that are near-duplicates (for merging)."""
        # Search by same task_type + domain
        rows = self.conn.execute(
            "SELECT * FROM skills WHERE task_type = ? AND domain = ? AND retired = 0 AND id != ?",
            (skill.task_type, skill.domain, skill.id)
        ).fetchall()
        
        candidates = [self._row_to_skill(r) for r in rows]
        
        # Simple overlap score on triggers
        duplicates = []
        for c in candidates:
            overlap = len(set(skill.triggers) & set(c.triggers))
            total = len(set(skill.triggers) | set(c.triggers))
            if total > 0 and overlap / total >= threshold:
                duplicates.append(c)
        
        return duplicates
    
    def retire(self, skill_id: str) -> bool:
        self.conn.execute("UPDATE skills SET retired = 1 WHERE id = ?", (skill_id,))
        self.conn.commit()
        return True
    
    def get_active(self, limit: int = 50) -> list[Skill]:
        rows = self.conn.execute(
            "SELECT * FROM skills WHERE retired = 0 ORDER BY score DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [self._row_to_skill(r) for r in rows]
    
    def _row_to_skill(self, row) -> Skill:
        return Skill(
            id=row["id"],
            name=row["name"],
            task_type=row["task_type"],
            domain=row["domain"],
            triggers=json.loads(row["triggers"]),
            level=SkillLevel(row["level"]),
            approach=row["approach"],
            preconditions=json.loads(row["preconditions"]),
            postconditions=json.loads(row["postconditions"]),
            success_rate=row["success_rate"],
            uses=row["uses"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            last_used=row["last_used"],
            score=row["score"],
            retired=bool(row["retired"]),
            merged_from=json.loads(row["merged_from"]),
            pii_checked=bool(row["pii_checked"]),
            tags=json.loads(row["tags"]),
        )
```

**`agent/skills/lifecycle.py`**（新增，~150 行）:

```python
"""Skill lifecycle management: rating, retirement, merging."""

import structlog

from .models import Skill, SkillFeedback
from .repository import SkillRepository

logger = structlog.get_logger()


class SkillLifecycle:
    """Manages skill lifecycle: create → consume → rate → iterate → retire → merge."""
    
    def __init__(self, repository: SkillRepository):
        self.repo = repository
    
    def record_feedback(self, skill_id: str, rating: int, reason: str,
                        episode_id: str) -> Skill | None:
        """Record feedback on a skill. +1 (worked), -1 (didn't work).
        
        Written reason is MORE important than rating — it tells future agents
        exactly what to fix.
        """
        skill = self._get_skill(skill_id)
        if not skill:
            return None
        
        fb = SkillFeedback(
            rating=rating,
            reason=reason,
            episode_id=episode_id,
        )
        skill.feedback.append(fb)
        skill.score += rating
        skill.uses += 1
        skill.success_rate = (
            sum(1 for f in skill.feedback if f.rating > 0) / len(skill.feedback)
            if skill.feedback else 0.0
        )
        
        # Auto-retirement check
        if skill.score < -3 and not skill.retired:
            logger.warning("skill_auto_retired",
                          skill_id=skill_id, score=skill.score,
                          reason="Score below -3 threshold")
            skill.retired = True
        
        # Save feedback to DB
        self.repo.conn.execute(
            "INSERT INTO skill_feedback (skill_id, rating, reason, episode_id, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            (skill_id, rating, reason, episode_id, fb.timestamp)
        )
        self.repo.conn.commit()
        
        self.repo.save(skill)
        return skill
    
    def merge_duplicates(self, skill_id: str) -> Skill | None:
        """Find and merge near-duplicate skills."""
        skill = self._get_skill(skill_id)
        if not skill:
            return None
        
        duplicates = self.repo.find_near_duplicates(skill)
        if not duplicates:
            return None
        
        # Merge: keep the higher-scored one, absorb the other's feedback
        best = max([skill] + duplicates, key=lambda s: s.quality_score)
        
        for dup in duplicates:
            if dup.id == best.id:
                continue
            # Absorb feedback
            for fb in self._get_feedback(dup.id):
                best.feedback.append(fb)
            best.score += dup.score
            best.merged_from.append(dup.id)
            best.triggers = list(set(best.triggers + dup.triggers))
            # Retire the duplicate
            self.repo.retire(dup.id)
            logger.info("skill_merged", kept=best.id, retired=dup.id)
        
        self.repo.save(best)
        return best
    
    def _get_skill(self, skill_id: str) -> Skill | None:
        row = self.repo.conn.execute(
            "SELECT * FROM skills WHERE id = ?", (skill_id,)
        ).fetchone()
        return self.repo._row_to_skill(row) if row else None
    
    def _get_feedback(self, skill_id: str) -> list[SkillFeedback]:
        rows = self.repo.conn.execute(
            "SELECT * FROM skill_feedback WHERE skill_id = ?", (skill_id,)
        ).fetchall()
        return [
            SkillFeedback(rating=r["rating"], reason=r["reason"],
                         episode_id=r["episode_id"], timestamp=r["timestamp"])
            for r in rows
        ]
```

**`agent/skills/pii_gate.py`**（新增，~100 行）:

```python
"""PII gating for skills. Prevents sensitive data from being saved in shared skills."""

import re
import structlog

logger = structlog.get_logger()

# Rule-based PII patterns
PII_PATTERNS = [
    (re.compile(r'[\w\.-]+@[\w\.-]+\.\w+'), 'email'),
    (re.compile(r'Bearer\s+[A-Za-z0-9\-._~+/]+=*'), 'bearer_token'),
    (re.compile(r'sk-[A-Za-z0-9]{32,}'), 'api_key'),
    (re.compile(r'AKIA[0-9A-Z]{16}'), 'aws_access_key'),
    (re.compile(r'[\da-fA-F]{8}-[\da-fA-F]{4}-[\da-fA-F]{4}-[\da-fA-F]{4}-[\da-fA-F]{12}'),
     'uuid_potential_session'),
    (re.compile(r'(?:password|passwd|pwd|secret|token|key)\s*[:=]\s*\S+', re.I),
     'credential_assignment'),
    (re.compile(r'-----BEGIN (?:RSA |EC )?PRIVATE KEY-----'), 'private_key'),
    (re.compile(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b'), 'ip_address'),
]


class PIIGate:
    """Two-layer PII detection: rule-based + LLM double-check."""
    
    def __init__(self, llm_provider=None):
        self.provider = llm_provider  # Optional LLM for second pass
    
    def check_rules(self, text: str) -> list[dict]:
        """Rule-based PII scan. Returns list of findings."""
        findings = []
        for pattern, pii_type in PII_PATTERNS:
            matches = pattern.findall(text)
            for match in matches:
                findings.append({
                    "type": pii_type,
                    "match": str(match)[:50],
                    "method": "rule",
                })
        return findings
    
    async def check_llm(self, text: str) -> list[dict]:
        """LLM-based PII scan for semantic detection (emails in prose, etc.)."""
        if not self.provider:
            return []
        
        prompt = (
            "Scan the following text for PII (personally identifiable information). "
            "Look for: email addresses, API keys, tokens, passwords, personal names, "
            "phone numbers, physical addresses, session IDs, internal URLs with credentials.\n\n"
            "Respond with a JSON array of findings: "
            '[{"type": "email|token|password|name|phone|address|session|url", '
            '"description": "what was found (redacted)"}]\n'
            'If nothing found, respond with [].\n\n'
            f"Text:\n{text[:2000]}"
        )
        
        try:
            resp = await self.provider.complete(prompt, max_tokens=200)
            import json
            return json.loads(resp.content.strip())
        except Exception as e:
            logger.error("pii_llm_check_failed", error=str(e))
            return []
    
    async def validate(self, skill_name: str, content: str) -> tuple[bool, list[dict]]:
        """Validate skill content for PII. Returns (clean, findings)."""
        all_findings = self.check_rules(content)
        
        if self.provider:
            llm_findings = await self.check_llm(content)
            all_findings.extend(llm_findings)
        
        if all_findings:
            logger.warning("pii_detected_in_skill",
                          skill=skill_name,
                          finding_count=len(all_findings),
                          types=[f["type"] for f in all_findings])
            return False, all_findings
        
        return True, []
```

### 3.2 与现有系统的集成

**`agent/consolidation.py`** 新增技能提取（修改，~60 行）：

在 `consolidate()` 末尾，增加从成功 episode 中提取技能的步骤：

```python
async def _extract_skill_from_episode(self, episode: EpisodeEntry) -> Skill | None:
    """Extract a reusable skill from a successful episode."""
    if not episode.success:
        return None
    
    prompt = f"""分析以下成功完成的任务，提取可复用的"技能"。

任务描述: {episode.task_summary}
使用的工具: {', '.join(episode.tools_used)}
执行步骤数: {episode.steps}
结果: 成功

请提取:
1. 技能名称（简短）
2. 技能适用的触发条件（关键词列表）
3. 执行方法（步骤说明，2-5 步）
4. 前置条件（需要什么环境/状态）
5. 后置条件（执行后应该是什么状态）

输出 JSON:
{{"name": "...", "triggers": [...], "approach": "...", 
  "preconditions": [...], "postconditions": [...]}}
"""
    resp = await self.provider.complete(prompt, max_tokens=500)
    # Parse and create Skill...
```

**`agent/core.py`** 技能注入（修改，~30 行）：

在 prompt 组装时注入匹配的技能：

```python
# 在 run() 和 goal_run() 的 prompt 构建阶段
matching_skills = self.skill_repo.search(task_description, limit=3)
if matching_skills:
    skills_context = "## 可参考的技能（已验证）\n\n"
    for s in matching_skills:
        skills_context += (
            f"### {s.name} (成功率: {s.success_rate:.0%}, 使用: {s.uses}次)\n"
            f"触发条件: {', '.join(s.triggers)}\n"
            f"方法:\n{s.approach}\n\n"
        )
    inputs.memory_context += "\n" + skills_context
```

### 3.3 Phase 3 文件改动汇总

| 文件 | 类型 | 行数 | 说明 |
|------|------|------|------|
| `agent/skills/__init__.py` | **新增** | ~20 | 技能系统入口 |
| `agent/skills/models.py` | **新增** | ~80 | Skill, SkillFeedback, SkillLevel |
| `agent/skills/repository.py` | **新增** | ~200 | SQLite + FTS5 存储和搜索 |
| `agent/skills/lifecycle.py` | **新增** | ~150 | 评分、退役、合并 |
| `agent/skills/pii_gate.py` | **新增** | ~100 | 规则 + LLM 双重 PII 检测 |
| `agent/consolidation.py` | 修改 | +60 | 技能提取 |
| `agent/core.py` | 修改 | +30 | 技能注入 prompt |
| **Phase 3 合计** | | **~640 行** | |

---

## Phase 4: 扩展 — 原生浏览器适配器

### 4.1 `agent/tools/browser/daemon.py` — CDP 守护进程（新增，~220 行）

**OS 内核类比**：`kthread`——内核线程，在后台持续运行，不受用户进程生命周期影响。

```python
"""CDP daemon. 类比: kthread — persistent background kernel thread.

Maintains a persistent Chrome DevTools Protocol connection across
LLM cognitive pauses. Handles Chrome discovery, launch, and IPC.
"""

import asyncio
import json
import os
import secrets
import signal
import socket
import subprocess
import time
from pathlib import Path

import structlog
import websockets

logger = structlog.get_logger()

# Known Chrome/Chromium install paths (Windows)
CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Chromium\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Chromium\Application\chrome.exe"),
]


class BrowserDaemon:
    """Persistent CDP connection manager. 类比: kthread.
    
    Each BU_NAME gets one daemon. IPC via TCP loopback (Windows).
    Token-based security prevents unauthorized CDP commands.
    """
    
    def __init__(self, name: str = "default", port: int = 9222):
        self.name = name
        self.port = port
        self.token = secrets.token_hex(16)
        self._chrome_process: subprocess.Popen | None = None
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._running = False
        self._user_data_dir: Path | None = None
    
    async def start(self, headless: bool = True) -> bool:
        """Start the browser daemon. Launches Chrome if needed."""
        # 1. Check if Chrome is already running with DevTools
        chrome_ws = await self._find_running_chrome()
        if chrome_ws:
            self._ws = await websockets.connect(chrome_ws)
            logger.info("daemon_attached_existing", name=self.name, ws=chrome_ws)
            self._running = True
            return True
        
        # 2. Launch new Chrome
        self._user_data_dir = Path(os.environ.get("TEMP", "/tmp")) / f"browser-harness-{self.name}"
        self._user_data_dir.mkdir(parents=True, exist_ok=True)
        
        chrome_exe = self._find_chrome_exe()
        if not chrome_exe:
            logger.error("daemon_chrome_not_found")
            return False
        
        args = [
            chrome_exe,
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={self._user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--disable-background-networking",
            "--disable-sync",
            "--no-sandbox",  # Needed in some CI/container environments
        ]
        if headless:
            args.append("--headless=new")  # New headless mode (Chrome 112+)
        
        try:
            self._chrome_process = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            logger.error("daemon_launch_failed", chrome=chrome_exe)
            return False
        
        # 3. Wait for DevTools port to be ready
        ws_url = await self._wait_for_devtools(timeout=10)
        if not ws_url:
            return False
        
        self._ws = await websockets.connect(ws_url)
        self._running = True
        logger.info("daemon_started", name=self.name, port=self.port)
        return True
    
    async def send(self, method: str, params: dict | None = None) -> dict:
        """Send a CDP command and get the response."""
        if not self._ws:
            raise RuntimeError("Daemon not running")
        
        msg = {
            "id": int(time.time() * 1000000),
            "method": method,
            "params": params or {},
        }
        # Include auth token
        params_with_auth = (params or {}) | {"_token": self.token}
        msg["params"] = params_with_auth
        
        await self._ws.send(json.dumps(msg))
        response = await asyncio.wait_for(self._ws.recv(), timeout=30)
        return json.loads(response)
    
    async def stop(self):
        """Graceful shutdown."""
        self._running = False
        if self._ws:
            await self._ws.close()
        if self._chrome_process:
            self._chrome_process.terminate()
            try:
                self._chrome_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._chrome_process.kill()
        logger.info("daemon_stopped", name=self.name)
    
    def _find_chrome_exe(self) -> str | None:
        for path in CHROME_PATHS:
            if os.path.exists(path):
                return path
        # Try 'chrome' or 'chromium' on PATH
        for cmd in ["chrome", "chromium", "chromium-browser", "google-chrome"]:
            result = subprocess.run(["where", cmd], capture_output=True, text=True)
            if result.returncode == 0:
                return result.stdout.strip().split("\n")[0]
        return None
    
    async def _find_running_chrome(self) -> str | None:
        """Check if a Chrome with DevTools is already listening."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", self.port),
                timeout=2,
            )
            # Probe /json/version endpoint
            request = (
                f"GET /json/version HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{self.port}\r\n"
                f"Connection: close\r\n\r\n"
            )
            writer.write(request.encode())
            await writer.drain()
            
            response = b""
            while True:
                try:
                    chunk = await asyncio.wait_for(reader.read(4096), timeout=1)
                    if not chunk:
                        break
                    response += chunk
                except TimeoutError:
                    break
            
            writer.close()
            
            if b"webSocketDebuggerUrl" in response:
                # Parse the JSON response to get WebSocket URL
                body = response.decode().split("\r\n\r\n", 1)[1]
                data = json.loads(body)
                return data.get("webSocketDebuggerUrl")
        except Exception:
            pass
        return None
    
    async def _wait_for_devtools(self, timeout: float = 10) -> str | None:
        """Poll until DevTools port is ready, return WS URL."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            ws_url = await self._find_running_chrome()
            if ws_url:
                return ws_url
            await asyncio.sleep(0.5)
        return None
```

### 4.2 `agent/tools/browser/helpers.py` — 浏览器辅助函数（新增，~180 行）

```python
"""Browser interaction helpers. Agent-editable surface.

Design decisions (from Browser Harness):
- Coordinate click default (Input.dispatchMouseEvent at compositor level)
- Screenshot-first: capture → read pixels → click → verify
- Direct CDP, no framework abstraction
- Core helpers stay short (~200 lines)
- Suppress "locate first, then click" reflex
"""

import asyncio
import base64
import json
import time


class BrowserHelpers:
    """Browser interaction helpers. 类比: VFS file_operations.
    
    All helpers pre-imported into the agent's execution namespace.
    """
    
    def __init__(self, daemon):
        self.daemon = daemon
    
    # === Navigation ===
    
    async def navigate(self, url: str) -> dict:
        """Navigate to a URL."""
        return await self.daemon.send("Page.navigate", {"url": url})
    
    async def reload(self) -> dict:
        return await self.daemon.send("Page.reload")
    
    async def current_url(self) -> str:
        """Get the current page URL."""
        # Use Runtime.evaluate for simple JS
        result = await self.js("window.location.href")
        return result.get("result", {}).get("value", "")
    
    # === Screenshot (primary interaction pattern) ===
    
    async def capture_screenshot(self) -> str:
        """Capture a screenshot. Returns base64-encoded PNG."""
        result = await self.daemon.send("Page.captureScreenshot", {
            "format": "png",
            "fromSurface": True,
        })
        return result.get("result", {}).get("data", "")
    
    # === Coordinate click (DEFAULT interaction pattern) ===
    
    async def click_at_xy(self, x: float, y: float) -> dict:
        """Click at pixel coordinates. Compositor-level — bypasses iframe/shadow DOM."""
        # Mouse pressed
        await self.daemon.send("Input.dispatchMouseEvent", {
            "type": "mousePressed",
            "x": x, "y": y,
            "button": "left",
            "clickCount": 1,
        })
        # Mouse released
        result = await self.daemon.send("Input.dispatchMouseEvent", {
            "type": "mouseReleased",
            "x": x, "y": y,
            "button": "left",
            "clickCount": 1,
        })
        return result
    
    async def double_click_at_xy(self, x: float, y: float) -> dict:
        await self.daemon.send("Input.dispatchMouseEvent", {
            "type": "mousePressed", "x": x, "y": y,
            "button": "left", "clickCount": 2,
        })
        return await self.daemon.send("Input.dispatchMouseEvent", {
            "type": "mouseReleased", "x": x, "y": y,
            "button": "left", "clickCount": 2,
        })
    
    # === Keyboard ===
    
    async def type_text(self, text: str) -> dict:
        """Type text at current focus."""
        return await self.daemon.send("Input.insertText", {"text": text})
    
    async def press_key(self, key: str) -> dict:
        """Press a key (e.g. 'Enter', 'Escape', 'Tab')."""
        return await self.daemon.send("Input.dispatchKeyEvent", {
            "type": "keyDown",
            "key": key,
        })
    
    # === DOM / JavaScript (fallback for structured data extraction) ===
    
    async def js(self, expression: str) -> dict:
        """Execute JavaScript. Auto-wrapped in IIFE."""
        return await self.daemon.send("Runtime.evaluate", {
            "expression": f"(function() {{ return {expression}; }})()",
            "returnByValue": True,
            "awaitPromise": True,
        })
    
    async def get_page_text(self) -> str:
        """Get all visible text content."""
        result = await self.js("document.body.innerText")
        return result.get("result", {}).get("value", "")
    
    async def get_element_info(self, selector: str) -> dict:
        """Get bounding box and attributes of an element (DOM fallback)."""
        result = await self.js(f"""
            (function() {{
                const el = document.querySelector('{selector}');
                if (!el) return null;
                const rect = el.getBoundingClientRect();
                return {{
                    x: rect.x, y: rect.y,
                    width: rect.width, height: rect.height,
                    visible: rect.width > 0 && rect.height > 0,
                    text: el.textContent?.substring(0, 200),
                    tag: el.tagName,
                }};
            }})()
        """)
        return result.get("result", {}).get("value", {})
    
    # === Input (framework-aware) ===
    
    async def fill_input(self, selector: str, value: str) -> dict:
        """Fill an input field. Framework-aware (React/Vue/Ember)."""
        # Focus the element
        await self.js(f"""
            (function() {{
                const el = document.querySelector('{selector}');
                if (!el) return;
                el.focus();
                // Trigger React/Vue change event
                const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value'
                ).set;
                nativeInputValueSetter.call(el, '{value}');
                el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                el.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }})()
        """)
        # Also type via CDP for realism
        return await self.type_text(value)
    
    # === CDP raw channel (escape hatch) ===
    
    async def cdp(self, method: str, params: dict | None = None) -> dict:
        """Raw CDP command. Escape hatch for anything not in helpers."""
        return await self.daemon.send(method, params)
    
    # === HTTP (for API-level skill extraction) ===
    
    async def capture_network_requests(self) -> list[dict]:
        """Get captured network requests. Requires Network.enable first."""
        # The daemon would need to buffer these
        return []  # Placeholder
    
    # === Page info ===
    
    async def page_info(self) -> dict:
        """Get page metadata including dialogs, title."""
        title = await self.js("document.title")
        url = await self.current_url()
        return {
            "title": title.get("result", {}).get("value", ""),
            "url": url,
        }
    
    async def wait_for_network_idle(self, timeout: float = 5.0) -> bool:
        """Wait for network to become idle."""
        # Simple polling approach
        deadline = time.monotonic() + timeout
        last_activity = time.monotonic()
        while time.monotonic() < deadline:
            # Check if there are active network requests
            # (simplified — full impl would track Network.loadingFailed/loadingFinished)
            await asyncio.sleep(0.5)
        return True
```

### 4.3 `agent/tools/browser/tool.md` — 工具定义（新增，~60 行）

```yaml
---
name: browser-harness
version: "0.1.0"
description: "Browser automation via direct CDP — coordinate-click default, screenshot-first"
objects: [web-page, web-element, browser-tab]
source: builtin
runtime: import
entry_points:
  navigate: helpers.py:BrowserHelpers.navigate
  capture_screenshot: helpers.py:BrowserHelpers.capture_screenshot
  click_at_xy: helpers.py:BrowserHelpers.click_at_xy
  type_text: helpers.py:BrowserHelpers.type_text
  press_key: helpers.py:BrowserHelpers.press_key
  js: helpers.py:BrowserHelpers.js
  get_page_text: helpers.py:BrowserHelpers.get_page_text
  get_element_info: helpers.py:BrowserHelpers.get_element_info
  fill_input: helpers.py:BrowserHelpers.fill_input
  cdp: helpers.py:BrowserHelpers.cdp
  page_info: helpers.py:BrowserHelpers.page_info
  wait_for_network_idle: helpers.py:BrowserHelpers.wait_for_network_idle
capabilities:
  - name: navigate
    params:
      url: {type: string, required: true}
    description: "Navigate to a URL"
  - name: capture_screenshot
    params: {}
    description: "Capture a screenshot of the current page. Returns base64 PNG."
    returns: "base64-encoded PNG image"
  - name: click_at_xy
    params:
      x: {type: number, required: true}
      y: {type: number, required: true}
    description: "Click at pixel coordinates. Compositor-level — works through iframes and shadow DOM."
  - name: type_text
    params:
      text: {type: string, required: true}
    description: "Type text at current keyboard focus"
  - name: press_key
    params:
      key: {type: string, required: true}
    description: "Press a keyboard key (Enter, Escape, Tab, etc.)"
  - name: js
    params:
      expression: {type: string, required: true}
    description: "Execute JavaScript in the page. Auto-IIFE-wrapped."
  - name: get_page_text
    params: {}
    description: "Get all visible text content of the page"
  - name: get_element_info
    params:
      selector: {type: string, required: true}
    description: "Get position, size, and visibility of a DOM element"
  - name: fill_input
    params:
      selector: {type: string, required: true}
      value: {type: string, required: true}
    description: "Fill an input field (React/Vue/Ember aware)"
  - name: cdp
    params:
      method: {type: string, required: true}
      params: {type: object, required: false}
    description: "Raw CDP command — escape hatch for anything not in helpers"
  - name: page_info
    params: {}
    description: "Get current page title and URL"
  - name: wait_for_network_idle
    params:
      timeout: {type: number, required: false}
    description: "Wait for network activity to settle"

behavior_rules:
  - "默认使用截图+坐标点击模式: capture_screenshot() → 从图像分析 → click_at_xy(x,y) → capture_screenshot() 验证"
  - "坐标点击默认。抑制 Playwright 习惯反射 '先定位，再点击'"
  - "Core helpers stay short. 缺失功能通过 user_helpers.py 扩展，不修改 helpers.py"
  - "使用 js() 做批量数据提取，不做逐个元素选择器提取"
  - "截图优先交互。对于视觉-语言模型，像素比选择器更可靠"
dont_do:
  - object: web-page
    operations: [navigate]
    unless: "URL 已在任务描述中明确给出"
    message: "导航前确认目标 URL"
---

# Browser Harness

通过 Chrome DevTools Protocol 直接控制浏览器。

## 核心交互模式

1. **截图优先**: `capture_screenshot()` → 从图像分析页面 → 确定操作坐标
2. **坐标点击**: `click_at_xy(x, y)` → `capture_screenshot()` 验证 → 继续
3. **DOM 回退**: 仅在批量数据提取时使用 `js()` 或 `get_element_info()`

## 自愈扩展

如果需要 `helpers.py` 中没有的功能，使用工具编辑器将新函数写入 `user_helpers.py`。
下次执行时自动加载，无需修改核心 helpers.py。
```

### 4.4 `agent/tools/adapters/browser_harness.py` — 适配器（新增，~40 行）

```python
"""Browser Harness adapter. Registers browser tools into the agent tool system."""

from pathlib import Path

import structlog

from agent.tools.loader import parse_tool_md

logger = structlog.get_logger()


class BrowserHarnessAdapter:
    """Adapter that registers browser tools. 类比: filesystem driver registration."""
    
    def __init__(self, registry):
        self.registry = registry
    
    def register(self, tools_dir: Path | None = None) -> int:
        """Register browser tools. 
        
        Scans agent/tools/browser/ for tool.md and registers all capabilities.
        """
        if tools_dir is None:
            tools_dir = Path(__file__).parent.parent / "browser"
        
        tool_md = tools_dir / "tool.md"
        if not tool_md.exists():
            logger.warning("browser_harness_tool_md_not_found", path=str(tool_md))
            return 0
        
        try:
            tool_def = parse_tool_md(tool_md)
            self.registry.register(tool_def)
            logger.info("browser_harness_registered",
                       capabilities=len(tool_def.capabilities))
            return 1
        except Exception as e:
            logger.error("browser_harness_register_failed", error=str(e))
            return 0
```

### 4.5 Phase 4 文件改动汇总

| 文件 | 类型 | 行数 | 说明 |
|------|------|------|------|
| `agent/tools/browser/daemon.py` | **新增** | ~220 | CDP 守护进程（kthread 类比） |
| `agent/tools/browser/helpers.py` | **新增** | ~180 | 浏览器辅助函数（代理可编辑） |
| `agent/tools/browser/tool.md` | **新增** | ~60 | 工具定义（11 个能力） |
| `agent/tools/browser/user_helpers.py` | **新增** | ~15 | 代理扩展空间（空模板） |
| `agent/tools/adapters/browser_harness.py` | **新增** | ~40 | 适配器 |
| `pyproject.toml` | 修改 | +5 | 新增依赖 `websockets` |
| **Phase 4 合计** | | **~520 行** | |

---

## 实施路线图

```
Phase 1 (基础)   九-C: 自愈工具运行时     ~545 行    2-3 天
                 十-A: 验证钩子（协同）    (含在九-C)
                 ─────────────────────
                 产出: 代理可编辑工具 + 自动写 verify 钩子

Phase 2 (智能)   十一-C: 语义压缩         ~410 行    1-2 天
                 十三-B: 双模式调度
                 ─────────────────────
                 产出: 安全上下文管理 + 探索/利用自动切换

Phase 3 (学习)   十二-C: 技能社交网络     ~640 行    2-3 天
                 ─────────────────────
                 产出: 跨会话技能积累 + PII 门控 + 自动退役

Phase 4 (扩展)   十四-B: 浏览器适配器     ~520 行    2-3 天
                 ─────────────────────
                 产出: 原生 CDP 浏览器自动化 + 坐标点击默认
```

### 全部文件改动汇总

| Phase | 新增文件 | 修改文件 | 代码行数 |
|-------|---------|---------|---------|
| Phase 1 | `evolution.py`, `editor.py` | `executor.py`, `registry.py`, `core.py`, `memory.py` | ~545 |
| Phase 2 | `context_compressor.py` | `context.py`, `core.py`, `providers/router.py` | ~410 |
| Phase 3 | `skills/` (5 文件) | `consolidation.py`, `core.py` | ~640 |
| Phase 4 | `browser/` (4 文件), `adapters/browser_harness.py` | `pyproject.toml` | ~520 |
| **总计** | **12 个新文件** | **9 个文件修改** | **~2,115 行** |

---

## 关键设计原则

1. **向后兼容** — 新字段有默认值，旧数据不受影响
2. **渐进增强** — 每个 Phase 独立可测试，不依赖后续 Phase
3. **不破坏现有测试** — 247 个现有测试应全部通过
4. **OS 内核类比一致性** — 新增概念与现有代码风格保持一致
5. **自愈优先** — 九-C 是整个方案的核心引擎，其他优化通过它与系统协同
