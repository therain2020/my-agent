# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is the leaked source code of **Claude Code** — Anthropic's official CLI tool for interacting with Claude in the terminal. Leaked 2026-03-31 via a `.map` file in the npm registry.

- **Language**: TypeScript (strict)
- **Runtime**: [Bun](https://bun.sh)
- **Terminal UI**: React + [Ink](https://github.com/vadimdemedes/ink)
- **CLI Parsing**: Commander.js (`@commander-js/extra-typings`)
- **Schema Validation**: Zod v4 (`zod/v4`)
- **API**: Anthropic SDK (`@anthropic-ai/sdk`)
- **Code Search**: ripgrep (via GrepTool)
- **Feature Flags**: GrowthBook + Bun bundler dead-code elimination
- **Telemetry**: OpenTelemetry + gRPC

## Project Structure

```
src/
├── main.tsx                 # Entrypoint — Commander.js + React/Ink renderer + startup prefetch
├── commands.ts              # Slash command registry
├── tools.ts                 # Tool registry
├── Tool.ts                  # Tool type definitions (~29K lines)
├── QueryEngine.ts           # Core LLM API caller (~46K lines) — streaming, tool-call loops, retry
├── context.ts               # System/user context collection (CLAUDE.md, git status, env)
├── cost-tracker.ts          # Token cost tracking
├── Task.ts                  # Task type definitions
├── tasks.ts                 # Task management
│
├── commands/                # Slash command implementations (~80 subdirectories)
├── tools/                   # Agent tool implementations (~40 subdirectories)
├── components/              # Ink UI components (~140 files)
├── hooks/                   # React hooks (toolPermission, notifs)
├── services/                # External service integrations
│   ├── api/                 # Anthropic API client, file API, bootstrap
│   ├── mcp/                 # MCP server connection and management
│   ├── oauth/               # OAuth 2.0 authentication
│   ├── lsp/                 # Language Server Protocol manager
│   ├── analytics/           # GrowthBook feature flags and analytics
│   ├── plugins/             # Plugin loader
│   ├── compact/             # Conversation context compression
│   ├── policyLimits/        # Organization policy limits
│   └── remoteManagedSettings/ # Remote managed settings
│
├── bridge/                  # IDE integration (VS Code, JetBrains)
├── coordinator/             # Multi-agent coordinator
├── plugins/                 # Plugin system
├── skills/                  # Skill system (bundled + user skills)
├── state/                   # AppStateStore, AppState, selectors
├── entrypoints/             # Initialization logic (init.ts, cli.tsx, mcp.ts)
├── types/                   # Shared TypeScript types
├── utils/                   # Utility functions
├── constants/               # Constants (products, prompts, OAauth, betas, etc.)
├── schemas/                 # Config schemas (Zod)
├── migrations/              # Config migrations
├── keybindings/             # Keybinding configuration
├── vim/                     # Vim mode
├── voice/                   # Voice input
├── remote/                  # Remote sessions
├── server/                  # Server mode
├── memdir/                  # Persistent memory directory
├── buddy/                   # Companion sprite (easter egg)
├── ink/                     # Ink renderer wrapper
├── outputStyles/            # Output styling
├── query/                   # Query pipeline
├── cli/                     # CLI transports (SSE, WebSocket, CCR), I/O
└── upstreamproxy/           # Proxy configuration
```

## Core Architecture

### Tool System

Every tool implements the `Tool` interface (`Tool.ts:362`). Each tool lives in its own directory under `src/tools/<Name>/` and exports an object with:

- `name` — unique identifier
- `call(input, context, canUseTool)` — execution logic
- `description(input, options)` — dynamic description for the model
- `inputSchema` — Zod schema for input validation
- `isEnabled()` — feature-gate check
- `isReadOnly(input)` — permission classification
- `isConcurrencySafe(input)` — whether parallel calls are safe
- `isDestructive?(input)` — marks irreversible operations
- `validateInput?(input, context)` — context-aware validation
- `interruptBehavior?()` — `'cancel'` or `'block'` for new messages during execution
- `mcpInfo?` — present on all MCP-proxied tools

Tools are registered in `tools.ts` with conditional imports gated by `feature()` (Bun dead-code elimination) or `process.env.USER_TYPE === 'ant'`.

### Command System

Slash commands are UI-level features invoked with `/` prefix. Each command is a module with `Command` type (`types/command.ts`). Registered in `commands.ts`, executed via `commands.handleCommand()`.

### Query Engine (`QueryEngine.ts`)

The central LLM interaction loop. Handles:
- Streaming responses from Anthropic API
- Tool-call detection and execution loop
- Thinking mode (extended reasoning)
- Retry logic for transient API errors
- Token counting and cost tracking
- System/user context assembly

### State Management

- `state/AppState.tsx` — defines the full application state type
- `state/AppStateStore.ts` — singleton store
- `state/selectors.ts` — memoized selectors
- `state/onChangeAppState.ts` — subscribe to state changes
- State flows through `ToolUseContext.getAppState()` / `setAppState()`

### Services Layer

- **MCP** — connects to Model Context Protocol servers via stdio/SSE/HTTP/WS. Each MCP tool is wrapped as a native `Tool` via `mcp__server__tool` naming convention
- **OAuth** — OAuth 2.0 flow for API authentication
- **LSP** — Language Server Protocol integration for code intelligence
- **Analytics** — GrowthBook SDK for feature flags, event logging
- **Compact** — context compression when conversation exceeds limits

### Bridge System

Bidirectional communication between IDE extensions (VS Code, JetBrains) and the CLI. Key files: `bridgeMain.ts`, `replBridge.ts`, `bridgeMessaging.ts`, `sessionRunner.ts`.

### Permission System

`hooks/toolPermission/` — checks permissions per tool invocation. Configurable modes: `default`, `plan`, `bypassPermissions`, `auto`, `acceptEdits`. Each tool's `validateInput()` and `isReadOnly()` feed into this system.

### Feature Flags

Bun's `bun:bundle` feature flags enable dead-code elimination:

```typescript
import { feature } from 'bun:bundle'

const monitorTool = feature('MONITOR_TOOL')
  ? require('./tools/MonitorTool/MonitorTool.js').MonitorTool
  : null
```

Notable flags: `PROACTIVE`, `KAIROS`, `BRIDGE_MODE`, `DAEMON`, `VOICE_MODE`, `AGENT_TRIGGERS`, `MONITOR_TOOL`, `COORDINATOR_MODE`.

### Agent Swarms / Coordinator

`AgentTool` spawns sub-agents for parallel work. `coordinator/coordinatorMode.ts` handles multi-agent orchestration. `TeamCreateTool` / `TeamDeleteTool` manage team-level parallelism.

### Skill System

Reusable workflows in `skills/` executed through `SkillTool`. Skills are loaded from `bundledSkills.ts` and `loadSkillsDir.ts`. Users add custom skills at `~/.claude/skills/<name>/SKILL.md`.

## Key Design Patterns

### Startup Prefetch

`main.tsx` fires side-effects before heavy imports: MDM settings read, keychain prefetch, GrowthBook init all run in parallel during module evaluation.

### Lazy Loading

Heavy modules (~400KB OpenTelemetry, ~700KB gRPC) are loaded via dynamic `import()` only when needed. `require()` is used for conditional imports gated by feature flags.

### Tool Result Persistence

When tool output exceeds `maxResultSizeChars`, results are saved to disk and a preview with file path is sent to the model instead. Prevents context window bloat.

### Circular Dependency Handling

Lazy `require()` patterns break import cycles (e.g., `teammate.ts → AppState.tsx → main.tsx`).

## Code Conventions

- `src/` uses `import { ... } from './relative/path.js'` with explicit `.js` extensions even for `.tsx` files
- Zod v4 schemas use `lazySchema()` wrapper for recursive/circular schema definitions
- `// biome-ignore-all assist/source/organizeImports` marks files with intentional import ordering
- `// eslint-disable-next-line custom-rules/no-top-level-side-effects` for startup side-effects
- `ANT-ONLY` comments mark internal Anthropic-only features gated by `USER_TYPE === 'ant'`
- Use `process.env.NODE_ENV === 'test'` guards to skip git/filesystem operations during tests
