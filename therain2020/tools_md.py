"""Parse tool.md files into ToolDef dataclasses.

tool.md format:
    ---
    name: file-reader
    version: 1.0.0
    objects: [file]
    capabilities:
      - name: read
        description: Read file contents
        parameters:
          path: string (required) — File path
    ---
    # Markdown body (agent reference)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Parameter:
    name: str
    type: str
    required: bool = False
    description: str = ""


@dataclass
class Capability:
    name: str
    description: str
    parameters: list[Parameter] = field(default_factory=list)
    verify: dict | None = None
    body: str = ""


@dataclass
class ToolDef:
    name: str
    version: str = "0.1.0"
    objects: list[str] = field(default_factory=list)
    capabilities: list[Capability] = field(default_factory=list)
    source_path: Path | None = None
    body: str = ""

    def to_openai_tools(self) -> list[dict]:
        """Convert capabilities to OpenAI function-calling format."""
        tools = []
        for cap in self.capabilities:
            props = {}
            required = []
            for p in cap.parameters:
                props[p.name] = {"type": p.type, "description": p.description}
                if p.required:
                    required.append(p.name)
            tools.append({
                "type": "function",
                "function": {
                    "name": f"{self.name}__{cap.name}",
                    "description": cap.description,
                    "parameters": {
                        "type": "object",
                        "properties": props,
                        "required": required,
                    } if props else {"type": "object", "properties": {}},
                },
            })
        return tools


def parse_tool_md(content: str, source: Path | None = None) -> ToolDef:
    """Parse a tool.md string into a ToolDef."""
    fm = _extract_frontmatter(content)
    if not fm:
        raise ValueError(f"No frontmatter found in {source or '<string>'}")

    data = yaml.safe_load(fm)
    if not isinstance(data, dict):
        raise ValueError(f"Invalid YAML frontmatter in {source or '<string>'}")

    name = data.get("name", "")
    if not name:
        raise ValueError(f"Missing 'name' in {source or '<string>'}")

    caps = []
    for c in data.get("capabilities", []):
        if isinstance(c, str):
            caps.append(Capability(name=c, description=c))
        elif isinstance(c, dict):
            params = []
            for pname, pdesc in (c.get("parameters") or {}).items():
                parsed = _parse_param_str(pname, str(pdesc))
                params.append(parsed)
            caps.append(Capability(
                name=c.get("name", ""),
                description=c.get("description", ""),
                parameters=params,
                verify=c.get("verify"),
                body=c.get("body", ""),
            ))

    body = content[content.find("---", 3) + 3:] if content.startswith("---") else ""

    return ToolDef(
        name=name,
        version=str(data.get("version", "0.1.0")),
        objects=data.get("objects") or [],
        capabilities=caps,
        source_path=source,
        body=body.strip(),
    )


def load_tool_from_file(path: Path) -> ToolDef:
    return parse_tool_md(path.read_text(encoding="utf-8"), source=path)


def _extract_frontmatter(content: str) -> str | None:
    m = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    return m.group(1) if m else None


def _parse_param_str(name: str, desc: str) -> Parameter:
    """Parse 'path: string (required) — File path' into a Parameter."""
    required = "(required)" in desc
    type_str = "string"
    clean_desc = desc
    # extract type
    type_m = re.match(r"(\w+)", desc)
    if type_m:
        type_str = type_m.group(1)
        clean_desc = desc[type_m.end():].strip()
    # strip '(required)'
    clean_desc = clean_desc.replace("(required)", "").strip()
    # strip leading ' — ' or ' - '
    clean_desc = re.sub(r"^[—\-]\s*", "", clean_desc)
    return Parameter(name=name, type=type_str, required=required, description=clean_desc or desc)
