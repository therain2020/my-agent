---
name: filesystem
version: 1.0.0
objects: [file]
capabilities:
  - name: read
    description: Read the contents of a file at the given path
    parameters:
      path: string (required) — Absolute or relative file path
  - name: write
    description: Write content to a file, creating parent directories if needed
    parameters:
      path: string (required) — File path to write to
      content: string (required) — Content to write
  - name: list_files
    description: List files in a directory matching a glob pattern
    parameters:
      dir: string — Directory to list, defaults to current directory
      pattern: string — Glob pattern, defaults to *
  - name: delete
    description: Delete a file or empty directory
    parameters:
      path: string (required) — Path to delete
  - name: make_temp
    description: Create a temporary file with the given content and return its path
    parameters:
      content: string (required) — Content to write to temp file
      suffix: string — Optional file suffix
---

# Filesystem Tools

Core file operations: read, write, list, delete.
