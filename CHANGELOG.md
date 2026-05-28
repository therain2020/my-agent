# Changelog

## v0.6.1 (2026-05-28)

### Fixed
- Default data paths now use `~/.therain2020-agent/` instead of relative `./memory`, `./tools`, `./dont-do`
- REPL no longer crashes when run from a non-writable directory

## v0.6.0 (2026-05-28)

### Added
- **Interactive REPL** — `therain2020-agent` without arguments starts an interactive session like Claude Code
- Agent stays alive across turns, context persists (memory, skills, tool evolution)
- Streaming progress: live tool execution feedback with ✓/⚠ indicators
- Slash commands: `/help`, `/clear`, `/tools`, `/mode`, `/history`, `/skills`, `/exit`
- Progress callback system (`set_progress_callback` + `_emit_progress`) for streaming UX

### Fixed
- Agent `__init__` provider reference order (accessed before declaration)

## v0.5.0 (2026-05-28)

Browser Harness-inspired optimization: self-healing tools, semantic compression, skills network, browser automation. 302 tests.

### Phase 1 — Self-Healing Tool Runtime + Silent Failure Detection (九-C + 十-A)
- **Tool evolution** — `agent/tools/evolution.py` — kpatch-style runtime patching with git version control, validation gate, rollback
- **Agent tool editor** — `agent/tools/editor.py` — ptrace-style editing surface: add_verify, add_helper, get_edit_history
- **Verification hooks** — `VerificationResult` + `execute_and_verify()` in executor. Agent writes verify functions at runtime when silent failures detected
- **Self-healing loop** — core.py detects ToolNotFoundError/ToolExecutionError → triggers healing prompt → agent writes missing code → auto-reloads
- **Auto-generated verify hooks** — Capability.verify field with auto_generated tracking

### Phase 2 — Semantic Compression + Dual-Mode Scheduler (十一-C + 十三-B)
- **Semantic compressor** — `agent/context_compressor.py` — content type classification (PROCEDURAL/REFERENCE/CONVERSATION/EVIDENCE), never compresses procedural instructions
- **Context safety** — ContextPage.compressible field, Hermes Issue #155 prevention
- **Dual-mode scheduler** — `_select_mode()` classifies tasks as explore or exploit, mode-aware provider selection, fewer iterations for known domains

### Phase 3 — Skills Social Learning Network (十二-C)
- **Skills package** — `agent/skills/` — Skill/SkillFeedback/SkillLevel models, SQLite+FTS5 repository, lifecycle management
- **Skill lifecycle** — create → consume → rate(+1/-1 with reason) → iterate → retire(score < -3) → merge(duplicates)
- **PII gating** — Rule-based patterns + LLM double-check before saving skills
- **Auto-extraction** — `extract_skill_from_episode()` distills successful episodes into reusable skills
- **Auto-injection** — Matching skills injected into prompts via memory_context

### Phase 4 — Native Browser Harness Adapter (十四-B)
- **CDP daemon** — `agent/tools/browser/daemon.py` — Chrome discovery, TCP loopback IPC, token-based security
- **Browser helpers** — `agent/tools/browser/helpers.py` — coordinate-click default, screenshot-first interaction, direct CDP (no Playwright/Selenium)
- **12 capabilities** — navigate, capture_screenshot, click_at_xy, type_text, js, cdp, fill_input, page_info, etc.
- **Browser adapter** — `agent/tools/adapters/browser_harness.py` — registers browser tools into agent registry

### Added
- New modules: `evolution.py`, `editor.py`, `context_compressor.py`, `skills/` (5 files), `browser/` (4 files), `adapters/browser_harness.py`
- 55 new tests (247 → 302)
- New dependency: `websockets>=13.0`

## v0.4.1 (2026-05-28)

### Changed
- Design docs migrated to Feishu Wiki (all local path references updated)
- Release verification now uses Python urllib instead of curl (Windows compat)
- CLAUDE.md architecture table fully updated with Phase 1-3 modules

### Added
- `update-docs` skill — bilingual README independent-writing rule encoded
- Troubleshooting knowledge base (12 entries) covering PowerShell, lark-cli, Python, and agent bugs

## v0.4.0 (2026-05-28)

Phase 1-3: Quality infrastructure, Event Sourcing, and Intelligence. 247 tests.

### Phase 1 — Infrastructure Quality + Ontology Object Model + Fitness Functions
- **K: Infrastructure** — Versioned schema migrations (MigrationManager), typed config hierarchy (AppConfig dataclass + dev/test presets), Agent factory pattern (create_agent), centralized exception handling (format_error_for_llm with sanitization)
- **G: Ontology Object Model** — AgentObject extended with Data+Logic+Actions+Relations (constraints, relations, available_actions). ObjectConstraint/ObjectAction dataclasses. Role generates ontology context from focus definitions. Object context injected into planning prompts via build_object_context()
- **C: Agent Fitness Functions** — 23 architectural gate tests covering 5 characteristics: plan completeness, dont-do effectiveness with STRIDE threat scenarios, role compliance, context efficiency, output format compliance

### Phase 2 — Event Sourcing Memory System
- **A: Event Sourcing** — 11 event types covering full agent lifecycle (GoalStarted → ObjectObserved → PlanGenerated → ToolCalled/Result → CorrectionApplied/RuleAdded → GoalVerified → GoalCompleted)
- EventStore — SQLite append-only event log with indexed queries by task_id and event_type
- EventPublisher — In-process synchronous pub/sub (explicitly NOT EDA Broker)
- Snapshot mechanism — periodic state snapshots every 50 events for replay efficiency
- Consistency model — Safety-critical events (RuleAdded) synchronously visible; observation events are eventual

### Phase 3 — Intelligence
- **F: Capability Profile Routing** — Per-model, per-task-type success rate tracking (Jagged Frontier). best_model_for() recommends cheapest model with >=85% success rate. Cold start falls back to cost-based routing. CostRouter enhanced with route_with_capability() and record_result()
- **E: Agent Self-Teaching** — PatternMiner discovers patterns across episodes: error clusters → rule proposals, correction clusters → skill proposals, failure clusters → plan hints. Agent proposes, human approves (Taste principle)
- Integration wiring — CostRouter + PatternMiner in Agent. _record_capability_result() after each task. mine_patterns() via Agent API

### Fixed
- FF-2 security gap — _enrich_dont_do_context() extracts path from params, sets path_in_restricted/path_matches. r-fs-001/r-fs-002 now actually fire in production
- create_agent() factory — Agent.__init__ accepts config_dict, so memory_path override works correctly

### Added
- New modules: `memory_migrations.py`, `events.py`, `event_store.py`, `pattern_miner.py`, `providers/capability.py`

## v0.3.1 (2026-05-27)

- Updated README.md and README.zh-CN.md with closed-loop agent architecture
- Added CLAUDE.md with design document index and OS kernel analogy map

## v0.3.0 (2026-05-27)

Phase 4: Closed-loop agent with object model, structured verification, and output format enforcement. 170 tests.

### Phase 1 — DontDoEngine Integration + Object State Memory
- DontDoEngine runtime enforcement at PLAN/PRE_ACTION/POST_ACTION hook points
- Non-set change tracking (`_track_non_set_change()`) recorded per episode
- EpisodeEntry extended with `objects_before`, `objects_after`, `object_changes` fields
- SQLite schema auto-migration for existing databases
- `get_object_history(uri)` — per-object state change history across episodes
- `get_non_set_history()` — dont-do rule change timeline

### Phase 2 — Structured Object Model + Role-based Observation
- `agent/objects.py` — AgentObject with URI, type, state_before/after, diff computation
- `agent/role.py` — Structured Role with ObjectFocus per type (observation/manipulation/dont-do)
- `_observe_structured()` — identifies object types from goal, uses role-filtered observation tools
- `_verify_goal()` V2 — actively re-observes object states, compares before/after diffs
- Object-filtered planning — `_plan_goal` uses only tools relevant to identified object types

### Phase 3 — Correction-to-Rule Closed Loop + TODO Acceptance Criteria
- `agent/correction.py` — Structured Correction model, LLM-driven rule generation from user feedback
- Correction-driven replanning — `_replan_with_corrections()` with user corrections as constraints
- `_analyze_todo()` — LLM checks TODO clarity, acceptance criteria, object involvement
- `_verify_against_criteria()` — post-execution check of each criterion
- `Correction` → YAML files in `corrections/` directory, consumed and persisted as dont-do rules

### Phase 4 — Mandatory Citation Format + Progressive Disclosure
- `agent/output_format.py` — OutputFormatManager with CitationRule and OutputFormatProfile
- File references enforced: `path/to/file:line_number`, `function()`, `config.key.subkey`
- Progressive disclosure — `---` separator required for responses >500 chars
- Action report format — every `<function_call>` requires `<action_report>`
- `<format_rules immutable="true">` injected into every prompt; post-hoc validation

### Added
- New modules: `objects.py`, `role.py`, `correction.py`, `output_format.py`
- CLI reference: `CLAUDE.md` at project root with design doc index and architecture map

## v0.2.0 (2026-05-27)

Phase 2 + Phase 3 complete. 123 tests.

### Phase 2 — Memory & Security
- SQLite WAL backend with FTS5 full-text search
- Semantic memory (preferences, facts, patterns) with LLM-driven consolidation
- Goal mode — K8s reconciliation loop (observe, plan, execute, verify)
- Dont-Do engine — iptables-style hook-based rule enforcement
- Context virtual memory — page table, LRU + priority replacement, conversation compression
- Provider failover — RAID-style sequential fallback with circuit breaker
- Credential guard — kernel keyring model, LLM never sees raw credentials
- Search abstraction layer — Python + ripgrep auto-detection
- MCP SSE/Streamable HTTP transports
- Remote search — GitHub + MCP Registry

### Phase 3 — Ecosystem & Scale
- Cost router — DVFS-style progressive model escalation (haiku → sonnet → opus)
- Plugin publish — package tools as .tar.gz, publish to GitHub Releases
- Evaluation benchmark suite — LTP-style regression testing, 6 standard scenarios
- Multi-agent infrastructure — D-Bus event bus + Unix pipe pipeline

### Changed
- Python requirement lowered from 3.12 to 3.11
- Renamed package from my-agent to therain2020-agent

## v0.1.1 (2026-05-27)

- Python 3.11 support

## v0.1.0 (2026-05-27)

Initial release. Add-First Agent skeleton.
- CLI with 16 subcommands
- 9 external ecosystem adapters
- 51 tests, CI/CD pipeline
