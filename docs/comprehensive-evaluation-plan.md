# Agent 改进方向：多角度综合评估与路线图

> 基于个人知识库 50+ 条专业知识的全面评估（第二轮：追加安全、一致性、基础设施视角）
> 2026-05-28

---

## 零、当前状态基线

原 `improvement-plan.md` 中的 8 个方向**已全部在代码中落地**：

| # | 方向 | 状态 | 代码位置 |
|---|------|------|---------|
| 1 | DontDoEngine 集成 | 已完成 | `core.py:67,92,142-150` — PLAN/PRE_ACTION/POST_ACTION hook |
| 2 | 角色+结构化观察 | 已完成 | `core.py:742-802` — `_observe_structured()` |
| 3 | 纠正闭环 | 已完成 | `core.py:154-185` — `_check_for_corrections()` + `_apply_correction()` |
| 4 | 结构化验证 | 已完成 | `core.py:850-896` — `_verify_goal()` with state diff |
| 5 | TODO 分析+询问 | 已完成 | `core.py:225-286` — `_analyze_todo()` + 交互询问 |
| 6 | 对象状态记忆 | 已完成 | `memory.py:33-35` — objects_before/after/changes |
| 7 | 非集变动追踪 | 已完成 | `core.py:110-119,140` — `_track_non_set_change()` |
| 8 | 输出格式+渐进披露 | 已完成 | `output_format.py` — OutputFormatManager + CitationRules |

**结论**：当前代码已超出原始改进方案。以下所有新方向均在现有基础上展开。

---

## 零-B、安全架构视角：Trust Boundaries + CIA + STRIDE

> 新增视角，来自 `cia-triad.md`、`trust-boundaries.md`、`security-context-and-tokens.md`

不作为一个独立改进方向，而是**重新框架现有安全机制**，让架构概念更清晰。

### 每条工具调用都是一次信任边界跨越

```
LLM (不可信区域) ──→ Tool Executor (可信区域) ──→ 文件系统/数据库/网络
                    ↑
              DontDoEngine 就是这个边界的守门人
              CredentialGuard 确保凭据不跨越边界反向泄露
              Role 定义边界内允许的操作范围
```

来自 `trust-boundaries.md` 的核心认知：**"信任边界标志着数据或执行改变其信任级别的前沿——每次跨越都需要验证。"** Agent 场景下，LLM 是不可信区域（Ghost——锯齿状、统计性、不可靠），Tool Executor 是可信区域。每次工具调用都是一次边界跨越，DontDoEngine 的三层 hook（PLAN、PRE_ACTION、POST_ACTION）正好对应边界跨越的三个检查点。

### CIA 三元组在 Agent 中的映射

| CIA 维度 | Agent 机制 | 现有实现 |
|----------|-----------|---------|
| **Confidentiality** | API key 不对 LLM 可见 | `security/credentials.py` — CredentialGuard 在调用时注入 |
| **Integrity** | 禁止未授权的文件/数据库修改 | `dont_do.py` — DontDoEngine + dont-do/*.yaml 规则 |
| **Availability** | Provider 故障时自动切换 | `providers/pool.py` — RAID 1 故障转移池 |

来自 `cia-triad.md` 的核心认知：**安全目标就是非功能需求**——和可扩展性、可维护性是同一层级。安全也参与 trade-off：更严格的安全规则可能降低 Agent 的灵活性。

### STRIDE 威胁建模应用于工具接口

来自 `trust-boundaries.md` 的 STRIDE 框架可直接应用于每个 tool.md 定义的工具：

| 威胁 | Agent 场景 | 缓解 |
|------|-----------|------|
| **S**poofing | LLM 伪装调用未被授权的工具 | Role + DontDoEngine 双重验证 |
| **T**ampering | LLM 修改工具参数（如路径遍历） | DontDoEngine PRE_ACTION 参数检查 |
| **R**epudiation | 无法追溯某次操作是谁发起的 | Event Sourcing（方向 A）提供完整审计 |
| **I**nfo Disclosure | 工具结果中包含敏感信息 | POST_ACTION 结果过滤 + 输出脱敏 |
| **D**enial of Service | LLM 恶意循环调用工具 | max_iterations 限制 + InterruptHandler |
| **E**levation | LLM 试图执行超出 role 权限的操作 | Role.get_manipulation_tools() 白名单 |

**关键洞察**：当前安全机制（DontDoEngine、CredentialGuard、Role、InterruptHandler）已经覆盖了 STRIDE 的 6 个维度，但缺乏统一的安全架构语言。通过 Trust Boundaries + CIA + STRIDE 框架重新表述后，每个安全决策都有了明确的"为什么"——不只是一堆规则，而是一个**安全架构**。

---

## 一、评估框架

每个改进方向从 7 个维度打分（1-5），加权计算综合优先级。

| 维度 | 权重 | 说明 |
|------|------|------|
| 原始 IDEA 对齐 | 25% | 与用户原始设计理念的匹配度 |
| 知识库支撑 | 20% | 被知识库中多少条专业知识支撑 |
| 架构契合度 | 15% | 与 OS 内核类比架构的一致性 |
| 技术可行性 | 15% | 实现难度、依赖复杂度、测试可行性 |
| 影响力 | 15% | 对 agent 质量和用户体验的提升幅度 |
| 风险 | 5% | 引入的复杂度和回归风险（反向计分：低风险=5） |
| 独立性 | 5% | 是否可独立交付，不依赖其他方向 |

---

## 二、逐方向深度评估

### 方向 A：Event Sourcing 记忆系统

**核心思想**：将记忆从"存快照对"改为"存不可变事件流"。每次 Observe/ToolCall/Correct/Verify 是一个 Event，追加到 append-only log。当前状态通过重放 Event 计算。

**知识库来源**：
- `event-sourcing.md` — "不存状态，存变更"
- `event-immutability.md` — "不可变 Event 支持并行处理和回溯"
- `event-vs-command.md` — Event（事实）与 Command（指令）的意图区分

**OS 内核类比**：journald 二进制日志 / ext4 journal — 所有操作先写 journal，再应用到状态

**具体方案**：

```
当前: Episode { objects_before: {...}, objects_after: {...} }
ES:    EventLog [
         GoalStarted(goal="...", time=T0),
         ObjectObserved(uri="file://a.py", type="file", props={size:100}, time=T1),
         PlanGenerated(steps=[...], time=T2),
         ToolCalled(tool="file-system", capability="write_file", params={...}, time=T3),
         ToolResult(tool="file-system", result={...}, time=T4),
         ObjectObserved(uri="file://a.py", type="file", props={size:200}, time=T5),
         CorrectionApplied(corr_id="...", rule_id="...", time=T6),
         GoalVerified(achieved=true, confidence=0.9, time=T7),
         GoalCompleted(time=T8),
       ]
```

**优势**：
- **完整审计**：每一步都可追溯——谁在什么时候做了什么
- **Temporal Query**：回到第 3 步时对象状态是什么？重放前 3 个 Event 即知
- **Replay 调试**：重放 event log 可完整重现执行过程（不需要重新调 LLM）
- **多 Consumer**：同一 event log，Memory 存它、Consolidation 读它、Fitness Function 分析它

**一致性模型选择**（来自 `strict-vs-eventual-consistency.md`）：

Event Sourcing 引入了一个关键设计决策——不同 Consumer 读取 Event Log 的时间不同，数据存在 replication lag。Christian 的两个问题直接适用：

1. **业务是否需要立即看到最新数据？**
   - Dont-do 规则变更：**需要严格一致性**——用户在纠正中新增的规则，必须在下一次 PRE_ACTION 检查前生效，否则安全窗口出现
   - Episode 记录：**最终一致性可接受**——Memory、Consolidation、Fitness Functions 可以在微秒到毫秒级延迟内消费

2. **读多还是写多？**
   - 写：每个 tool call 产生 1-2 个 Event
   - 读：Fitness Functions（每次 CI 跑）、能力画像查询（每次路由决策）、自我教学（每次 Consolidation 触发）
   - 读远多于写 → 适合用 Event Log + 多 Consumer 独立构建读模型

**设计决策**：区分两类事件的传播策略——
- **安全关键事件**（RuleAdded、RuleModified）：同步写入 + 立即通知所有 Consumer
- **观测事件**（ObjectObserved、ToolCalled、GoalVerified）：异步写入 + 最终一致性传播

**代价**（来自 `eda-tradeoffs.md`）：
- 存储增长：Event Log 随时间线性增长（Snapshot 每 N 个 event 存一次状态快照可缓解）
- 查询复杂：当前状态需要"计算"而非直接"读取"
- 追踪复杂度：事件驱动的系统调试比直接调用难（需要额外可观测性）

| 维度 | 评分 | 说明 |
|------|------|------|
| IDEA 对齐 | 5 | 原始 IDEA 明确要求"记忆:时间，任务类型，对象状态变化，工具使用，非集变动" |
| 知识库支撑 | 5 | event-sourcing + event-immutability + event-vs-command + cqrs 四条直接支撑 |
| 架构契合 | 5 | ext4 journal 类比最完美的延伸 — journal 先行，状态后算 |
| 技术可行性 | 3 | SQLite 可以存储 event log，但查询模式需要重新设计；现有 Episode schema 需大改 |
| 影响力 | 5 | 改变记忆系统的数据范式，是所有高级查询（能力画像、模式挖掘）的基础 |
| 风险 | 3 | schema 大改动，现有 170 个测试有部分依赖 episode 结构 |
| 独立性 | 3 | 被 B（CQRS）和 D（能力画像）依赖 |

**综合评分**：4.4 / 5.0

---

### 方向 B：CQRS 读写分离

**核心思想**：Event Log（Write Model）与查询视图（Read Model）分离。写侧只追加 Event，读侧维护专门优化的查询结构。

**知识库来源**：
- `cqrs-pattern.md` — "写模型和读模型不同时，分离它们"
- 特别警告："CQRS 应该是最后的选项——如果 CRUD 能满足需求，用 CRUD"

**OS 内核类比**：VFS page cache（读缓存）与磁盘写入队列（写队列）分离

**具体方案**：

```
Write Side:                    Read Side:
  Agent Action → Event Log      成本分析视图（per model cost）
                  ↓             对象历史视图（per object timeline）
               Event Bus        非集有效性视图（rule hit rate）
                  ↓             能力画像视图（model x task success rate）
              Projectors        审计视图（full timeline）
```

**当前现状**：`memory.py` 已有一个 `MemoryStore`，写（`log_episode`）和读（`get_recent`, `get_object_history`, `stats`, `get_non_set_history`）共用同一张 `episodic` 表。读查询依赖 JSON 字段的 LIKE 匹配（如 `get_object_history` 做 `WHERE objects_before LIKE '%{uri}%'`），效率低。

**YAGNI 判断**：当前 episode 量级（单用户、单会话、几十到几百条）下，CRUD 完全够用。CQRS 的真正价值在 episode 量级达到万级以上或需要实时聚合查询时才体现。**建议暂不独立实施，而是作为 A（Event Sourcing）的自然延伸。**

| 维度 | 评分 | 说明 |
|------|------|------|
| IDEA 对齐 | 3 | 间接相关——原始 IDEA 没明确提读写分离 |
| 知识库支撑 | 4 | 直接来自 cqrs-pattern.md，但文档也警告"应该是最后选项" |
| 架构契合 | 4 | 与 VFS 读写分离类比一致 |
| 技术可行性 | 4 | 技术上简单（建视图/物化视图），但需要等 Event Log 先到位 |
| 影响力 | 3 | 当前数据量下收益有限；万级 episode 后收益显著 |
| 风险 | 4 | 低风险——在现有 SQLite 上加视图即可 |
| 独立性 | 1 | 强依赖 A（Event Sourcing）先落地 |

**综合评分**：3.2 / 5.0 — **标记为 A 的附属品，不独立排期**

---

### 方向 C：Agent Fitness Functions（架构适应度函数）

**核心思想**：为 Agent 本身的架构特性写自动化测试——不只是"代码是否编译通过"，而是"Agent 是否按架构设计运行"。

**知识库来源**：
- `architectural-fitness-function.md` — "对架构特性提供客观完整性评估的自动化测试"
- `fitness-function-core-principles.md` — 四条核心原则
- `fitness-functions-vs-unit-tests.md` — "FF 是讨论的起点，不是硬性门禁"
- `fast-feedback-in-architecture.md` — "FFDA 的目标是快速反馈，不是全面覆盖"

**OS 内核类比**：kernel kselftest / LTP（Linux Test Project）— agent 的回归测试套件

**四条 FFDA 原则的 Agent 映射**：

| 原则 | Agent 场景 |
|------|-----------|
| 1. 不滥发低价值 FF | 只测关键架构特性——非集有效性、plan 质量、角色合规 |
| 2. 用 FF 缓解负面权衡 | 选择 ReAct 灵活性 → 损失可预测性 → FF 监控 plan 偏离度 |
| 3. 架构即可执行代码 | "非集规则覆盖所有文件写入"不是文档声明，是每次构建自动验证的 |
| 4. 最小最快反馈环 | 从"每次 plan 是否包含 verify 条件"这个简单 FF 开始 |

**具体 FF 清单**（精选 5 个高价值目标）：

```python
# FF-1: Plan 完整性
# 每次 plan 中的步骤是否都有 verify 条件？
def test_plan_has_verify_for_each_step():
    plan = agent._plan_goal(goal, observation, conversation)
    for step in plan:
        assert "verify" in step, f"Step missing verify: {step['action'][:100]}"

# FF-2: 非集规则有效性
# dont-do 规则是否在模拟攻击场景中阻止了危险操作？
def test_dont_do_blocks_dangerous_write():
    verdict, _ = agent.dont_do.check(HookPoint.PRE_ACTION, {
        "object": "file", "operation": "write_file",
        "tool": "file-system", "params": {"path": "/etc/passwd"}
    })
    assert verdict == Verdict.REJECT

# FF-3: 角色合规
# Agent 是否使用了 role 未授权的工具？
def test_agent_stays_within_role():
    role_tools = set(agent.role.get_manipulation_tools("file"))
    for step in plan:
        if step.get("tool"):
            assert step["tool"] in role_tools

# FF-4: 上下文效率
# Prompt 中是否有超过阈值比例的冗余 token？
def test_prompt_efficiency():
    prompt = agent.prompt_assembler.assemble(...)
    tool_section = extract_section(prompt, "可用工具")
    assert len(tool_section) / len(prompt) < 0.3  # 工具描述不超过 30%

# FF-5: 输出格式合规
# LLM 响应中文件引用是否使用 path:line 格式？
def test_output_has_proper_citations():
    response = agent._get_provider().complete(...)
    result = agent.output_format.validate(response.content)
    assert result["error_count"] == 0
```

**关键设计决策**（来自 FF 原则）：FF 失败 ≠ 构建失败。FF 失败 = 触发一次讨论/记录。"这不是用棍子打人，是让 trade-off 可见。"

| 维度 | 评分 | 说明 |
|------|------|------|
| IDEA 对齐 | 4 | 原始 IDEA 要求"行动完成后 agent 自行观察对象终态并和验收标准比对"——FF 是这种验证的自动化 |
| 知识库支撑 | 5 | 4 条 fitness function 知识 + testing-pyramid + fast-feedback 全部支撑 |
| 架构契合 | 4 | kselftest/LTP 类比自然，但 FF 是 meta-layer（测试 agent 本身） |
| 技术可行性 | 5 | Python 测试框架（pytest）已有 170 个测试，加 FF 无技术障碍 |
| 影响力 | 4 | 将架构保障从"人脑检查"变为"自动化验证"，长期价值极高 |
| 风险 | 5 | 极低——只加测试不改核心逻辑 |
| 独立性 | 5 | 完全独立，不依赖任何其他方向 |

**综合评分**：4.6 / 5.0 — **最高优先级，无依赖，风险最低**

---

### 方向 D：语义记忆检索（Vector Embedding 替代 FTS5）

**核心思想**：将记忆检索从关键词匹配（FTS5）升级为语义相似度搜索（Vector Embedding），使 Agent 能找到"意思相似但词汇不同"的历史经验。

**知识库来源**：
- `vector-index.md` — "语义相似度搜索，而非精确关键词匹配"
- `rag-retrieval.md` — "RAG 让 LLM 基于外部数据做接地气的回答"
- `index-structures.md` — "不同类型的索引适合不同的查询模式"
- `llama-index.md` — "Data Connectors → Indices → Query Engines → Retrieval"

**OS 内核类比**：内容寻址存储（content-addressable storage）— 按"含义"而非"地址"查找

**当前现状**：`memory.py` 用 FTS5 做全文搜索（`search_semantic`），fallback 到 LIKE。问题是：
- FTS5 是关键词匹配——搜"数据库迁移"找不到"DB migration"
- 中文分词天然劣势——FTS5 没有中文分词器

**方案**：

```python
class SemanticRetriever:
    """Vector-based memory retrieval."""
    
    def __init__(self, embedding_model: str = "text-embedding-3-small"):
        self.embedding_model = embedding_model
        # 使用 sqlite-vec 扩展（纯 SQLite，零外部依赖）
        # 或简单的 numpy + sqlite BLOB 存储
    
    def index_episode(self, entry: EpisodeEntry) -> None:
        """生成 embedding 并存储到 vec_episodes 表."""
        text = f"{entry.task_type}: {entry.task_summary}"
        vec = self._embed(text)
        # 存储到 SQLite BLOB
    
    def search_similar(self, query: str, limit: int = 5) -> list[EpisodeEntry]:
        """语义搜索：找到与当前任务最相似的历史 episode."""
        query_vec = self._embed(query)
        return self._cosine_similarity_search(query_vec, limit)
    
    def search_similar_errors(self, error: str) -> list[EpisodeEntry]:
        """找到历史上类似的错误及当时的解决方案."""
        ...
```

**YAGNI 判断**：当前 episode 量级（几十到几百条）下，FTS5 LIKE 搜索足够。语义搜索的价值在 episode 积累到千级以上时才体现。**建议 Phase 4 实施，不作为优先级。**

| 维度 | 评分 | 说明 |
|------|------|------|
| IDEA 对齐 | 3 | 原始 IDEA 要求记忆但未指定检索方式 |
| 知识库支撑 | 5 | 4 条 RAG/vector 知识直接支撑 |
| 架构契合 | 3 | 内容寻址存储类比略牵强 |
| 技术可行性 | 3 | sqlite-vec 或 numpy 方案可行，但需要 embedding API 调用（增加延迟和成本） |
| 影响力 | 3 | 当前数据量下收益有限；规模化后价值高 |
| 风险 | 4 | 低风险——在现有 search_semantic 旁加新方法，不破坏旧逻辑 |
| 独立性 | 5 | 完全独立 |

**综合评分**：3.6 / 5.0 — **延后到 Phase 4**

---

### 方向 E：Agent 自我教学（跨 Episode 模式挖掘）

**核心思想**：Agent 不只是被动接受纠正（correction → rule），而是主动从历史 episode 中发现模式，提出"我注意到你反复纠正同一个问题，要不要我把它变成规则？"

**知识库来源**：
- `skills-as-continuous-learning.md` — Anthropic Skills 的三层学习模型
- `outsource-thinking-not-understanding.md` — "Taste 是人类独有的判断力"——自我教学是辅助，最终决策权在人

**OS 内核类比**：KSM（Kernel Same-page Merging）— 发现并合并重复模式

**具体方案**：

```
Consolidation 流程增强:

当前: Episode → LLM 叙事压缩 → SemanticEntry
增强: Episode 1..N → 跨 episode 模式挖掘:
      
      1. 错误聚类: "最近 10 次 database 类型的任务，有 7 次出现 'connection timeout'"
         → 建议: 添加自动重连 dont-do 规则
      
      2. 纠正聚类: "最近 20 次纠正，有 12 次关于 '文件路径拼写错误'"
         → 建议: 创建 path-validation skill
      
      3. 回滚聚类: "最近 5 次 goal 验证失败，有 4 次因为 '数据库迁移后未运行测试'"
         → 建议: 在数据库迁移 plan 中自动加入 test step
```

**关键约束**（来自 Karpathy 的 Taste 概念）：Agent 可以**提议**，不能**自动执行**。因为"什么值得学"是 Taste 判断——属于"不能外包的理解"。

```python
class PatternMiner:
    """Cross-episode pattern discovery."""
    
    def mine(self, episodes: list[EpisodeEntry]) -> list[PatternProposal]:
        proposals = []
        
        # 聚类分析
        error_clusters = self._cluster_by_error(episodes)
        correction_clusters = self._cluster_by_correction(episodes)
        failure_clusters = self._cluster_by_failure(episodes)
        
        for cluster in error_clusters:
            if cluster.frequency >= 3 and cluster.confidence > 0.7:
                proposals.append(PatternProposal(
                    type="error_pattern",
                    description=f"最近 {cluster.count} 次 {cluster.task_type} 任务"
                                f"中有 {cluster.hit_count} 次出现 '{cluster.error}'",
                    suggestion=cluster.generate_rule_suggestion(),
                    confidence=cluster.confidence,
                ))
        
        return proposals
```

| 维度 | 评分 | 说明 |
|------|------|------|
| IDEA 对齐 | 5 | 原始 IDEA："用户如发现计划存在问题，指出问题后，将问题添加到非集中"→ 自我教学是这个流程的自动化 |
| 知识库支撑 | 5 | skills-as-continuous-learning 三层模型直接映射 |
| 架构契合 | 4 | KSM 类比：发现并去重模式 |
| 技术可行性 | 3 | 需要 episode 积累到一定量级才有统计意义；聚类算法选择和调参有不确定性 |
| 影响力 | 5 | 从"被动学习"到"主动学习"的范式跃迁 |
| 风险 | 3 | 误判模式（假阳性）可能导致垃圾规则 |
| 独立性 | 2 | 依赖 A（Event Sourcing）提供结构化事件用于聚类；需要积累足够 episode |

**综合评分**：4.0 / 5.0 — **高价值但依赖 A，Phase 3**

---

### 方向 F：Jagged Frontier 能力画像与自适应路由

**核心思想**：持续记录每种 task_type + model 组合的 success rate，建立模型能力画像，实现"能力路由"而非纯"成本路由"。

**知识库来源**：
- `llm-as-ghost-jagged-statistical.md` — "LLM 的能力不是均匀的圆形，而是锯齿状的"
- Karpathy 的三特征：Jagged Frontier、Statistical、Summoned

**OS 内核类比**：NUMA scheduling / CPU affinity — 不同任务分配到最适合的"核"

**当前现状**：`providers/router.py` 已有成本路由（haiku → sonnet → opus 渐进升级），但路由策略只看成本不看能力。缺少的是闭环反馈——路由决策基于 episode 结果动态调整。

**方案**：

```python
class CapabilityProfile:
    """Per-model, per-task-type capability tracking."""
    
    def update(self, task_type: str, model: str, 
               tools: list[str], success: bool, steps: int) -> None:
        """更新能力画像."""
        key = f"{model}:{task_type}"
        profile = self._profiles.get(key) or self._init_profile()
        profile.total += 1
        if success:
            profile.successes += 1
        profile.avg_steps = (profile.avg_steps * (profile.total - 1) + steps) / profile.total
        self._profiles[key] = profile
    
    def recommend_model(self, task_type: str, tools: list[str]) -> str:
        """基于能力画像推荐模型."""
        # 查找历史成功率
        candidates = []
        for key, profile in self._profiles.items():
            model, ttype = key.split(":", 1)
            if ttype == task_type and profile.total >= 5:  # 至少5次才有统计意义
                candidates.append((model, profile.success_rate))
        
        if not candidates:
            return self._default_model  # 无数据 → 用最便宜的
        
        # 成功率 > 85% → 用最便宜的满足条件的
        good_enough = [(m, r) for m, r in candidates if r > 0.85]
        if good_enough:
            return min(good_enough, key=lambda x: self._model_cost[x[0]])[0]
        
        # 都不满足 → 用最强的
        return self._most_capable_model
```

**与成本路由的关系**：成本路由是"先试便宜的，不行再升级"；能力路由是"根据历史数据，直接选最可能成功的模型"。两者互补：
- 新任务类型（无历史数据）→ 成本路由（先试便宜的）
- 已知任务类型（有足够历史数据）→ 能力路由（精准选择）

| 维度 | 评分 | 说明 |
|------|------|------|
| IDEA 对齐 | 3 | 原始 IDEA 未提及模型选择策略 |
| 知识库支撑 | 5 | Jagged Frontier 是 Karpathy 对 LLM 本质的认知模型，直接指导设计 |
| 架构契合 | 5 | NUMA scheduling / CPU affinity 类比精准 |
| 技术可行性 | 4 | 在现有 Episode 数据上做聚合查询即可；不需要新基础设施 |
| 影响力 | 4 | 直接省钱 + 提升成功率——双重收益 |
| 风险 | 4 | 低——叠加在现有路由之上，不破坏旧逻辑 |
| 独立性 | 3 | 需要 episod 数据积累（至少每种 task_type 5+ 条才有统计意义） |

**综合评分**：4.0 / 5.0 — **中等依赖，高性价比**

---

### 方向 G：Ontology 式对象模型（Data + Logic + Actions + Relations）

**核心思想**：将 `AgentObject` 从"状态快照"扩展为"状态 + 约束 + 可用操作 + 关系图"，让 LLM 看到的不只是"对象 X 的状态是 Y"，而是"对象 X 有什么约束、我能对它做什么、它和谁相关"。

**知识库来源**：
- `ontology-data-logic-actions.md` — "Data alone is inert. Data + Logic gives analysis. Data + Logic + Actions closes the loop."
- `ontology-digital-twin.md` — "Models how the business actually operates, not how source systems structure data"
- `llm-ontology-context.md` — "Ontology tells the LLM: here is how this business works and what you can do about it"
- `code-as-universal-interface.md` — "代码不只是 Agent 的一个用例，而是 Agent 与整个数字世界交互的通用接口"

**OS 内核类比**：VFS inode 扩展属性（xattrs）+ ACLs + 文件系统关系（hard link, symlink）

**当前 `AgentObject`**：
```python
AgentObject(
    uri="file://src/auth.py",
    type="file",
    display_name="src/auth.py",
    state_before=ObjectState(properties={"exists": True, "size": 1024}),
    state_after=None,
    observation_tools=["read_file"],
    manipulation_tools=["write_file"],
)
```

**方案（扩展后）**：
```python
@dataclass
class AgentObject:
    # === 现有字段 ===
    uri: str
    type: str
    display_name: str
    state_before: ObjectState | None
    state_after: ObjectState | None
    observation_tools: list[str]
    manipulation_tools: list[str]
    
    # === 新增: Logic ===
    constraints: list[ObjectConstraint]    # 对象级别的约束
    # ObjectConstraint("不能包含硬编码密钥", severity="blocker",
    #                   check="no pattern like 'sk-[a-zA-Z0-9]{32}'")
    
    # === 新增: Relations ===
    relations: dict[str, list[str]]        # 对象关系图
    # {"tested_by": ["file://tests/test_auth.py"],
    #  "imports": ["file://src/config.py"],
    #  "depends_on": ["package://flask"]}
    
    # === 新增: Actions ===
    available_actions: list[ObjectAction]  # 此对象可用的操作（带约束）
    # ObjectAction(name="write_file", preconditions=["file exists", "not system path"],
    #              side_effects=["modifies file content", "may break tests"])

@dataclass
class ObjectConstraint:
    """对象级别的约束条件."""
    description: str
    severity: str          # "blocker" | "warning" | "info"
    check: str = ""        # 可选的自动化检查表达式
    source: str = ""       # 约束来源: "dont_do" | "role" | "correction"
```

**关键洞察**（来自 Ontology）：这个扩展不只是增加字段——它改变了 LLM 看到对象时的**认知上下文**。对比：

```
当前 LLM 看到的:      扩展后 LLM 看到的:
"文件 src/auth.py       "文件 src/auth.py 
 当前状态: {size:1024}"   当前状态: {size:1024}
                          约束: 不能含硬编码密钥(blocker), 
                                修改前需先读文件(warning)
                          关系: 被 tests/test_auth.py 测试,
                                导入了 src/config.py
                          可用操作: read_file, write_file(前置:文件存在,
                                    非系统路径), run_linter"
```

当前 LLM 基于"状态"做 plan。扩展后 LLM 基于"状态+约束+关系+可用操作"做 plan——每个 plan step 天然考虑了约束和影响范围。

| 维度 | 评分 | 说明 |
|------|------|------|
| IDEA 对齐 | 5 | 原始 IDEA："模型需要观察 goal 所涉及的对象的当前状态，并思考自己有哪些 tools 能够用来操作这些对象"——Ontology 是这条的极致实现 |
| 知识库支撑 | 5 | 4 条 Ontology 知识 + code-as-universal-interface 全部直接映射 |
| 架构契合 | 5 | VFS inode xattrs + ACLs + dentry 关系图 —— 最自然的 OS 类比延伸 |
| 技术可行性 | 4 | 纯数据模型扩展 + tool.md 格式增强，无需新基础设施 |
| 影响力 | 5 | 直接提升 plan 质量——LLM 在规划时已知道约束、关系和影响范围 |
| 风险 | 4 | 向后兼容——所有新字段有默认空值 |
| 独立性 | 4 | 可独立实施；与 A（Event Sourcing）互补但非依赖 |

**综合评分**：4.7 / 5.0 — **最高价值方向之一**

---

### 方向 H：Saga Pattern 长任务补偿机制

**核心思想**：当 Agent 执行多步骤任务时，如果第 3 步失败，前 2 步的副作用需要补偿（回滚）。Saga 模式提供结构化的补偿流程。

**知识库来源**：
- `saga-pattern.md` — "通过补偿动作实现跨步骤的原子性"
- `orchestration-vs-choreography.md` — 两种实现方式的选择标准
- `eda-tradeoffs.md` — "简单系统用直接调用"

**OS 内核类比**：文件系统事务（txn）+ fsck 恢复

**当前现状**：Agent loop 有 max_iterations=3 的重试机制，但**没有补偿逻辑**。如果 step 1 创建了文件 A，step 2 修改了文件 B，step 3 失败了——A 和 B 的修改不会回滚。

**YAGNI 判断**（来自 `cqrs-pattern.md` 的警告 + `eda-tradeoffs.md` 的"简单系统用直接调用"）：Saga 是为微服务分布式事务设计的复杂模式。对于单 Agent 的线性任务执行，Saga 的复杂性远超收益。更实用的方案是：

```python
# 简单补偿：记录每个 step 的逆操作
class StepWithCompensation:
    action: str
    compensation: str  # "delete file://tmp/build.py" 或 None

# 如果后续 step 失败，逆序执行 compensation
# 这是 Saga 的核心思想但不需要完整的 Saga 框架
```

**结论：不作为独立方向。将"补偿记录"作为 A（Event Sourcing）中 Event 的一个可选字段。**

| 维度 | 评分 | 说明 |
|------|------|------|
| IDEA 对齐 | 2 | 原始 IDEA 未提及补偿/回滚 |
| 知识库支撑 | 3 | 直接来自 saga-pattern，但该模式设计场景（微服务分布式事务）与当前项目（单 Agent 线性执行）不匹配 |
| 架构契合 | 2 | fsck 类比勉强 |
| 技术可行性 | 2 | 复杂——需要定义每个 tool 的逆操作、处理补偿失败、嵌套补偿 |
| 影响力 | 2 | 当前单 Agent 场景下收益有限 |
| 风险 | 2 | 补偿逻辑本身可能出错，引入新 bug |
| 独立性 | 3 | 可独立实施 |

**综合评分**：2.3 / 5.0 — **不纳入路线图，补偿记录作为 A 的附属字段**

---

### 方向 I：EDA 式内部解耦

**核心思想**：将 Agent 的单体架构（一个 Agent 类调度一切）解耦为通过 Event Bus 通信的独立组件。

**知识库来源**：
- `eda-decoupling-dependency-inversion.md` — "契约变成了 Event——只要尊重 Event schema，整个系统就能工作"
- `eda-producer-broker-consumer.md` — Producer → Broker → Consumer 三组件模型
- `eda-tradeoffs.md` — "简单系统用直接调用"、"性能开销"、"追踪复杂度"

**具体方案**：

```
当前（单体）:                    解耦后（EDA）:
  Agent.run()                     Agent.run()
    ├─ DontDoEngine.check()         ├─ emit(GoalStarted)
    ├─ ToolExecutor.execute()       ├─ emit(ToolCallRequested)
    ├─ Memory.log_episode()         ├─ AgentEventBus
    └─ Consolidation.on_task_end()  │   ├─ DontDoEngine 订阅 ToolCallRequested
                                    │   ├─ Memory 订阅 ToolExecuted
                                    │   ├─ Consolidation 订阅 TaskCompleted
                                    │   └─ OutputFormat 订阅 LLMResponse
```

**YAGNI 判断**：EDA 三个代价全部命中当前场景：
1. **性能开销**：Agent 主循环引入 Broker 中转，增加延迟
2. **最终一致性**：Memory 可能晚于 ToolExecutor 感知到事件——对于单体 agent 来说这是不必要引入的复杂度
3. **追踪复杂度**：当前 `conversation` 字符串就是完整的执行追踪——EDA 后需要额外的分布式追踪基础设施

基督教（Christian）讲 EDA 的标准："简单系统用直接调用。"当前 Agent 是单进程单体，直接调用是最优选择。

| 维度 | 评分 | 说明 |
|------|------|------|
| IDEA 对齐 | 2 | 原始 IDEA 未要求内部解耦 |
| 知识库支撑 | 4 | 5 条 EDA 知识支撑，但每次讨论都强调"简单系统不需要" |
| 架构契合 | 3 | netlink/udev 类比有道理，但过度设计 |
| 技术可行性 | 2 | 需要引入事件总线、异步消息传递、schema 定义——对当前单进程架构过重 |
| 影响力 | 1 | **负面影响**——引入不必要的复杂度 |
| 风险 | 1 | 高风险——将简单直接的调用链变成异步事件流 |
| 独立性 | 4 | 技术上可独立实施 |

**综合评分**：2.3 / 5.0 — **不纳入。EDA 是解决分布式系统问题的方案，当前 Agent 是单进程单体。**

---

### 方向 J：架构约束一等公民

**核心思想**：将"约束条件"（法律合规、成本限制、技术标准、安全策略）从隐式规则提升为显式的、一等公民的架构概念。

**知识库来源**：
- `architectural-constraints.md` — "约束通常是不可协商的——你不能选择'不遵守 GDPR'"
- `requirement-prioritization-and-tradeoffs.md` — "约束决定方案空间的边界"
- `yagni-principle.md` — "区分'现在需要的'和'现在不确定的'"

**方案**：在 `AgentObject.constraints` 中已经覆盖了对象级别的约束（见方向 G）。系统级别的约束（如 "所有 API key 必须通过 CredentialGuard 注入，禁止 LLM 可见"）已由 `security/credentials.py` 实现。

**结论：约束概念已通过 G（Ontology 对象模型）和现有 security 模块充分覆盖。不作为独立方向。**

| 维度 | 评分 | 说明 |
|------|------|------|
| 综合评分 | — | 已通过方向 G 覆盖，不独立评估 |

---

### 方向 K：基础设施工程质量（Schema 迁移 + 类型化配置 + 集中异常处理）

**核心思想**：三个低风险、高纪律性的基础设施改进，来自知识库中后端工程最佳实践。

**知识库来源**：
- `database-migration-alembic.md` — "迁移文件进入 Git，CI/CD 自动执行——数据库结构始终与代码版本对应"
- `settings-hierarchy.md` — "所有配置项有类型注解和默认值；IDE 自动补全；.env.example 作为文档"
- `application-factory-pattern.md` — "用函数创建应用实例，而不是在模块顶层直接实例化"
- `layered-exception-handling.md` — "抛出层 → 捕获层 → 脱敏层；不需要在路由函数里 try-except"

#### K1: 版本化 Schema 迁移

**当前问题**：`memory.py:_migrate_schema()` 用 try/except 做 ad-hoc 迁移——
```python
for sql in migrations:
    try:
        self.conn.execute(sql)
    except sqlite3.OperationalError:
        pass  # 列已存在
```
问题：无版本记录（不知道当前 schema 版本）、无回退机制、无法处理复杂迁移（如列重命名、数据迁移）。

**方案**：引入轻量版本化迁移——

```python
# agent/memory_migrations.py
MIGRATIONS = [
    ("001_initial", """
        CREATE TABLE IF NOT EXISTS episodic (...);
        CREATE TABLE IF NOT EXISTS semantic (...);
    """),
    ("002_add_object_state", """
        ALTER TABLE episodic ADD COLUMN objects_before TEXT DEFAULT '{}';
        ALTER TABLE episodic ADD COLUMN objects_after TEXT DEFAULT '{}';
    """),
    ("003_add_event_log", """  -- Phase 2 新增
        CREATE TABLE IF NOT EXISTS event_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            task_id TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE INDEX idx_event_task ON event_log(task_id);
        CREATE INDEX idx_event_type ON event_log(event_type);
    """),
]

class MigrationManager:
    def __init__(self, conn):
        self.conn = conn
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version ("
            "  version TEXT PRIMARY KEY, applied_at TEXT NOT NULL"
            ")"
        )
    
    def migrate(self):
        current = self._current_version()
        for version, sql in MIGRATIONS:
            if version > current:
                self.conn.executescript(sql)
                self.conn.execute(
                    "INSERT INTO schema_version VALUES (?, ?)",
                    (version, datetime.now(UTC).isoformat())
                )
                logger.info("migration_applied", version=version)
```

#### K2: 类型化配置层次

**当前问题**：`config.py` 加载 YAML → dict，无类型检查、无 IDE 补全、无环境覆盖。

**方案**：引入 dataclass 配置层次（无需引入 pydantic，保持零外部依赖原则）——

```python
@dataclass
class AgentConfig:
    max_loop_iterations: int = 3
    session_timeout_seconds: int = 300

@dataclass
class AppConfig:
    agent: AgentConfig = field(default_factory=AgentConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    
    @classmethod
    def from_yaml(cls, path: Path) -> "AppConfig":
        """Load YAML → typed dataclass, with env var overrides."""
        ...
    
    @classmethod
    def dev(cls) -> "AppConfig":
        """Development defaults (verbose logging, short timeouts)."""
        ...
    
    @classmethod
    def test(cls) -> "AppConfig":
        """Test defaults (in-memory DB, mock providers)."""
        ...
```

**收益**：IDE 跳转和补全、拼写错误在 import 时暴露、`AppConfig.test()` 让测试更简洁。

#### K3: Agent 工厂模式

**当前现状**：`Agent.__init__(config_path)` 已接近工厂模式。进一步形式化：

```python
def create_agent(
    config: AppConfig | None = None,
    provider: LLMProvider | None = None,
    memory_path: str | None = None,
) -> Agent:
    """Agent factory — 测试注入点."""
    agent = Agent(config=config or AppConfig.dev())
    if provider:
        agent.set_provider(provider, ProviderConfig(...))
    if memory_path:
        agent.memory = EpisodicMemory(memory_path)  # 测试用 :memory:
    agent.setup()
    return agent
```

#### K4: 集中异常处理

**当前问题**：`core.py` 中散落 try/except——
```python
# run() 中有 3 处 try/except
# goal_run() 中有 4 处 try/except
# _observe_structured() 中有 1 处
```

**方案**：三层异常处理链——

```python
# 第一层：异常体系（已有 agent/errors.py）
class AgentError(Exception): ...
class ProviderError(AgentError): ...
class ToolExecutionError(AgentError): ...
class DontDoRejectionError(AgentError): ...

# 第二层：集中处理器
def handle_agent_error(error: AgentError, context: dict) -> str:
    """将异常转换为 LLM 可理解的上下文消息."""
    if isinstance(error, DontDoRejectionError):
        return f"[Blocked] {error.rule_id}: {error.message}"
    if isinstance(error, ToolExecutionError):
        return f"[Tool Error] {error.tool_name}: {error.detail}"
    if isinstance(error, ProviderError):
        return f"[Provider Error] {error.provider}: {error.detail}"
    return f"[Error] {error}"

# 第三层：生产脱敏
# 在发送给 LLM 之前，移除堆栈跟踪、内部路径等敏感信息
```

### 综合评估

| 子项 | 改动量 | 风险 | 价值 |
|------|--------|------|------|
| K1: 版本化迁移 | ~60 行 | 极低 | 中——为 Phase 2 Event Sourcing 的 schema 变更打基础 |
| K2: 类型化配置 | ~120 行 | 低 | 高——改善开发体验，减少运行时配置错误 |
| K3: Agent 工厂 | ~40 行 | 极低 | 中——形式化已有的模式 |
| K4: 集中异常处理 | ~80 行 | 低 | 中——减少 try/except 分散 |

**总体**：~300 行、极低风险、为 Phase 2 铺路。建议 **Phase 1 与 C、G 并行推进**。

| 维度 | 评分 | 说明 |
|------|------|------|
| IDEA 对齐 | 3 | 间接相关——工程质量改进 |
| 知识库支撑 | 5 | 4 条独立知识全部直接映射 |
| 架构契合 | 4 | 不改变架构，强化工程纪律 |
| 技术可行性 | 5 | 纯 Python 工程改进，零外部依赖 |
| 影响力 | 3 | 不直接改变 Agent 行为，但降低长期维护成本和 bug 风险 |
| 风险 | 5 | 极低——独立改动，不影响核心逻辑 |
| 独立性 | 5 | 完全独立，可与 C、G 并行开发 |

**综合评分**：4.1 / 5.0 — **低风险基础设施，Phase 1 并行推进**

---

## 三、综合评分总览

| # | 方向 | 综合 | 依赖 | 风险 | 建议 |
|---|------|------|------|------|------|
| **C** | **Agent Fitness Functions** | **4.6** | 无 | 极低 | Phase 1 立即启动 |
| **G** | **Ontology 式对象模型** | **4.7** | 无 | 低 | Phase 1 立即启动 |
| **K** | **基础设施工程质量** | **4.1** | 无 | 极低 | Phase 1 并行推进 |
| **A** | **Event Sourcing 记忆** | **4.4** | K1(弱) | 中 | Phase 2（基础设施） |
| **E** | **Agent 自我教学** | **4.0** | A | 中 | Phase 3（需 A 到位） |
| **F** | **能力画像路由** | **4.0** | A(弱) | 低 | Phase 3（需足够 episode） |
| D | 语义记忆检索 | 3.6 | 无 | 低 | Phase 4（规模化后） |
| B | CQRS 读写分离 | 3.2 | A | 低 | A 的自然延伸，不独立 |
| H | Saga 补偿 | 2.3 | — | 中 | 不纳入（过度设计） |
| I | EDA 内部解耦 | 2.3 | — | 高 | 不纳入（过度设计） |
| J | 架构约束 | — | — | — | 已被 G 覆盖 |
| 零-B | 安全架构视角 | — | — | — | 跨切重构，不独立占位 |

---

## 四、交叉分析与协同效应

### 4.1 方向间的增强关系

```
G (Ontology 对象) ──→ 增强 Plan 质量 ──→ 更多成功的 episode
    │                                         │
    │                                         ↓
    │                              F (能力画像) ← 更多数据
    │                                         │
    ↓                                         ↓
A (Event Sourcing) ──→ 结构化事件流 ──→ E (自我教学)
    │                                   
    │──→ 多 Consumer 读视图 ──→ 成本分析 + 对象历史 + 审计
    │                                   
    └──→ C (Fitness Functions) ← 用事件验证架构特性

K (基础设施) ──→ 版本化迁移 ──→ A 的 schema 变更安全可靠
    │──→ 类型化配置 ──→ 所有模块的类型安全基础
    │──→ 集中异常处理 ──→ 减少 try/except 分散
    └──→ Agent 工厂 ──→ 测试更简洁

零-B (安全架构) ──→ Trust Boundaries + CIA + STRIDE
    ──→ 重新框架 DontDoEngine + CredentialGuard + Role
    ──→ 为每个工具接口提供威胁建模标准
    ──→ STRIDE 的 Repudiation 维度 → 由 A (Event Sourcing) 提供完整审计
```

### 4.2 关键协同效应

**G + A = 最强大的组合**：
- G（Ontology 对象）让 LLM 在 plan 时能看到约束、关系和可用操作
- A（Event Sourcing）记录每一步的详细信息
- 两者合力：plan 质量提升 → 成功率提升 → 积累了高质量的 event log → E（自我教学）有更干净的信号 → 正向飞轮

**C + E = 质量闭环**：
- C（Fitness Functions）检测到"plan 质量在下降"
- E（自我教学）分析近期 episode，找出下降原因
- 自动提议纠正规则 → 用户批准 → plan 质量恢复

**F + G = 精准路由**：
- G 让 LLM 理解任务涉及的对象、约束和关系 → plan 更结构化
- F 基于结构化的 task_type（从 G 的 object type 推断）做能力路由
- 例如："这个 goal 涉及 database + git" → 历史数据显示 haiku 在处理 database 任务时成功率只有 60% → 自动升级到 sonnet

### 4.3 YAGNI 红线

知识库中多次强调的 YAGNI 原则在本评估中直接体现：
- **B（CQRS）**：Christian 的原话 "CQRS 应该是最后的选项"——当前数据量下不需要
- **I（EDA 解耦）**：Christian 的标准 "简单系统用直接调用"——当前 Agent 是单进程单体
- **H（Saga）**：为微服务设计的模式，单 Agent 场景过度设计
- **D（语义检索）**：当前 episode 量级 FTS5 足够

---

## 五、实施路线图

### Phase 1：质量基础设施（2-3 周）

```
C: Agent Fitness Functions (5 个 FF)
   ├── FF-1: Plan 完整性验证
   ├── FF-2: 非集规则有效性（含 STRIDE 威胁场景）
   ├── FF-3: 角色合规检查
   ├── FF-4: 上下文效率检测
   └── FF-5: 输出格式合规

G: Ontology 式对象模型
   ├── AgentObject 扩展: +constraints, +relations, +available_actions
   ├── tool.md 格式增强: 支持 constraints 和 relations 声明
   ├── PromptAssembler 集成: 对象上下文注入 planning prompt
   └── 向后兼容: 新字段全有默认空值

K: 基础设施工程质量
   ├── K1: 版本化 Schema 迁移（替代 ad-hoc try/except）
   ├── K2: 类型化配置层次（dataclass 替代裸 dict）
   ├── K3: Agent 工厂模式形式化（create_agent()）
   └── K4: 集中异常处理链（raise → catch → sanitize）

零-B: 安全架构文档化
   └── 用 Trust Boundaries + CIA + STRIDE 框架重述现有安全机制
```

**目标**：
- 任何改动都能被 FF 检测到架构偏离
- LLM 做 plan 时看到的不再是裸对象，而是"有约束、有关系、有可用操作"的对象
- Schema 变更有版本追踪和回退能力
- 配置错误在 IDE 中暴露，而非运行时

### Phase 2：记忆基础设施（3-4 周）

```
A: Event Sourcing 记忆
   ├── Event schema 设计: GoalStarted, ObjectObserved, ToolCalled,
   │   ToolResult, PlanGenerated, CorrectionApplied, GoalVerified,
   │   GoalCompleted
   ├── EventStore: SQLite append-only event log
   ├── EventPublisher: 简单的进程内 pub/sub（非 EDA！只做通知）
   ├── Snapshot 机制: 每 N 个 event 存一次状态快照
   ├── EpisodeEntry 适配: 从 event log 构建 episode 视图
   └── 迁移脚本: 现有 episodic 表数据 → event log
```

**关键设计决策**：Event Publisher 不是 EDA Broker——它是进程内的同步回调列表，没有 Broker 的持久化和异步语义。避免了 I（EDA 解耦）的代价。

```python
class EventPublisher:
    """进程内同步事件通知——不是 EDA Broker."""
    
    def __init__(self):
        self._subscribers: dict[str, list[callable]] = {}
    
    def subscribe(self, event_type: str, handler: callable) -> None:
        self._subscribers.setdefault(event_type, []).append(handler)
    
    def publish(self, event: AgentEvent) -> None:
        for handler in self._subscribers.get(event.type, []):
            handler(event)  # 同步调用，不引入异步复杂度
```

### Phase 3：智能增强（4-6 周）

```
E: Agent 自我教学
   ├── PatternMiner: 跨 episode 聚类分析
   ├── 错误模式识别: "同类型任务反复出现同一错误"
   ├── 纠正模式识别: "同一纠正反复出现"
   └── 提案机制: Agent 提议 → 用户审批 → 生成规则/skill

F: 能力画像路由
   ├── CapabilityProfile: per-model, per-task_type 成功率追踪
   ├── Router 增强: 在成本路由基础上叠加能力路由
   └── 冷启动策略: 新任务类型用成本路由，积累5+条后切换到能力路由
```

### Phase 4：规模化增强（按需启动）

```
D: 语义记忆检索
   └── 当 episode 量级 > 1000 且 FTS5 搜索不够用时启动
```

### 实施顺序依赖图

```
Phase 1              Phase 2             Phase 3          Phase 4
─────────            ─────────           ─────────        ─────────
C (FF) ─────────────────────────────────────────────────────→ 持续运行
G (Ontology) ────→ 提升 episode 质量 ──→ 更多好数据 ──→ E, F
K (基础设施) ────→ K1 版本迁移 ──→ A 的 schema 变更安全
                    │
                    ↓
              A (Event Sourcing) ──────→ E (自我教学)
                    │                    │
                    │                    └──→ 正向飞轮
                    │
                    ├────────────────→ F (能力画像)
                    │                    │
                    │                    └──→ D (语义检索)
                    │                         (Phase 4, 规模化后)
                    │
                    └──→ 多 Consumer 读视图
                         (成本分析/对象历史/审计/能力画像)

零-B (安全架构) ──→ 贯穿所有 Phase ──→ 持续指导安全设计决策
```

---

## 六、风险矩阵

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| Event Sourcing schema 设计不当，后续迁移成本高 | 中 | 高 | K1 版本化迁移确保可回退；新旧 schema 并行运行 2 周 |
| 一致性模型选择错误——安全规则传播延迟导致窗口期漏洞 | 低 | 高 | 安全关键事件同步写入+立即通知；非安全事件异步 |
| 自我教学模式挖掘产生大量假阳性 | 高 | 中 | 所有提案必须人类审批；设置高置信度阈值（>0.7） |
| Ontology 对象模型导致 prompt 膨胀 | 中 | 中 | 渐进式披露——只在 planning prompt 中注入，不在每个 turn 中重复 |
| 能力画像因 episode 太少而过拟合 | 中 | 低 | 最少 5 条 episode 才有统计意义；冷启动期间继续用成本路由 |
| FF 太严格导致开发体验下降 | 低 | 低 | FF 失败 = 警告，不是阻断（来自 `fitness-functions-vs-unit-tests.md`） |
| 类型化配置迁移破坏现有 config.yaml 兼容性 | 低 | 中 | `from_yaml()` 保持完全向后兼容；渐进迁移 |

---

## 七、不做清单（Don't-Do — 应用 YAGNI + 架构重要性过滤器）

基于知识库中的 YAGNI 原则和 Christian/Richards/Karpathy 的反复警告，明确不做的方向：

| 方向 | 不做的原因 | KB 依据 |
|------|-----------|---------|
| EDA 内部解耦 | 单进程单体不需要异步事件架构 | `eda-tradeoffs.md`: "简单系统用直接调用" + `stateful-vs-stateless-scaling.md`: 当前 Agent 是无状态服务 |
| Saga 完整模式 | 为微服务分布式事务设计，单 Agent 过度设计 | `saga-pattern.md`: "Saga 没有隔离" + `orchestration-vs-choreography.md`: "简单工作流用 Choreography" |
| CQRS 独立实施 | 当前数据量 CRUD 完全够用 | `cqrs-pattern.md`: "CQRS 应该是最后的选项" + `yagni-principle.md`: "不确定的需求先不做" |
| 语义检索（Phase 4 前） | 当前 episode 量级 FTS5 足够 | `yagni-principle.md` + `index-structures.md`: "不同索引类型适合不同查询模式" — 当前查询模式不需要 vector |
| Multi-Agent Orchestration | Phase 1-3 聚焦单 Agent 质量 | `leader-election.md`: "简单场景不需要自己实现 Leader Election" + `consensus-in-distributed-systems.md`: "某些场景可以避免共识" |
| Horizontal Scaling | 单用户单会话，无扩展需求 | `horizontal-scaling.md`: "一旦确定会超过单机规模，尽早采用" — 当前未确定 |

### 架构重要性过滤器

来自 `software-architecture-definition.md` 的判断标准：
> "Architecture is about the important stuff — the expensive choices costly to change."

**架构级决策（变更成本极高）**：
- Event Sourcing 数据范式 — 一旦选定，所有查询、存储、迁移都基于此
- Ontology 对象模型 — 一旦选定，LLM 的认知上下文结构就固定了
- Trust Boundaries 安全模型 — 一旦选定，所有工具接口的安全假设基于此

**非架构级决策（可在任何阶段调整）**：
- Fitness Functions 的具体规则 — 增删 FF 不改变系统结构
- 配置格式（YAML → dataclass）— 对外接口不变
- 异常处理方式 — 纯内部重构
- 能力画像的阈值参数 — 调参不改架构

这个过滤器解释了什么值得花更多时间设计（Phase 2 的 Event Sourcing 值得深思熟虑），什么可以快速迭代（Fitness Functions 可以先写 3 个，不够再加）。

---

## 八、总结

**当前代码状态**：原有 improvement-plan.md 的 8 个方向已全部实现。代码质量良好，170 个测试通过，架构清晰。

**评估方法论**：
- 知识库覆盖：从 `D:\GitHub\wiki-quiz-kit\wiki\permanent` 读取 50+ 条专业知识
- 覆盖领域：Agent 模式（6 条）、架构模式（12 条）、分布式系统（8 条）、LLM 认知（5 条）、安全（4 条）、Ontology（4 条）、工程实践（8 条）、测试与质量（4 条）
- 评估维度：7 维度加权评分 × 每方向独立打分
- YAGNI 过滤：应用知识库自身的 YAGNI 原则，明确排除 5 个方向

**最终结论**：
- **Phase 1（3 个方向并行）**：C (Fitness Functions, 4.6) + G (Ontology 对象模型, 4.7) + K (基础设施工程, 4.1) + 零-B (安全架构文档化)
- **Phase 2（1 个方向）**：A (Event Sourcing, 4.4) — 含一致性模型设计
- **Phase 3（2 个方向）**：E (自我教学, 4.0) + F (能力画像, 4.0)
- **Phase 4（1 个方向）**：D (语义检索, 3.6) — 规模化后按需启动
- **不纳入（5 个方向）**：B/CQRS, H/Saga, I/EDA, J/约束（独立）, 多 Agent 编排 — 过度设计或已被覆盖

**核心飞轮**：Ontology 对象模型 → Plan 质量提升 → 成功率提升 → Event Sourcing 积累高质量事件 → 自我教学发现模式 + 能力画像精准路由 → Agent 越来越聪明。

**架构原则**（来自 `software-architecture-definition.md`）：
> "Architecture is about the important stuff — the expensive choices costly to change."
> 
> 本方案中的架构级决策：Event Sourcing（数据范式）、Ontology 对象模型（认知范式）、Trust Boundaries 安全模型（安全范式）。这三个是"代价高昂的选择"——一旦选定后变更成本极高。其余方向（Fitness Functions、基础设施工程、能力画像）是这些架构决策之上的增量增强，可以在任何阶段调整。
