# Changelog

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
