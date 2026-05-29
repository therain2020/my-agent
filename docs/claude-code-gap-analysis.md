# Claude Code 架构差距分析与改进方案

> 深度对比 therain2020-agent (Python) vs Claude Code (TypeScript/Ink)，按严重程度排序
> 2026-05-28

---

## 十大关键差距

### 1. 工具格式：XML vs 原生 tool_use API

**严重性：致命**

当前用 `<function_call>` XML + 正则解析。Claude Code 用 Anthropic Messages API 原生 `tool_use` 内容块。

| 维度 | 当前 | Claude Code |
|------|------|-------------|
| 工具定义 | YAML tool.md + 正则 | Zod schema → API tool parameter |
| 调用方式 | LLM 生成 XML 文本 | API 原生 tool_use 块 |
| 解析 | 正则 `_parse_tool_calls()` | 类型化 content block |
| 参数验证 | 无 | Zod safeParse |
| 流式 | 等待全文 | 块到达时流式传输 |

**修复**：provider 层适配 Anthropic/OpenAI 原生 tool calling。

### 2. 消息架构：字符串拼接 vs 结构化数组

**严重性：致命**

当前把所有对话拼成一个字符串。Claude Code 用 `Message[]` 类型化数组。

影响：提示缓存完全无效、工具结果无法关联 tool_use_id、无并行工具调用。

**修复**：重构为结构化消息数组。

### 3. 上下文压缩未接入循环

**严重性：高**

`ContextManager` 和 `SemanticCompressor` 已实现但 `run_stream()` 从未调用。
对话字符串无限增长直到 `[-3000:]` 截断。

**修复**：在每次循环迭代中集成压缩，token 预算触发自动压缩。

### 4. 工具执行无模式验证

**严重性：高**

无参数类型检查。参数类型错误 → Python TypeError → 模糊错误。

**修复**：为每个 capability 添加 JSON Schema，执行前验证。

### 5. 代理循环最大 3 次迭代

**严重性：高**

`max_loop_iterations = 3`。Claude Code 的 `while(true)` 直到完成。

**修复**：移除硬限制，改用 token 预算 + 自动压缩触发。

### 6. 无会话持久化

**严重性：高**

进程崩溃 = 会话丢失。无 `/resume`。

**修复**：JSONL 转录文件 + 会话恢复。

### 7-10：连续性恢复、流架构、系统提示、子代理

详见完整分析文档。

---

## 修复优先级

| Phase | 内容 | 影响 |
|-------|------|------|
| **P0 (立即)** | 工具格式：XML → 原生 API | 工具调用成功率 |
| **P0 (立即)** | 消息：字符串 → 结构化数组 | 提示缓存、上下文准确 |
| **P1 (本周)** | 压缩接入循环 | 长对话不崩溃 |
| **P1 (本周)** | 工具验证 | 参数错误不再静默 |
| **P2 (本月)** | 会话持久化 | 可恢复 |
| **P3** | 子代理、连续性、提示缓存 | 性能和成本 |
