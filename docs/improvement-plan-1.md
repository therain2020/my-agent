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

