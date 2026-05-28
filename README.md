# therain2020-agent

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-247%20passed-brightgreen.svg)](tests/)
[![PyPI](https://img.shields.io/pypi/v/therain2020-agent.svg)](https://pypi.org/project/therain2020-agent/)

[中文](README.zh-CN.md)

A closed-loop AI agent framework. Structured observation, runtime safety enforcement, correction-driven learning, event-sourced memory, capability-aware routing, and self-teaching pattern mining — with your own API key.

---

## Why

Most agent frameworks are prompt-wrappers. They ask an LLM what to do, hope it does the right thing, and call it done.

This one doesn't.

- **Observes** object states before acting. Knows what changed.
- **Blocks** dangerous operations at runtime — not as a prompt request, as enforced rules. Path-aware context enrichment closes the gap between rule definitions and real-world execution.
- **Learns** from corrections. User says "don't do that" once, it never happens again. Agent also **self-teaches** — discovers recurring patterns across episodes and proposes rules autonomously.
- **Verifies** results against acceptance criteria with evidence. Re-observes object states, computes diffs. Not "YES/NO" guessing.
- **Remembers** with event sourcing. Every observation, tool call, correction, and verification is an immutable event. Full audit trail. Replay any task from start to finish.

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
| **TODO** | Task list with acceptance criteria | Analyzes TODO clarity, asks user if criteria missing, checks each criterion against execution evidence |
| **Goal** | Open-ended objectives | Re-observes object states, diffs before/after, returns confidence score with explanation |

### Ontology object model (Data + Logic + Actions + Relations)

The agent doesn't just see raw data. Each object carries:

- **Data** — current state snapshot (size, branch, exists)
- **Logic** — constraints that govern valid operations ("no hardcoded keys", "don't write to system paths")
- **Actions** — available operations with preconditions and side effects
- **Relations** — links to other objects (tested_by, imports, depends_on)

This is injected into the planning prompt. The LLM sees the full picture — not just "file X is size 100", but "file X has these constraints, relates to these other files, and you can use these specific tools on it."

### Event Sourcing memory

Every agent action is an immutable event appended to a SQLite WAL log:

```
GoalStarted → ObjectObserved → PlanGenerated → ToolCalled → ToolResult
→ CorrectionApplied → RuleAdded → GoalVerified → GoalCompleted
```

11 event types. Full replay. Periodic snapshots every 50 events. Safety-critical events (rule changes) are synchronously visible; observation events are eventually consistent.

### Role-based observation

Roles define *what* to observe and *how*. Each role declares focus objects with observation tools, manipulation tools, prohibited operations, and behavior rules. Observation is targeted — the agent only calls relevant tools, not everything in its toolbox.

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
      path_in_restricted: true
    action: REJECT
    message: "Deleting system files is forbidden"
```

Rules fire at **runtime** at three hook points: `PLAN` (filter steps before execution), `PRE_ACTION` (block tool calls), `POST_ACTION` (audit results). Context is **path-enriched** — the agent extracts path from params and sets `path_in_restricted`/`path_matches` automatically. Prompt injection is layer 1. Runtime enforcement is layer 2. Credential guard is layer 3.

### Trust Boundaries (STRIDE)

Every tool call crosses a trust boundary (LLM → Tool Executor). The security model maps to STRIDE threat modeling:

| Threat | Mitigation |
|--------|-----------|
| Spoofing | Role + DontDoEngine dual verification |
| Tampering | PRE_ACTION path-aware parameter checks |
| Repudiation | Event Sourcing full audit trail |
| Info Disclosure | POST_ACTION result filtering + output sanitization |
| Denial of Service | max_iterations limit + InterruptHandler |
| Elevation | Role.get_manipulation_tools() whitelist |

### Correction → rule closed loop

User spots a problem mid-execution? Drop a YAML file into `corrections/`. The agent generates a dont-do rule via LLM, persists it, replans with the new constraint. It never makes the same mistake twice.

### Architectural Fitness Functions

23 automated tests verify architectural characteristics every CI run — not just "does the code compile", but "are dont-do rules effective?", "does the agent stay within its role?", "is context usage efficient?".

---

## Intelligence

### Capability-aware routing

Tracks per-model, per-task-type success rates. When you ask for a "database migration", the router knows haiku succeeds 60% of the time on database tasks — it routes to sonnet automatically. Cold start (new task type) falls back to cost-based routing. Based on Karpathy's "Jagged Frontier" concept.

### Self-teaching pattern mining

The agent discovers patterns across episodes:

- **Error clusters** — same error across same task type → rule proposal
- **Correction clusters** — same correction repeated → skill proposal
- **Failure clusters** — same verify failure → plan template hint

Agent **proposes**. Human **approves** (Taste principle).

---

## Memory

### Episodic memory

Every task run is recorded: tools used, objects changed, dont-do rules fired, success/failure. SQLite WAL with versioned schema migrations.

### Semantic memory

LLM-driven consolidation daemon (kswapd + LFS cleaner) distills episodes into reusable knowledge — preferences, facts, patterns — with confidence scoring.

### Object state history

`get_object_history("file://src/main.py")` returns the complete change timeline for any object across all episodes.

### Event replay

`event_store.replay_task(task_id)` reconstructs the full execution timeline — every observation, every tool call, every verification — in insertion order.

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
| `agent/core.py` | Process scheduler | TODO/Goal event loop, dont-do enrichment, capability recording |
| `agent/objects.py` | VFS inode + xattrs | Ontology object model (Data+Logic+Actions+Relations) |
| `agent/role.py` | seccomp profile | Structured role with focus objects, constraint/action generation |
| `agent/dont_do.py` | iptables netfilter | Hook-based rule engine, first-match semantics |
| `agent/correction.py` | auditd + rule gen | User feedback → dont-do rule closed loop |
| `agent/events.py` | journald | 11 event types for event-sourced memory |
| `agent/event_store.py` | ext4 journal | Append-only event log, snapshot, in-process pub/sub |
| `agent/memory.py` | ext4 journal (WAL) | Episodic + semantic with FTS5 search |
| `agent/consolidation.py` | kswapd + LFS cleaner | LLM-driven episodic→semantic distillation |
| `agent/pattern_miner.py` | KSM (same-page merging) | Cross-episode pattern discovery, agent self-teaching |
| `agent/memory_migrations.py` | Alembic-style | Versioned schema migration tracking |
| `agent/prompt.py` | ELF loader | Structured prompt assembly + ontology context injection |
| `agent/context.py` | MMU + page replacement | LRU context window management |
| `agent/output_format.py` | syslog format enforcer | Citation rules, progressive disclosure, action reports |
| `agent/providers/pool.py` | RAID 1 + multipath | Provider failover with circuit breaker |
| `agent/providers/router.py` | ondemand cpufreq + NUMA | Cost + capability-aware model routing |
| `agent/providers/capability.py` | CPU affinity | Jagged Frontier model profiling per task type |
| `agent/tools/supervisor.py` | systemd | MCP process lifecycle management |
| `agent/tools/registry.py` | udev | Tool registration, lookup by object type |
| `agent/tools/adapters/` | filesystem drivers | 9 ecosystem adapters (Claude, Cursor, Gemini, etc.) |
| `agent/security/` | LSM + keyring | Credential guard, prompt injection defense |

Full design documents at `D:\GitHub\agent-design\temp\`. 30 design topics, 80+ solution variants, 119 OS analogy mappings.

---

## Tests

```bash
pytest tests/ -v    # 247 passed
```

Including 23 architectural Fitness Functions (plan completeness, dont-do effectiveness with STRIDE, role compliance, context efficiency, output format compliance).

---

## License

MIT
