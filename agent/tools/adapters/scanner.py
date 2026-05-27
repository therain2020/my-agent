"""Installed agent scanner. 类比: macOS 迁移助理.

Scans the local machine for installed AI agents (Claude Code, Codex,
Gemini, Cursor) and lists all migratable content: skills, plugins,
MCP servers, settings, rules, and config files.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import structlog

logger = structlog.get_logger()


@dataclass
class Finding:
    """A single migratable item found by the scanner."""
    type: str  # skill | plugin | mcp | settings_deny | settings_hooks | rule | plain_text
    name: str
    source: str  # Which agent it came from
    path: Optional[Path] = None
    command: Optional[str] = None  # For MCP servers
    metadata: dict = field(default_factory=dict)
    description: str = ""


@dataclass
class AgentScanResult:
    """Scan result for a single agent."""
    agent_name: str
    installed: bool
    install_paths: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    error: str = ""


@dataclass
class ScanResult:
    """Complete scan result across all agents."""
    results: list[AgentScanResult] = field(default_factory=list)

    @property
    def total_findings(self) -> int:
        return sum(len(r.findings) for r in self.results)

    @property
    def installed_agents(self) -> list[str]:
        return [r.agent_name for r in self.results if r.installed]

    def all_findings_by_type(self, finding_type: str) -> list[Finding]:
        return [f for r in self.results for f in r.findings if f.type == finding_type]


class InstalledAgentScanner:
    """Scanner that detects installed AI agents and lists migratable content.

    类比: macOS 迁移助理 — 自动检测旧设备，列出可迁移的数据。
    """

    AGENT_DETECTORS = {
        "claude-code": "_scan_claude_code",
        "codex": "_scan_codex",
        "gemini": "_scan_gemini",
        "cursor": "_scan_cursor",
    }

    def scan_all(self) -> ScanResult:
        """Scan all known agents."""
        results = []
        for agent_name, method_name in self.AGENT_DETECTORS.items():
            try:
                method = getattr(self, method_name)
                result = method()
                results.append(result)
            except Exception as e:
                logger.warning("scanner_error", agent=agent_name, error=str(e))
                results.append(AgentScanResult(
                    agent_name=agent_name,
                    installed=False,
                    error=str(e),
                ))
        return ScanResult(results=results)

    def scan_agent(self, agent_name: str) -> AgentScanResult:
        """Scan a specific agent by name."""
        method_name = self.AGENT_DETECTORS.get(agent_name)
        if not method_name:
            return AgentScanResult(
                agent_name=agent_name,
                installed=False,
                error=f"Unknown agent: {agent_name}"
            )
        return getattr(self, method_name)()

    # === Claude Code ===

    def _scan_claude_code(self) -> AgentScanResult:
        findings = []
        paths = []
        home = Path.home()

        # Global skills
        skills_dir = home / ".claude" / "skills"
        if skills_dir.exists():
            paths.append(str(skills_dir))
            for skill_dir in skills_dir.iterdir():
                if skill_dir.is_dir():
                    skill_md = skill_dir / "SKILL.md"
                    if skill_md.exists():
                        findings.append(Finding(
                            type="skill", name=skill_dir.name,
                            source="claude-code",
                            path=skill_md,
                            description=self._first_line(skill_md),
                        ))

        # Project-level .claude/skills
        cwd = Path.cwd()
        project_skills = cwd / ".claude" / "skills"
        if project_skills.exists() and project_skills != skills_dir:
            paths.append(str(project_skills))
            for skill_dir in project_skills.iterdir():
                if skill_dir.is_dir():
                    skill_md = skill_dir / "SKILL.md"
                    if skill_md.exists():
                        findings.append(Finding(
                            type="skill",
                            name=f"project:{skill_dir.name}",
                            source="claude-code",
                            path=skill_md,
                            description=self._first_line(skill_md),
                        ))

        # Global settings.json
        settings_path = home / ".claude" / "settings.json"
        if settings_path.exists():
            paths.append(str(settings_path))
            try:
                settings = json.loads(settings_path.read_text(encoding="utf-8"))
                # MCP servers
                mcp_servers = settings.get("mcpServers", {})
                for name, config in mcp_servers.items():
                    findings.append(Finding(
                        type="mcp", name=name,
                        source="claude-code",
                        command=config.get("command", str(config)),
                        metadata=config,
                        description=f"MCP server: {name}",
                    ))
                # Permissions deny → dont-do
                deny_rules = settings.get("permissions", {}).get("deny", [])
                if deny_rules:
                    findings.append(Finding(
                        type="settings_deny",
                        name="claude-code-deny-rules",
                        source="claude-code",
                        path=settings_path,
                        metadata={"rules": deny_rules},
                        description=f"{len(deny_rules)} deny rules from permissions",
                    ))
                # Hooks → probes
                hooks = settings.get("hooks", {})
                if hooks:
                    findings.append(Finding(
                        type="settings_hooks",
                        name="claude-code-hooks",
                        source="claude-code",
                        path=settings_path,
                        metadata={"hooks": hooks},
                        description=f"Hooks: {', '.join(hooks.keys())}",
                    ))
            except json.JSONDecodeError:
                pass

        # Global CLAUDE.md
        claude_md = home / ".claude" / "CLAUDE.md"
        if claude_md.exists():
            paths.append(str(claude_md))
            findings.append(Finding(
                type="plain_text", name="claude-global-claude-md",
                source="claude-code",
                path=claude_md,
                description=f"Global CLAUDE.md ({claude_md.stat().st_size} bytes)",
            ))

        # Project CLAUDE.md
        project_claude_md = cwd / "CLAUDE.md"
        if project_claude_md.exists():
            paths.append(str(project_claude_md))
            findings.append(Finding(
                type="plain_text", name="claude-project-claude-md",
                source="claude-code",
                path=project_claude_md,
                description=f"Project CLAUDE.md ({project_claude_md.stat().st_size} bytes)",
            ))

        installed = bool(paths)
        return AgentScanResult(
            agent_name="claude-code",
            installed=installed,
            install_paths=paths,
            findings=findings,
        )

    # === Codex CLI ===

    def _scan_codex(self) -> AgentScanResult:
        findings = []
        paths = []
        home = Path.home()

        config_path = home / ".codex" / "config.yaml"
        if config_path.exists():
            paths.append(str(config_path))
            try:
                import yaml
                config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
                mcp_servers = config.get("mcpServers", {})
                for name, cfg in mcp_servers.items():
                    findings.append(Finding(
                        type="mcp", name=name,
                        source="codex",
                        command=cfg.get("command", str(cfg)),
                        description=f"Codex MCP: {name}",
                    ))
            except Exception:
                pass

        plugins_dir = home / ".codex" / "plugins"
        if plugins_dir.exists():
            paths.append(str(plugins_dir))
            for plugin_dir in plugins_dir.iterdir():
                if plugin_dir.is_dir():
                    plugin_json = plugin_dir / "codex-plugin.json"
                    if plugin_json.exists():
                        findings.append(Finding(
                            type="plugin", name=plugin_dir.name,
                            source="codex",
                            path=plugin_dir,
                            description=f"Codex plugin: {plugin_dir.name}",
                        ))

        installed = bool(paths)
        return AgentScanResult(
            agent_name="codex",
            installed=installed,
            install_paths=paths,
            findings=findings,
        )

    # === Gemini CLI ===

    def _scan_gemini(self) -> AgentScanResult:
        findings = []
        paths = []
        home = Path.home()

        config_path = home / ".gemini" / "config.json"
        if config_path.exists():
            paths.append(str(config_path))
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
                mcp_servers = config.get("mcpServers", {})
                for name, cfg in mcp_servers.items():
                    findings.append(Finding(
                        type="mcp", name=name,
                        source="gemini",
                        command=cfg.get("command", str(cfg)),
                        description=f"Gemini MCP: {name}",
                    ))
            except json.JSONDecodeError:
                pass

        extensions_dir = home / ".gemini" / "extensions"
        if extensions_dir.exists():
            paths.append(str(extensions_dir))
            for ext_dir in extensions_dir.iterdir():
                if ext_dir.is_dir():
                    findings.append(Finding(
                        type="plugin", name=ext_dir.name,
                        source="gemini",
                        path=ext_dir,
                        description=f"Gemini extension: {ext_dir.name}",
                    ))

        installed = bool(paths)
        return AgentScanResult(
            agent_name="gemini",
            installed=installed,
            install_paths=paths,
            findings=findings,
        )

    # === Cursor ===

    def _scan_cursor(self) -> AgentScanResult:
        findings = []
        paths = []
        cwd = Path.cwd()

        rules_dir = cwd / ".cursor" / "rules"
        if rules_dir.exists():
            paths.append(str(rules_dir))
            for rule_file in rules_dir.glob("*.mdc"):
                findings.append(Finding(
                    type="rule", name=rule_file.stem,
                    source="cursor",
                    path=rule_file,
                    description=f"Cursor rule: {rule_file.stem}",
                ))

        mcp_json = cwd / ".cursor" / "mcp.json"
        if mcp_json.exists():
            paths.append(str(mcp_json))
            try:
                config = json.loads(mcp_json.read_text(encoding="utf-8"))
                mcp_servers = config.get("mcpServers", {})
                for name, cfg in mcp_servers.items():
                    findings.append(Finding(
                        type="mcp", name=name,
                        source="cursor",
                        command=cfg.get("command", str(cfg)),
                        description=f"Cursor MCP: {name}",
                    ))
            except json.JSONDecodeError:
                pass

        installed = bool(paths)
        return AgentScanResult(
            agent_name="cursor",
            installed=installed,
            install_paths=paths,
            findings=findings,
        )

    @staticmethod
    def _first_line(path: Path) -> str:
        """Get the first non-empty, non-YAML line of a markdown file."""
        try:
            content = path.read_text(encoding="utf-8")
            in_frontmatter = False
            for line in content.split("\n"):
                stripped = line.strip()
                if stripped == "---":
                    in_frontmatter = not in_frontmatter
                    continue
                if not in_frontmatter and stripped and not stripped.startswith("# "):
                    return stripped[:100]
                if not in_frontmatter and stripped.startswith("# "):
                    return stripped[2:100]
        except Exception:
            pass
        return ""
