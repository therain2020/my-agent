# Phase 4: 清理与打磨 — 详细实施方案

## 目标

删除所有旧代码，更新项目元数据，确保干净的发布状态。

## 4.1 待删除文件

### agent/ 核心（已被 Phase 1 取代）
```
agent/core.py              # → therain2020/agent.py
agent/memory.py            # → therain2020/memory.py（迁移）
agent/dont_do.py           # → therain2020/safety.py（合并）
agent/event_store.py       # 移除（双重存储）
agent/events.py            # 移除（双重存储）
agent/consolidation.py     # 移除（重叠）
agent/pattern_miner.py     # 移除（重叠）
agent/objects.py           # 移除（过度抽象）
agent/context.py           # 移除（过度设计）
agent/context_compressor.py # 移除（过度设计）
agent/prompt.py            # 移除（XML 格式）
agent/output_format.py     # 移除（XML 格式）
agent/config.py            # 移除（过度工程）
agent/correction.py        # 内联到 agent.py
agent/interrupt.py         # 移除（Signal handler 内联）
agent/retry.py             # 移除（内联到 provider.py）
agent/streaming.py         # 移除（内联到 agent.py）
agent/errors.py            # 移除（简单异常类内联）
agent/role.py              # 移除
agent/search.py            # 移除
agent/eval.py              # 移除
agent/publish.py           # 移除
agent/multi_agent.py       # 移除
agent/memory_migrations.py # 移除（新 schema）
```

### agent/tools/（已被 Phase 1 取代）
```
agent/tools/registry.py    # → therain2020/tools.py
agent/tools/loader.py      # → therain2020/tools_md.py
agent/tools/executor.py    # 内联到 agent.py
agent/tools/evolution.py   # 移除
agent/tools/editor.py      # 移除
agent/tools/supervisor.py  # 移除
agent/tools/mcp_transports.py # 移除
```

### agent/providers/（已被 Phase 1 取代）
```
agent/providers/__init__.py   # → therain2020/provider.py
agent/providers/anthropic.py  # → therain2020/provider.py
agent/providers/openai.py     # → therain2020/provider.py
agent/providers/deepseek.py   # → therain2020/provider.py
agent/providers/custom.py     # 移除
agent/providers/router.py     # → therain2020/provider.py
agent/providers/pool.py       # 移除
agent/providers/capability.py # 移除
```

### agent/security/（已被 Phase 1 取代）
```
agent/security/__init__.py    # → therain2020/safety.py
agent/security/credentials.py # → therain2020/provider.py
```

### agent/skills/（移除）
```
agent/skills/                 # 整个目录
```

### agent/tools/adapters/（移除，除 browser_harness.py 可能保留）
```
agent/tools/adapters/claude_skill.py
agent/tools/adapters/claude_settings.py
agent/tools/adapters/mcp.py
agent/tools/adapters/claude_plugin.py
agent/tools/adapters/codex.py
agent/tools/adapters/cursor.py
agent/tools/adapters/gemini.py
agent/tools/adapters/remote_search.py
agent/tools/adapters/scanner.py
agent/tools/adapters/validator.py
agent/tools/adapters/plain_text.py
```

### agent/cli/（已被 Phase 2 取代，旧 CLI 文件）
```
agent/cli/run.py
agent/cli/add.py
agent/cli/info.py
agent/cli/providers.py
agent/cli/publish.py
agent/cli/status.py
agent/cli/display.py
agent/cli/__main__.py
```

### 测试（迁移或移除）
```
tests/unit/test_memory.py     # 已迁移到 tests/test_memory.py
tests/unit/test_dont_do.py    # 已迁移到 tests/test_safety.py
tests/unit/test_registry.py   # 已合并到 tests/test_tools.py
tests/unit/test_tool_loader.py # 已合并到 tests/test_tools.py
tests/unit/test_provider_pool.py # 已合并到 tests/test_provider.py
tests/unit/test_capability.py # 移除（capability 矩阵已移除）
tests/unit/test_cost_router.py # 已合并到 tests/test_provider.py
tests/unit/test_consolidation.py # 移除
tests/unit/test_pattern_miner.py # 移除
tests/unit/test_context.py    # 移除
tests/unit/test_correction.py # 移除
tests/unit/test_errors.py     # 移除
tests/unit/test_objects.py    # 移除
tests/unit/test_output_format.py # 移除
tests/unit/test_adapters.py   # 移除
tests/unit/test_mcp_transports.py # 移除
tests/unit/test_multi_agent.py # 移除
tests/unit/test_publish.py    # 移除
tests/unit/test_eval.py       # 移除
tests/unit/test_fitness.py    # 移除
tests/unit/test_credentials.py # 移除
tests/unit/test_security.py   # 移除
tests/test_skills.py          # 移除
tests/test_evolution.py       # 移除
tests/test_context_compressor.py # 移除
tests/test_verification.py    # 移除
tests/test_repl.py            # 已迁移到 tests/cli/test_repl.py
tests/test_browser_harness.py # 保留（如果仍适用）
tests/test_autodetect.py      # 已合并到 tests/test_provider.py
tests/integration/test_e2e.py # 重写
tests/test_search.py          # 移除
tests/test_skills_lifecycle.py # 移除
```

## 4.2 更新项目文件

### pyproject.toml

```toml
[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[project]
name = "therain2020"
version = "0.8.0"
description = "Thin AI agent harness — less framework, more agent"
requires-python = ">=3.11"
dependencies = [
    "httpx>=0.27",
    "anthropic>=0.40",
    "openai>=1.50",
    "pyyaml>=6.0",
    "pillow>=11.0",
]
[project.optional-dependencies]
tui = ["textual>=0.70", "rich>=13.0"]
browser = ["cdp-use>=1.4"]

[project.scripts]
therain2020 = "therain2020.run:cli"

[tool.setuptools]
package-dir = {"" = "src"}

[tool.setuptools.packages.find]
where = ["src"]
```

### README.md

重写为体现新理念：
- 薄 harness，非框架
- Agent 编写自己的工具
- 截图优先的浏览器交互

### CLAUDE.md

更新以反映新架构和项目结构。

## 4.3 最终测试

```bash
# 1. 所有单元测试
pytest tests/ -v

# 2. 代码质量
ruff check therain2020/ tests/

# 3. 导入验证
python -c "import therain2020; print(therain2020.__version__)"

# 4. 端到端测试（需要 API 密钥）
pytest tests/integration/ -v

# 5. CLI 测试
therain2020 --help
echo "say hello" | therain2020
```

## 4.4 最终目录结构

```
D:\GitHub\therain2020-agent\
├── therain2020/            # 新核心包
│   ├── __init__.py
│   ├── run.py
│   ├── agent.py
│   ├── session.py
│   ├── memory.py
│   ├── safety.py
│   ├── tools.py
│   ├── tools_md.py
│   ├── provider.py
│   ├── _ipc.py
│   ├── jsonutil.py
│   ├── constants.py
│   ├── cli/
│   │   ├── __init__.py
│   │   ├── tui.py
│   │   └── repl.py
│   └── domain/
│       ├── __init__.py
│       ├── browser.py
│       ├── filesystem.py
│       └── tools/
│           ├── file-reader.md
│           ├── file-writer.md
│           ├── file-lister.md
│           └── browser-control.md
├── agent/                  # 旧核心（将被移除）
├── tests/
│   ├── test_jsonutil.py
│   ├── test_memory.py
│   ├── test_safety.py
│   ├── test_tools.py
│   ├── test_provider.py
│   ├── test_session.py
│   ├── test_agent.py
│   ├── test_run.py
│   ├── cli/
│   │   ├── test_tui.py
│   │   └── test_repl.py
│   ├── domain/
│   │   ├── test_filesystem.py
│   │   └── test_browser.py
│   └── integration/
│       └── test_end_to_end.py
├── agent-workspace/        # Agent 自编工具
│   └── .generated/
├── docs/
│   ├── phase-1-plan.md
│   ├── phase-2-plan.md
│   ├── phase-3-plan.md
│   └── phase-4-plan.md
├── pyproject.toml
├── README.md
├── CHANGELOG.md
└── CLAUDE.md
```

## 验收标准

```bash
# 1. 旧 agent/ 代码不再被引用
rg "from agent\." therain2020/  # 应该无输出

# 2. 所有测试通过
pytest tests/ -v

# 3. 代码行数目标
# 核心: < 2000 行 ✓  (目标 3000)
# 总计: < 4500 行 ✓

# 4. 打包可用
python -m build
pip install dist/therain2020-0.8.0-py3-none-any.whl
therain2020 --version
```
