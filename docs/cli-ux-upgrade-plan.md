# CLI UX 升级方案：流式输出 + 思考模式 + Rich 渲染

> 参考 Claude Code src/ 架构，升级 therain2020-agent 的 CLI 交互体验
> 2026-05-28

---

## 一、现状

| 维度 | 当前 | 问题 |
|------|------|------|
| 输出 | 阻塞式，全部完成后一次性打印 | 无实时反馈，等待焦虑 |
| 思考 | 无 | 模型思考过程不可见 |
| 渲染 | 纯文本 click.echo | 无 markdown、颜色面板、进度指示 |
| 交互 | 单行 input() | 无历史、无补全 |
| Provider | 自动检测 env var | ✅ 已解决 (v0.6.1+) |

---

## 二、Claude Code 关键架构参考

| 模块 | 模式 | 移植方案 |
|------|------|---------|
| 流式输出 | `AsyncGenerator` yield typed messages | `Agent.run_stream()` → `StreamEvent` |
| 思考显示 | `AssistantThinkingMessage` 组件，dim 渲染，可折叠 | `Rich Panel` + `/think` toggle |
| Spinner | `useAnimationFrame(50ms)` + verb 切换 | `rich.spinner.Spinner` + `rich.live.Live` |
| Markdown | `marked` lexer + 缓存 + ANSI 输出 | `rich.markdown.Markdown` |
| 状态 | `AppState` store 驱动渲染 | `StreamingDisplay` 管理状态 |

---

## 三、实施方案

### Phase 1: Provider 结构化流式 (已完成)

- `AnthropicProvider.complete_stream_structured()` — 解析 `thinking_delta` / `text_delta`
- `OpenAIProvider.complete_stream_structured()` — 解析 `reasoning_content` / `content`

### Phase 2: Agent 流式执行 (已完成)

- `Agent.run_stream(task)` — AsyncGenerator yielding `StreamEvent`
- `Agent.supports_structured_stream()` — 检测 provider 能力

### Phase 3: Rich 流式显示 (已完成)

- `StreamingDisplay` — `rich.live.Live` + Panel + Markdown
- Thinking 块：默认展开，`/think` 切换
- Tool 进度：`→ tool.cap ✓` / `⚠`
- 完成摘要：`[OK] N steps in X.Xs`

### Phase 4: 向后兼容

- 不支持 structured stream 的 provider 回退到 legacy `run()` + progress callback
- Goal mode 走 legacy 路径

---

## 四、新增文件

| 文件 | 说明 |
|------|------|
| `agent/streaming.py` | StreamEvent 数据模型 |
| `agent/cli/display.py` | Rich 流式显示组件 |
| `agent/cli/autodetect.py` | Provider 自动检测 (Phase 0) |

## 五、修改文件

| 文件 | 改动 |
|------|------|
| `agent/providers/anthropic.py` | +complete_stream_structured |
| `agent/providers/openai.py` | +complete_stream_structured |
| `agent/core.py` | +run_stream, +supports_structured_stream |
| `agent/cli/repl.py` | 集成 StreamingDisplay, /think 命令 |
| `agent/cli/run.py` | 自动检测 provider |
| `pyproject.toml` | +rich 依赖 |
