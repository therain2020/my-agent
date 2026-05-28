# therain2020-agent

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-302%20passed-brightgreen.svg)](tests/)
[![PyPI](https://img.shields.io/pypi/v/therain2020-agent.svg)](https://pypi.org/project/therain2020-agent/)

[中文文档](README.zh-CN.md)

A closed-loop agent framework that actually checks its work — observes before acting, blocks dangerous operations at runtime, verifies results with evidence, and learns from every mistake.

---

## What's different

Most agent frameworks send a prompt, execute whatever the LLM says, and call it done. This one runs a reconciliation loop:

- **Observes object state before acting.** Knows what a file looks like before writing to it. Diffs before and after.
- **Blocks at runtime, not in prompts.** Dont-do rules fire at three hook points. Path-aware context enrichment means rules actually match real paths — not just pattern names.
- **Verifies with evidence.** Re-observes after acting. Compares acceptance criteria against what actually changed. Returns confidence, not guesswork.
- **Remembers as events.** Every observation, tool call, correction, and verification is an immutable event. Full replay. Full audit trail.
- **Routes by capability, not just cost.** Tracks per-model success rates per task type. Knows when to upgrade from haiku to sonnet for database work.
- **Discovers its own patterns.** Mines past episodes for recurring errors, corrections, and failures. Proposes rules. You approve.
- **Heals its own tools.** When a tool is missing or silent-failing, the agent reads existing code, writes the missing function, and retries. Self-healing with git version control.
- **Builds a skill network.** Successful episodes are distilled into reusable skills. Skills get rated, iterated, retired when stale, and merged when duplicate. PII-gated before sharing.
- **Compresses context safely.** LLM-driven semantic compression that never touches procedural instructions — prevents the "where did the rules go" class of bugs.
- **Controls a browser directly.** Raw CDP, no Playwright wrapper. Screenshot-first interaction, coordinate-click default. Agent extends its own browser helpers at runtime.

---

## Install

```bash
pip install therain2020-agent
```

## Quick start

```bash
# Add a provider
therain2020-agent provider add qwen --adapter custom \
  --api-key-env ALI_TONGYI_KEY \
  --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 \
  --model qwen-plus

# Discover tools
therain2020-agent add discover

# Run a task
therain2020-agent run "add rate limiting to the login endpoint"
```

---

## How it works

### The loop

```
Observe → Analyze → Plan → Execute → Verify → (retry, max 3)
```

Not a linear prompt→response chain. The agent keeps going until the goal is verified or the loop exhausts. Think Kubernetes reconciliation, not shell script.

### Two modes

| Mode | Best for | How it verifies |
|------|----------|----------------|
| **TODO** | Tasks with clear acceptance criteria | Analyzes clarity, asks if criteria are missing, checks each one against evidence |
| **Goal** | Open-ended objectives | Re-observes objects, computes before/after diff, returns confidence score |

### Ontology object model

The agent doesn't see raw strings. Each object carries four layers of context — what Palantir calls the Data-Logic-Actions triad plus Relations:

- **State** — current snapshot (size, branch, exists, hash)
- **Constraints** — what you can't do to this object ("no hardcoded keys", "don't write to /etc")
- **Actions** — what you can do, with preconditions and side effects
- **Relations** — what this object connects to (tested by, imported by, depends on)

This full context is injected into every planning prompt. The LLM sees "file X, size 100, constraint: no system paths, related to test_auth.py, can read_file and write_file" — not just "file X".

---

## Safety

### Dont-Do rules

Rules fire at runtime, not as prompt suggestions. Three hook points:

```
PLAN        → filter dangerous steps before execution
PRE_ACTION  → block tool calls with bad parameters
POST_ACTION → audit results for suspicious output
```

The agent enriches context before checking — extracts paths from params, sets `path_in_restricted` and `path_matches` automatically. A rule that says "block writes to /etc" actually catches `/etc/passwd`.

### Trust boundaries (STRIDE)

Every tool call crosses a trust boundary. Each STRIDE dimension has a mitigation:

| Threat | How it's caught |
|--------|----------------|
| Spoofing | Role + DontDoEngine verify every call |
| Tampering | Path-aware parameter inspection at PRE_ACTION |
| Repudiation | Event Sourcing provides full audit trail |
| Info leaks | POST_ACTION result filtering + credential guard |
| DoS | max_iterations cap + interrupt handler |
| Elevation | Role whitelist — tools outside the role can't be called |

### Corrections

User spots a problem? Drop a YAML in `corrections/`. The agent generates a dont-do rule, persists it, and replans. The same mistake never happens twice.

### Self-healing tools

Tools don't just execute — they evolve. When the agent hits a missing capability or a silent failure:

```
Tool fails → reads existing code → writes missing function → commits via git → retries
```

The verification system catches silent failures (tool reports "OK" but state didn't change). When detected, the agent writes a verify hook, attaches it to the tool, and retries. No developer intervention needed — the same healing pattern that powers Browser Harness.

All agent-written code is git-committed with audit trail. Broken edits can be rolled back.

### Architectural fitness functions

23 automated tests verify architectural properties every CI run — dont-do effectiveness, role compliance, context efficiency, output format. Not "does it compile" — "does the architecture hold."

---

## Memory

**Episodic** — every task recorded with tools used, objects changed, rules fired. SQLite WAL with versioned migrations.

**Event Sourcing** — 11 event types across the full lifecycle. Append-only log. Periodic snapshots. Full replay.

**Semantic** — LLM-driven consolidation distills episodes into preferences, facts, and patterns with confidence scores.

**Object history** — `get_object_history("file://src/main.py")` returns the complete change timeline across all episodes.

---

## Intelligence

**Capability routing** — per-model, per-task-type success tracking. Database migration on haiku keeps failing at 60%? The router upgrades to sonnet automatically. New task types fall back to cost-based routing. Based on Karpathy's Jagged Frontier.

**Pattern mining** — mines past episodes for clusters: recurring errors → rule proposals, repeated corrections → skill proposals, common failures → plan hints. Agent proposes. Human decides (Taste principle).

---

## Skills Network

Knowledge doesn't die with the episode. Successful tasks are distilled into reusable skills:

```
Episode succeeds → LLM extracts approach → saves as Skill → future tasks auto-inject matching skills
```

Skills follow a social network lifecycle: **create → consume → rate → iterate → retire → merge**. Each use gets a +1 or -1 rating with a written reason — the reason matters more than the rating because it tells future agents exactly what broke. Score drops below -3? Auto-retired. Near-duplicate? Merged, feedback combined. PII gated before any skill is saved.

---

## Browser Automation

Raw Chrome DevTools Protocol, zero framework abstraction:

```
capture_screenshot() → read pixels → click_at_xy(x, y) → capture_screenshot() → verify
```

Coordinate-click default. Compositor-level events pierce through iframes, shadow DOM, and cross-origin boundaries. Playwright's "locate first, then click" reflex is explicitly suppressed — for vision-capable LLMs, pixels are more reliable than selectors.

A persistent CDP daemon keeps the WebSocket alive across LLM cognitive pauses. The agent extends its own browser helpers at runtime via the same self-healing system.

---

## Commands

| Command | What it does |
|--------|-------------|
| `provider add` | Register an LLM provider (Anthropic, OpenAI, DeepSeek, custom) |
| `provider list / test` | List or test registered providers |
| `add discover` | Scan local machine for tools, skills, and MCP servers |
| `add from-claude-code` | Import from Claude Code (skills, settings, plugins) |
| `add from-cursor / from-codex / from-gemini` | Import from other coding agents |
| `add skill <path>` | Register a skill by path |
| `add mcp <command>` | Register an MCP server |
| `add search <keyword>` | Search GitHub + MCP Registry for tools |
| `publish init / build / verify` | Package and publish tools |
| `run "task"` | Execute in TODO mode |
| `run "goal" --mode goal` | Execute in Goal mode |
| `info tools / dont-do / config` | Inspect current state |

---

## Architecture

Every module maps to a Linux kernel concept:

| Module | Kernel analogy |
|--------|---------------|
| `core.py` | Process scheduler — event loop, context enrichment, capability recording |
| `objects.py` | VFS inode + xattrs — Ontology object model (Data+Logic+Actions+Relations) |
| `role.py` | seccomp — structured role with constraint/action generation |
| `dont_do.py` | iptables — hook-based rule engine, path-aware matching |
| `correction.py` | auditd — user feedback → rule closed loop |
| `events.py` | journald — 11 event types for event sourcing |
| `event_store.py` | ext4 journal — append-only log, snapshots, in-process pub/sub |
| `memory.py` | ext4 WAL — episodic + semantic, FTS5 search |
| `consolidation.py` | kswapd — LLM-driven episodic→semantic distillation |
| `pattern_miner.py` | KSM — cross-episode pattern discovery |
| `memory_migrations.py` | Alembic — versioned schema migrations |
| `prompt.py` | ELF loader — prompt assembly + ontology context injection |
| `context.py` | MMU — LRU context window management |
| `output_format.py` | syslog — citation rules, progressive disclosure |
| `providers/pool.py` | RAID 1 — failover with circuit breaker |
| `providers/router.py` | cpufreq + NUMA — cost + capability-aware routing |
| `providers/capability.py` | CPU affinity — Jagged Frontier per-task profiling |
| `tools/registry.py` | udev — tool registration, lookup by object type |
| `tools/executor.py` | execve — execution, credential injection, verification hooks |
| `tools/evolution.py` | kpatch — runtime tool patching, git version control |
| `tools/editor.py` | ptrace — agent tool editing interface |
| `tools/supervisor.py` | systemd — MCP process lifecycle |
| `tools/browser/` | kthread — CDP daemon, screenshot-first, coordinate-click default |
| `skills/` | ld.so.cache — social learning network, PII gating, auto-retirement |
| `security/` | LSM + keyring — credential guard, prompt injection defense |

30 design documents, 80+ solution variants, 119 OS analogy mappings. [Feishu Wiki](https://ycn21rm70xup.feishu.cn/wiki/space/7644823612574141651).

---

## Tests

```bash
pytest tests/ -v    # 302 passed, including 23 architectural fitness functions
```

---

## License

MIT
