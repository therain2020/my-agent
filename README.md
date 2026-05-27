# therain2020-agent

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-170%20passed-brightgreen.svg)](tests/)
[![PyPI](https://img.shields.io/pypi/v/therain2020-agent.svg)](https://pypi.org/project/therain2020-agent/)

[中文](README.zh-CN.md)

A closed-loop AI agent framework. Structured observation, runtime safety enforcement, correction-driven learning, evidence-based verification — with your own API key.

---

## Why

Most agent frameworks are prompt-wrappers. They ask an LLM what to do, hope it does the right thing, and call it done.

This one doesn't.

- **Observes** object states before acting. Knows what changed.
- **Blocks** dangerous operations at runtime — not as a prompt request, as enforced rules.
- **Learns** from corrections. User says "don't do that" once, it never happens again.
- **Verifies** results against acceptance criteria with evidence. Not "YES/NO" guessing.

---

## Quick start

```bash
pip install therain2020-agent

therain2020-agent provider add qwen --adapter custom \
  --api-key-env ALI_TONGYI_KEY \
  --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 \
  --model qwen-plus

therain2020-agent add discover
therain2020-agent add from-claude-code
therain2020-agent run "fix the login bug"
```

---

## How it works

### The agent loop

```
Observe → Analyze → Plan → Execute → Verify → (loop, max 3)
```

Not a linear prompt→response chain. A Kubernetes-style reconciliation loop that keeps trying until the goal is met or the loop is exhausted.

### Two execution modes

| Mode | Use when | Verification |
|------|----------|-------------|
| **TODO** | Task list with acceptance criteria | Checks each criterion against execution evidence |
| **Goal** | Open-ended objectives | Re-observes object states, diffs before/after, returns confidence |

### Object model

The agent doesn't just execute commands. It maintains a typed model of what it's working on — files, databases, git repos, services. Each object has a URI, type, and observed state. Before acting, the agent observes the current state. After acting, it observes again. Verification compares the diff.

### Role-based observation

Roles define *what* to observe and *how*. A backend-developer role knows to observe file-system, git-repo, and database objects. Each object type maps to specific observation and manipulation tools. That means observation is targeted — the agent only calls relevant tools, not everything in its toolbox.

---

## Safety

Three layers. Not one.

### Dont-Do rules — iptables-style enforcement

```yaml
rules:
  - id: no-delete-system
    hook: [PRE_ACTION]
    match:
      object: file
      operation: delete_file
    action: REJECT
    message: "Deleting system files is forbidden"
```

Rules fire at **runtime** at three hook points: `PLAN` (filter steps before execution), `PRE_ACTION` (block tool calls), `POST_ACTION` (audit results). Prompt injection is layer 1. Runtime enforcement is layer 2.

### Correction → rule closed loop

User spots a problem mid-execution? Drop a YAML file into `corrections/`. The agent:
1. Parses the correction
2. Generates a dont-do rule via LLM
3. Persists it to the rule directory
4. Replans with the new constraint

It never makes the same mistake twice.

### Credential guard

API keys stay in the agent core. The LLM never sees them. Tool executor injects them at call time. Output is scanned for leaks.

---

## It learns

### Episodic memory

Every task run is recorded: what tools were used, what objects changed, what dont-do rules fired, whether it succeeded. SQLite with WAL, FTS5 full-text search.

### Semantic memory

An LLM-driven consolidation daemon (think kswapd + LFS cleaner) periodically distills episode records into reusable knowledge — preferences, facts, patterns — with confidence scoring. Rule-based fallback when no LLM is available.

### Object state history

`get_object_history("file://src/main.py")` returns the complete change timeline for any object across all episodes. You can trace what happened to a file across days of agent activity.

---

## Output discipline

System-level format constraints enforced in every prompt:

```
<format_rules immutable="true">
  File references: path/to/file:line_number
  Long responses: --- separated (summary → details → full)
  Every function_call must have an <action_report>
</format_rules>
```

Format violations are detected post-hoc and flagged. Not suggestions — immutable rules.

---

## Commands

```bash
# Provider
therain2020-agent provider add <name> --adapter anthropic|openai|deepseek|custom ...
therain2020-agent provider list
therain2020-agent provider test <name>

# Add
therain2020-agent add discover
therain2020-agent add search <keyword>
therain2020-agent add from-claude-code
therain2020-agent add from-cursor
therain2020-agent add from-gemini
therain2020-agent add from-codex
therain2020-agent add skill <path>
therain2020-agent add mcp <command>
therain2020-agent add list
therain2020-agent add remove <name>

# Publish
therain2020-agent publish init <name>
therain2020-agent publish build
therain2020-agent publish verify

# Run
therain2020-agent run "task"
therain2020-agent run "goal" --mode goal

# Info
therain2020-agent info tools
therain2020-agent info dont-do
therain2020-agent info config
```

---

## Supported formats

| Source | Reads | Produces |
|---|---|---|
| Claude Code | SKILL.md, .claude-plugin/, settings.json, CLAUDE.md | tool.md, role.md, dont-do rules |
| Cursor | .cursor/rules/, mcp.json | tool.md, behavior rules |
| Gemini CLI | config.json, extensions/ | tool.md (MCP) |
| Codex CLI | config.yaml, plugins/ | tool.md (MCP) |
| MCP | stdio / SSE / Streamable HTTP | tool.md (runtime=mcp) |
| Aider | CONVENTIONS.md | behavior rules |
| Custom | tool.md + Python script | native, no conversion needed |

---

## Architecture

Every component maps to a Linux kernel concept:

| Module | OS Analogy | What it does |
|--------|-----------|-------------|
| `agent/core.py` | Process scheduler | TODO/Goal event loop, 3-iteration max |
| `agent/objects.py` | VFS inode | Typed object model with state snapshots |
| `agent/role.py` | seccomp profile | Defines what to observe and allow per object type |
| `agent/dont_do.py` | iptables netfilter | Hook-based rule engine, first-match semantics |
| `agent/correction.py` | auditd + rule gen | User feedback → dont-do rule closed loop |
| `agent/memory.py` | ext4 journal (WAL) | Episodic + semantic with FTS5 search |
| `agent/consolidation.py` | kswapd + LFS cleaner | LLM-driven episodic→semantic distillation |
| `agent/prompt.py` | ELF loader | Structured prompt assembly with format enforcement |
| `agent/context.py` | MMU + page replacement | LRU context window management |
| `agent/output_format.py` | syslog format enforcer | Citation rules, progressive disclosure, action reports |
| `agent/providers/pool.py` | RAID 1 + multipath | Provider failover with circuit breaker |
| `agent/providers/router.py` | ondemand cpufreq | Cost-aware model routing |
| `agent/tools/supervisor.py` | systemd | MCP process lifecycle management |
| `agent/tools/registry.py` | udev | Tool registration, lookup by object type |
| `agent/tools/adapters/` | filesystem drivers | 9 ecosystem adapters (Claude, Cursor, Gemini, etc.) |
| `agent/security/` | LSM + keyring | Credential guard, prompt injection defense |

Full design documents at `D:\GitHub\agent-design\temp\`. 30 design topics, 80+ solution variants, 119 OS analogy mappings.

---

## Tests

```bash
pytest tests/ -v    # 170 passed
```

---

## License

MIT
