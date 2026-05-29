---
name: tool-writer
version: 1.0.0
objects: [tool]
capabilities:
  - name: write
    description: "Create a NEW tool for yourself. Use this when existing tools cannot
      complete a task. Write Python code that solves the problem, and it becomes a
      permanent new capability available in all future sessions."
    parameters:
      name: string (required) — Tool name, lowercase with hyphens (e.g. image-convert)
      code: string (required) — Python function body implementing the tool
      description: string — One-line description of what this tool does
---

# Tool Writer

Agent self-evolution: write new tools to `.generated/` directory.
These tools are automatically loaded by ToolRegistry on next startup.
