# CLAUDE.md — therain2020-agent

## Design Reference

设计文档和方案讨论位于: `D:\GitHub\agent-design\temp\`

| # | 文件 | 主题 |
|---|------|------|
| 01 | agent-structure.md | Agent 结构设计 |
| 02 | agent-loop.md | Agent 事件循环 |
| 03 | two-modes.md | TODO / Goal 双模式 |
| 04 | long-term-memory.md | 长期记忆系统 |
| 05 | dont-do-set.md | 非集设计 |
| 06 | supplemental-requirements.md | 补充需求 |
| 07 | interrupt-signal.md | 中断信号机制 |
| 08 | tool-registration.md | 工具注册与发现 |
| 09 | dont-do-storage.md | 非集存储方案 |
| 10 | memory-consolidation.md | 记忆整合 |
| 11 | system-architecture.md | 系统架构总览（OS 内核类比映射）|
| 12 | error-recovery.md | 错误恢复机制 |
| 13 | tech-stack.md | 技术栈选型 |
| 14 | context-window.md | 上下文窗口管理 |
| 15 | prompt-assembly.md | 提示组装器设计 |
| 16 | session-management.md | 会话管理 |
| 17 | observability.md | 可观测性 |
| 18 | security-threat-model.md | 安全威胁模型 |
| 19 | evaluation.md | 评估基准 |
| 20 | multi-agent.md | 多代理协作 |
| 21 | phase-one-plan.md | Phase 1 实施计划（Add-First Agent v0.1）|
| 22 | release-workflow.md | 发布流程 |
| 23 | semantic-memory-consolidation-v2.md | 语义记忆整合 V2 |
| 24 | goal-mode.md | Goal 模式设计 |
| 25 | dont-do-engine-v2.md | 非集引擎 V2（iptables 风格）|
| 26 | provider-failover-security.md | Provider 故障转移和安全 |
| 27 | phase-two-plan.md | Phase 2 实施计划（记忆与安全深化）|
| 28 | publish-marketplace.md | 发布与市场 |
| 29 | cost-routing.md | 成本路由 |
| 30 | phase-three-plan.md | Phase 3 实施计划（质量与协作）|

## 行为规则

- 当用户讨论设计方案、架构决策或新需求时，主动查阅 `D:\GitHub\agent-design\temp\` 中的相关设计文档作为上下文参考
- 当用户提出"像之前讨论的那样"或"按照设计来"时，先到设计文档目录确认原意再执行
- 设计文档是设计阶段的产物，当前实现可能已有偏差。以代码为准，设计文档仅供理解原始意图

## Project Architecture

核心模块按 OS 内核类比组织:

| 模块 | 类比 |
|------|------|
| `agent/core.py` | 核心事件循环（TODO 模式 + Goal 模式 reconciliation loop）|
| `agent/prompt.py` | ELF loader + linker script |
| `agent/context.py` | MMU + page replacement |
| `agent/memory.py` | ext4 journal (SQLite WAL) |
| `agent/tools/registry.py` | udev device database |
| `agent/tools/executor.py` | execve + kernel module calls |
| `agent/providers/pool.py` | RAID 1 + multipath I/O |
| `agent/providers/router.py` | ondemand cpufreq governor |
| `agent/dont_do.py` | iptables netfilter |
| `agent/tools/supervisor.py` | systemd |
| `agent/objects.py` | VFS inode |
| `agent/role.py` | seccomp profile |
| `agent/correction.py` | auditd + rule generation |
| `agent/output_format.py` | syslog format enforcer |

## 常规命令

```bash
# 测试
pytest tests/ -v

# Lint
ruff check agent/ tests/

# 构建
python -m build
```

## Network

此环境联网需代理。代理地址从系统环境变量 `net_proxy` 读取。

```bash
# 使用方式。$env:net_proxy 值类似 http://127.0.0.1:7890
curl --proxy $net_proxy ...
pip install --proxy $net_proxy ...
```

## Release Flow

```
1. python scripts/bump_version.py patch|minor|major
2. Update CHANGELOG.md
3. git checkout -b feat/release-vX.Y.Z
4. git add ... && git commit && git push && gh pr create
5. 等 CI 全绿 → merge PR
6. CI 自动: 读 pyproject.toml 版本号 → git tag vX.Y.Z → build
   → GitHub Release（含 release notes）→ PyPI 发布
```

Tag 由 CI 在 merge commit 上自动创建，保证 tag 和 master 代码永远一致。不需要手动打 tag。

### Release Verification

每次发布后验证三步：

```bash
# 1. 确认 GitHub Actions
gh run list -w release.yml --limit 1

# 2. 确认 PyPI 版本（走代理）
curl -s --proxy $env:net_proxy \
  "https://pypi.org/pypi/therain2020-agent/json" \
  | python -c "import sys,json; d=json.load(sys.stdin); print(d['info']['version'])"

# 3. 干净环境安装测试（走代理）
python -m venv /tmp/test-pypi
/tmp/test-pypi/Scripts/pip install --proxy $env:net_proxy \
  therain2020-agent==<version>
/tmp/test-pypi/Scripts/python -c "import agent; print(agent.__version__)"
rm -rf /tmp/test-pypi
```

## 行为规则

- 网络操作走 `$env:net_proxy` 代理（由系统环境变量配置），不要再问
- 发布后自动执行三步验证，不要再问
