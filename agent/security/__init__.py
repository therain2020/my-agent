"""Security manager + Credential guard. Prompt injection + kernel keyring."""

from pathlib import Path

import structlog

logger = structlog.get_logger()


class SecurityManager:
    """Manages dont-do rules and security checks.

    Phase 1: Prompt injection mode — reads .md files and formats
    constraints for the system prompt.
    """

    def __init__(self, dont_do_paths: list[str] | None = None):
        self._paths = [Path(p) for p in (dont_do_paths or ["./dont-do"])]
        self._rules: dict[str, str] = {}  # object_name → rule content
        self._dirty = True

    def load_rules(self) -> int:
        self._rules.clear()
        count = 0
        for scan_path in self._paths:
            if not scan_path.exists():
                continue
            for rule_file in sorted(scan_path.glob("*.md")):
                try:
                    content = rule_file.read_text(encoding="utf-8")
                    self._rules[rule_file.stem] = content
                    count += 1
                except Exception as e:
                    logger.error("dont_do_load_error", path=str(rule_file), error=str(e))
        self._dirty = False
        logger.info("dont_do_loaded", count=count)
        return count

    def get_constraints_prompt(self, relevant_objects: list[str] | None = None) -> str:
        if self._dirty:
            self.load_rules()
        if not self._rules:
            return ""
        if relevant_objects:
            included = {}
            for obj in relevant_objects:
                if obj in self._rules:
                    included[obj] = self._rules[obj]
            if not included:
                return ""
            return "\n\n".join(included.values())
        return "\n\n".join(self._rules.values())

    def list_rules(self) -> dict[str, str]:
        if self._dirty:
            self.load_rules()
        return dict(self._rules)

    def add_rule_file(self, path: Path) -> None:
        self._paths.append(path)
        self._dirty = True

    def add_rule(self, name: str, content: str, save_dir: Path | None = None) -> Path:
        self._rules[name] = content
        self._dirty = False
        if save_dir:
            save_dir.mkdir(parents=True, exist_ok=True)
            rule_path = save_dir / f"{name}.md"
            rule_path.write_text(content, encoding="utf-8")
            return rule_path
        return Path(f"{name}.md")
