"""tool-writer: Agent creates its own tools. Writes to .generated/."""


from ..constants import WORKSPACE_DIR


def write(name: str, code: str, description: str = "") -> str:
    """Create a new tool in .generated/. Loaded automatically next run."""
    generated = WORKSPACE_DIR / ".generated"
    generated.mkdir(parents=True, exist_ok=True)

    # Sanitise name
    safe_name = name.strip().lower().replace(" ", "-")

    # Write Python implementation
    py_file = generated / f"{safe_name}.py"
    py_content = (
        f"# Auto-generated tool: {safe_name}\n"
        f"# Description: {description}\n\n"
        f"{code}\n"
    )
    py_file.write_text(py_content, encoding="utf-8")

    # Write tool.md registration
    md_file = generated / f"{safe_name}.md"
    md_content = f"""---
name: {safe_name}
version: 0.1.0
objects: []
capabilities:
  - name: run
    description: {description}
---
# {safe_name}
Agent-generated tool.  Created to solve: {description}
"""
    md_file.write_text(md_content, encoding="utf-8")

    # Record in memory
    try:
        from ..memory_manager import MemoryManager
        mgr = MemoryManager()
        mgr.record_tool(safe_name, description, _summarize(code))
    except Exception:
        pass

    return (
        f"Tool '{safe_name}' created at {py_file}.\n"
        f"Restart to use: therain2020 --repl"
    )


def _summarize(code: str, n: int = 100) -> str:
    line = code.strip().split("\n")[0][:n]
    return line + ("..." if len(code) > n else "")
