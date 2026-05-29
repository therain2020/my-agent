---
name: shell
version: 1.0.0
objects: [system]
capabilities:
  - name: run
    description: "Execute a shell command. Use for: installing packages,
      starting services, running CLI tools, system diagnostics.
      NOT for interactive programs or infinite commands.
      Output capped at 5000 chars, 30s timeout."
    parameters:
      command: string (required) — The shell command to execute
      timeout: integer — Timeout in seconds, default 30
---

# Shell

System command execution. The foundation of self-healing —
without this, the agent cannot install packages or start services.
