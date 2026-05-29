# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is **therain2020-agent** — a self-healing, self-evolving AI agent based on Claude Code architecture.

- **Language**: TypeScript (strict)
- **Runtime**: [Bun](https://bun.sh)
- **Terminal UI**: React + [Ink](https://github.com/vadimdemedes/ink)
- **CLI Parsing**: Commander.js (`@commander-js/extra-typings`)
- **Schema Validation**: Zod v4 (`zod/v4`)
- **API**: Anthropic SDK (`@anthropic-ai/sdk`)

## Core Architecture

### Self-Modification System

The agent CAN modify its own source code. This is the foundation of self-healing and self-evolution.

- `src/services/SelfModService/SelfModService.ts` — Central engine: permission mode switching, heal/evolve orchestration, journal logging
- `src/services/SelfModService/Sandbox.ts` — Safe modification: checkpoint, worktree, rebuild, rollback
- `src/services/SelfModService/EvolutionLoop.ts` — Evolution pipeline: gap → design → generate → integrate → verify
- `src/services/DynamicToolRegistry.ts` — Runtime tool loading from `~/.claude/dynamic-tools/*.ts`
- `src/services/EvolvedPromptStore.ts` — System prompt evolution storage
- `src/services/CapabilityGapDetector.ts` — Gap detection + auto-trigger

### Permission System Changes

Modified from original Claude Code to support self-modification:

- `src/utils/permissions/filesystem.ts` — `.claude/` removed from DANGEROUS_DIRECTORIES, added self-modification bypass
- `src/types/permissions.ts` — Added `selfModify` PermissionMode

### Tool System

- `src/Tool.ts` — Tool type definitions
- `src/tools.ts` — Tool registry, `assembleToolPool()` now includes dynamic tools
- `src/tools/SelfHealTool.ts` — Agent calls this to trigger self-healing
- `src/tools/EvolveTool.ts` — Agent calls this to trigger self-evolution

### Evolution Tiers

| Tier | Target | Mechanism |
|------|--------|-----------|
| 1 | `.claude/skills/{name}/SKILL.md` | Auto-discovered by `discoverSkillDirsForPaths()` |
| 2 | `~/.claude/dynamic-tools/{name}.ts` | Loaded by `DynamicToolRegistry.import()` |
| 3 | Core engine (`src/tools/`, `src/services/`) | Worktree isolate → edit → build → restart |

### Key Files Modified from Original

1. `src/tools.ts` — DynamicRegistry integration in `assembleToolPool()`
2. `src/utils/permissions/filesystem.ts` — Self-modification permission bypass
3. `src/types/permissions.ts` — `selfModify` PermissionMode
4. `src/constants/prompts.ts` — SELF_MODIFY_CAPABILITY system prompt section
5. `src/memdir/memoryTypes.ts` — `selfheal` and `evolution` memory types

## Code Conventions

- `.js` extensions on imports even for `.tsx` files
- `buildTool()` factory for standard tool construction
- `systemPromptSection()` for system prompt extensions
- File-based storage in `~/.claude/` for persistence
