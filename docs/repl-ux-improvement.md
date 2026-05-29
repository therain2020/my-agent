# REPL 体验优化方案

## 当前问题

1. **看不到 LLM 思考过程** — 模型（DeepSeek R1、Claude thinking 等）的推理内容被丢弃
2. **工具调用看不到参数** — 只显示 `filesystem__read`，不知道读了哪个文件
3. **工具结果时序错误** — `run_stream()` 在工具实际执行前就 yield 了 `tool_result`

## 改动范围

4 个文件，约 +60/-20 行。

### 1. `therain2020/provider.py` — 提取思考内容

```python
@dataclass
class LLMResponse:
    content: str
    reasoning: str = ""          # 新增：思考/推理内容
    tool_calls: list[dict] | None = None
    finish_reason: str = "stop"
    model: str = ""
    tokens_used: int = 0
```

`_complete_openai()` 提取 `choice.message.reasoning_content`（DeepSeek R1 / o1 等）。
`_complete_anthropic()` 提取 `thinking` 类型的 content block。

### 2. `therain2020/cli/streaming.py` — 工具参数

```python
@dataclass
class StreamEvent:
    ...
    arguments: dict = field(default_factory=dict)   # 新增：工具调用参数

    @classmethod
    def tool_start(cls, name, args: dict):           # 签名变更
        return cls(type=StreamEventType.TOOL_START,
                   tool_name=name, arguments=args)
```

### 3. `therain2020/agent.py` — 修复时序 + 传递参数

```python
async def run_stream(task, session):
    ...
    for _ in range(session.max_steps):
        response = await _step(session, tools_used)

        # 1. 输出思考内容
        if response.reasoning:
            yield StreamEvent.thinking(response.reasoning)

        # 2. 输出正文
        if response.content:
            yield StreamEvent.text(response.content)

        # 3. 工具调用：先 start（带参数），执行，再 result
        if response.tool_calls:
            for tc in response.tool_calls:
                name = tc["function"]["name"]
                args = safe_parse_json(tc["function"]["arguments"])

                yield StreamEvent.tool_start(name, args)

                # 执行工具
                result = await _execute_tool(tc, session, tools_used)
                tools_used.append(name)

                yield StreamEvent.tool_result(name, True, str(result)[:200])
```

### 4. `therain2020/cli/repl.py` — 显示改进

```python
async def _execute(self, task):
    ...
    async for event in run_stream(task, session):
        if event.type == StreamEventType.THINKING:
            # 思考过程：灰色、缩进显示
            print(f"\n  [思考] {event.content[:500]}", flush=True)

        elif event.type == StreamEventType.TEXT:
            print(event.content, end="", flush=True)

        elif event.type == StreamEventType.TOOL_START:
            # 带参数显示：filesystem__read("path/to/file")
            args_str = ", ".join(f"{k}={v!r}" for k, v in event.arguments.items())
            print(f"\n  … {event.tool_name}({args_str})", flush=True)

        elif event.type == StreamEventType.TOOL_RESULT:
            mark = "✓" if event.ok else "✗"
            # 显示结果摘要（最多100字符）
            summary = event.content[:100] if event.content else ""
            if summary:
                print(f"  [{mark}] → {summary}", flush=True)
            else:
                print(f"  [{mark}]", flush=True)
```

## 效果预览

```
> 读取 wiki 目录下关于架构的文件

  [思考] 用户需要读取 wiki 目录下的架构相关文件。首先列出 wiki 目录内容...
  
  … filesystem__list_files(dir='D:\\GitHub\\wiki-quiz-kit\\wiki', pattern='*架构*')
  [✓] → []

  [思考] 没有直接匹配"架构"的文件，扩大搜索范围列出所有文件...
  
  … filesystem__list_files(dir='D:\\GitHub\\wiki-quiz-kit\\wiki', pattern='*')
  [✓] → ['architecture.md', 'getting-started.md', 'api-reference.md']

  [思考] 找到了 architecture.md，读取它...
  
  … filesystem__read(path='D:\\GitHub\\wiki-quiz-kit\\wiki\\architecture.md')
  [✓] → # Wiki Quiz Kit Architecture\n\n## Overview\n...

  wiki 目录下关于架构的文件是 architecture.md，其内容如下：...
```

## 改动量

| 文件 | 变更 |
|------|------|
| `provider.py` | +15 行 (reasoning 字段 + 提取逻辑) |
| `cli/streaming.py` | +5 行 (arguments 字段) |
| `agent.py` | +25/-15 行 (时序修复 + 参数传递 + 思考输出) |
| `cli/repl.py` | +15/-5 行 (显示思考 + 参数 + 结果摘要) |
| **合计** | **约 +60/-20 行** |
