# therain2020-agent

The **rain2020 Agent** — a self-healing, self-evolving AI agent for software engineering.

Based on the Claude Code architecture and radically transformed to support:

- **Self-healing (自愈)**: Automatically detects bugs in its own tools/skills/plugins, diagnoses root causes, modifies its own TypeScript source code, verifies fixes, and hot-applies them.
- **Self-evolution (自进化)**: Discovers capability gaps, designs new tools/skills, writes their implementation, and installs them at runtime — all without human intervention.

## Architecture

```
therain2020-agent/
├── src/                          # Agent source code (TypeScript, Bun)
│   ├── main.tsx                  # Entrypoint — Commander.js CLI + React/Ink
│   ├── tools/                    # Tool implementations
│   │   ├── SelfHealTool.ts       # Self-healing trigger
│   │   └── EvolveTool.ts         # Self-evolution trigger
│   ├── services/
│   │   ├── SelfModService/       # Central self-modification engine
│   │   ├── DynamicToolRegistry.ts # Runtime tool loading
│   │   ├── EvolvedPromptStore.ts # System prompt evolution
│   │   └── CapabilityGapDetector.ts # Gap detection + auto-trigger
│   ├── commands/
│   │   ├── evolve-undo.ts        # /evolve-undo
│   │   └── evolution-status.ts   # /evolution-status
│   └── ...
└── .claude/                      # Claude Code config
```

## Key Capabilities

### Self-Healing
Bug detected → Diagnose root cause → SelfModify mode → Fix source code → Verify → Apply (Tier 1/2) or Rebuild+Restart (Tier 3) → Async verification → FAIL? → Auto rollback

### Self-Evolution
Capability gap detected → Plan agent design → Generate code → Tier 1: Skill (instant) | Tier 2: Dynamic Tool (runtime) | Tier 3: Core engine (rebuild)

### Three Evolution Tiers

| Tier | Type | Load Time | Rebuild |
|------|------|-----------|---------|
| 1 | Skill (SKILL.md) | Instant | No |
| 2 | Dynamic Tool (.ts) | Next query | No |
| 3 | Core Engine | After rebuild | Yes |

## Tech Stack

- **Runtime**: [Bun](https://bun.sh)
- **Language**: TypeScript
- **Terminal UI**: React + [Ink](https://github.com/vadimdemedes/ink)
- **CLI**: Commander.js
- **Schema**: Zod v4

## Getting Started

```bash
curl -fsSL https://bun.sh/install | bash
bun run src/main.tsx
```

## Commands

- `/evolve-undo` — Rollback the last self-modification
- `/evolution-status` — View heal/evolve history and open capability gaps

## License

MIT
