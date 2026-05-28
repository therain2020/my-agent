# therain2020-agent

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-302%20passed-brightgreen.svg)](tests/)
[![PyPI](https://img.shields.io/pypi/v/therain2020-agent.svg)](https://pypi.org/project/therain2020-agent/)

[English](README.md)

一个会自己检查工作的 Agent 框架。动手前先观察对象状态，运行时拦截危险操作，拿证据验证结果，每次犯错都记住。

---

## 和别的 Agent 框架有什么不同

多数框架做的事：发 prompt → LLM 说干啥就干啥 → 结束。这个不是。

- **动手前先观察。** 写文件之前知道文件长什么样。改完再观察一次。对比前后差异。
- **运行时拦截，不靠 prompt 请求。** Dont-do 规则在三个 hook 点生效。路径感知——设了"禁写 /etc"，真的写 `/etc/passwd` 时会被拦住。
- **验证靠证据。** 重新观察对象终态，和验收标准逐条比对。返回置信度，不猜 YES/NO。
- **记忆用事件溯源。** 每次观察、每次工具调用、每次纠正、每次验证都是一条不可变事件。可完整回放。可审计。
- **路由看能力，不只看成本。** 记录每个模型在每类任务上的成功率。发现 haiku 做数据库迁移成功率只有 60%，自动切到 sonnet。
- **自己发现模式。** 挖掘历史任务中的重复错误、重复纠正、重复失败。主动提议规则。你来批。
- **工具自己会进化。** 工具缺失或静默失败时，agent 自己读现有代码、写缺失函数、git 提交、重试。坏了能回滚。
- **积累技能网络。** 每次成功任务都蒸馏成技能。技能有评分、有迭代、太烂自动退役、雷同自动合并。保存前 PII 双重检查。
- **压缩上下文不乱删。** LLM 驱动的语义压缩，程序指令类的永不压缩——防止"诶我的规则呢"这类 bug。
- **直接操控浏览器。** 不走 Playwright 包装层，裸 CDP 直连。截图→看像素→点坐标→再截图验证。agent 跑着跑着自己扩展浏览器工具。

---

## 安装

```bash
pip install therain2020-agent
```

## 三分钟用起来

```bash
# 加一个 provider
therain2020-agent provider add qwen --adapter custom \
  --api-key-env ALI_TONGYI_KEY \
  --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 \
  --model qwen-plus

# 发现本地已有的工具
therain2020-agent add discover

# 跑个任务
therain2020-agent run "给登录接口加上频率限制"
```

---

## 怎么工作的

### 主循环

```
观察 → 分析 → 规划 → 执行 → 验证 → (不行再来，最多 3 轮)
```

不是一次性 prompt→response。是 K8s reconciliation loop 的思路——目标没达成就不停，直到验证通过或者轮次耗尽。

### 两种模式

| 模式 | 适合 | 怎么验证 |
|------|------|---------|
| **TODO** | 有明确验收标准的任务 | 分析描述是否清晰，缺标准就问你，逐条比对 |
| **Goal** | 开放式目标 | 重新观察对象，计算前后 diff，输出置信度 |

### 它怎么看世界——Ontology 对象模型

Agent 看到的不是裸字符串。每个对象带四层信息：

- **状态** — 长什么样（大小、分支、哈希值）
- **约束** — 不能对它做什么（"别写系统目录"、"别硬编码密钥"）
- **操作** — 能对它做什么（前置条件 + 副作用都会说明）
- **关系** — 它和谁有关（被哪个测试覆盖、import 了什么、依赖了哪个包）

这四层信息直接注入 planning prompt。LLM 看到的是"文件 X，大小 100，约束：非系统路径，关联 test_auth.py，可 read/write"——而不是光秃秃的"文件 X"。

---

## 安全

### Dont-Do 规则

规则在运行时生效，不是写在 prompt 里的建议。三个拦截点：

```
PLAN        → 计划阶段就过滤危险步骤
PRE_ACTION  → 工具调用前拦截危险参数
POST_ACTION → 执行后审计结果
```

检查前自动增强上下文——从参数里提取路径，设好 `path_in_restricted` 和 `path_matches`。你写规则时说"禁写 /etc"，代码真的写 `/etc/passwd` 时能拦住。

### 信任边界 (STRIDE)

每次工具调用都是一次信任边界跨越。STRIDE 六个维度都有对策：

| 威胁 | 怎么防 |
|------|--------|
| 假冒 (Spoofing) | Role + DontDoEngine 双重校验 |
| 篡改 (Tampering) | PRE_ACTION 阶段检查路径参数 |
| 否认 (Repudiation) | Event Sourcing 完整审计日志 |
| 信息泄露 | POST_ACTION 结果过滤 + 凭据脱敏 |
| 拒绝服务 | max_iterations 上限 + 中断处理 |
| 提权 (Elevation) | Role 白名单——不在名单里的工具调不了 |

### 纠正即学习

发现 agent 做错了？往 `corrections/` 目录扔个 YAML。agent 自动生成 dont-do 规则、持久化、重规划。同一个错误不犯第二次。

### 工具自愈

工具不只是被调用——它们会进化。agent 发现工具缺失或静默失败时：

```
工具挂了 → 读现有代码 → 写缺失函数 → git 提交 → 重试
```

静默失败是 agent 最隐蔽的坑：工具说"OK"，实际啥也没变。验证系统能抓到这种情况——然后 agent 自己给工具补上验证钩子。整个过程不需要人插手。所有 agent 写的代码都有 git 审计记录，改坏了能回滚。

### 架构适应度函数

23 个自动化测试，每次 CI 跑。不测"代码能不能编译"——测"架构还在不在"：非集规则有效吗？agent 越权了吗？上下文效率怎样？输出格式合规吗？

---

## 记忆

**情景记忆** — 每次任务都记录：用了什么工具、对象怎么变、非集规则触发没、成功还是失败。SQLite WAL，版本化迁移。

**事件溯源** — 11 种事件类型覆盖整个生命周期。只追加不修改。定期快照。可完整重放。

**语义记忆** — LLM 驱动整合，从 episode 里提炼偏好、事实、模式，带可信度评分。

**对象历史** — `get_object_history("file://src/main.py")` 返回这个文件在所有任务中的完整变更时间线。

---

## 智能

**能力路由** — 按模型×任务类型跟踪成功率。数据库迁移任务 haiku 老挂？自动升级到 sonnet。新任务类型没数据时回退到成本路由。基于 Karpathy 的 Jagged Frontier 理论。

**模式挖掘** — 跨任务分析：同类错误反复出现 → 提规则，同类纠正反复出现 → 提技能，同类失败反复出现 → 提计划模板。Agent 提议，你来决定。

---

## 技能网络

知识不会随着一次任务结束而消失。成功任务会被蒸馏成技能，下次自动复用：

```
任务成功 → LLM 提取方法 → 存为 Skill → 以后类似任务自动注入
```

技能像社交网络一样运作：**创建 → 使用 → 评分 → 迭代 → 退役 → 合并**。每次使用带一个 +1/-1 评分和书面理由——理由比评分更重要，因为它准确告诉后面的 agent "到底哪里坏了"。分数跌破 -3 自动退役。雷同技能自动合并，反馈合并计算。保存前 PII 双重门控。

---

## 浏览器自动化

裸 CDP 协议，零框架抽象：

```
capture_screenshot() → 读像素 → click_at_xy(x, y) → capture_screenshot() → 验证
```

坐标点击优先。合成器级别的事件穿透 iframe、Shadow DOM、跨域边界。刻意压制 Playwright 的"先定位再点击"肌肉记忆——对视觉模型来说，像素比选择器可靠得多。

后台挂着 CDP 守护进程，LLM 思考期间保持 WebSocket 连接不丢。agent 可以在运行中通过工具自愈系统扩展自己的浏览器能力。

---

## 命令

```bash
# Provider 管理
therain2020-agent provider add <名称> --adapter anthropic|openai|deepseek|custom ...
therain2020-agent provider list
therain2020-agent provider test <名称>

# 添加能力
therain2020-agent add discover          # 扫描本地
therain2020-agent add from-claude-code  # 从 Claude Code 导入
therain2020-agent add from-cursor       # 从 Cursor 导入
therain2020-agent add from-codex        # 从 Codex 导入
therain2020-agent add from-gemini       # 从 Gemini 导入
therain2020-agent add skill <路径>      # 注册 skill
therain2020-agent add mcp <命令>        # 注册 MCP server
therain2020-agent add search <关键词>   # GitHub + MCP Registry 搜索
therain2020-agent add list              # 查看已添加
therain2020-agent add remove <名称>     # 移除

# 发布
therain2020-agent publish init <名称>
therain2020-agent publish build
therain2020-agent publish verify

# 运行
therain2020-agent run "修一下登录页的样式"
therain2020-agent run "重构数据库连接池" --mode goal

# 查看
therain2020-agent info tools
therain2020-agent info dont-do
therain2020-agent info config
```

### 支持的导入格式

| 来源 | 能读什么 | 生成什么 |
|------|---------|---------|
| Claude Code | SKILL.md, 插件, settings.json, CLAUDE.md | tool.md, role.md, dont-do 规则 |
| Cursor | .cursor/rules/, mcp.json | tool.md, 行为规则 |
| Gemini CLI | config.json, extensions/ | tool.md (MCP) |
| Codex CLI | config.yaml, plugins/ | tool.md (MCP) |
| MCP | stdio / SSE / HTTP | tool.md (runtime=mcp) |
| Aider | CONVENTIONS.md | 行为规则 |
| 自定义 | tool.md + Python 脚本 | 原生，无需转换 |

---

## 架构

每个模块都映射到一个 Linux 内核概念：

| 模块 | 内核类比 | 一句话职责 |
|------|---------|-----------|
| `core.py` | 进程调度器 | 事件循环，上下文增强，能力记录 |
| `objects.py` | VFS inode + xattrs | Ontology 对象模型 |
| `role.py` | seccomp | 结构化角色，约束/动作生成 |
| `dont_do.py` | iptables | Hook 规则引擎，路径感知匹配 |
| `correction.py` | auditd | 用户反馈→规则闭环 |
| `events.py` | journald | 11 种事件类型 |
| `event_store.py` | ext4 journal | 只追加日志，快照，进程内 pub/sub |
| `memory.py` | ext4 WAL | 情景+语义记忆，FTS5 检索 |
| `consolidation.py` | kswapd | LLM 驱动的记忆整合 |
| `pattern_miner.py` | KSM | 跨任务模式发现 |
| `memory_migrations.py` | Alembic | 版本化 schema 迁移 |
| `prompt.py` | ELF loader | prompt 组装+ontology 上下文注入 |
| `context.py` | MMU | LRU 上下文窗口管理 |
| `output_format.py` | syslog | 引用格式，渐进披露 |
| `providers/pool.py` | RAID 1 | 故障转移+熔断 |
| `providers/router.py` | cpufreq + NUMA | 成本+能力感知路由 |
| `providers/capability.py` | CPU affinity | 锯齿状能力画像 |
| `tools/registry.py` | udev | 工具注册和按对象类型查找 |
| `tools/executor.py` | execve | 工具执行、凭据注入、验证钩子 |
| `tools/evolution.py` | kpatch | 运行时工具热修补，git 版本控制 |
| `tools/editor.py` | ptrace | agent 工具编辑接口 |
| `tools/supervisor.py` | systemd | MCP 进程管理 |
| `tools/browser/` | kthread | CDP 守护进程，截图优先，坐标点击 |
| `skills/` | ld.so.cache | 技能社交网络，PII 门控，自动退役 |
| `security/` | LSM + keyring | 凭据守卫，prompt 注入防御 |

设计文档 30 篇，方案变体 80+，OS 类比映射 119 个。[飞书知识库](https://ycn21rm70xup.feishu.cn/wiki/space/7644823612574141651)。

---

## 测试

```bash
pytest tests/ -v    # 302 个通过，含 23 个架构适应度函数
```

---

## License

MIT
