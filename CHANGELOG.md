# Changelog

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
