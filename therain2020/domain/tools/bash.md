---
name: bash
version: 1.0.0
objects: [system]
capabilities:
  - name: run
    description: "Execute a shell command. This is your PRIMARY tool for
      almost everything: install packages, list files, read files,
      write files, run scripts, check system state, start services.
      Output capped at 5000 chars, 30s timeout."
    parameters:
      command: string (required) — Shell command to execute
      timeout: integer — Timeout in seconds, default 30
  - name: read
    description: "Read a file. Convenience for read() vs run('cat')."
    parameters:
      path: string (required) — File path
  - name: write
    description: "Write content to a file. Creates parent directories."
    parameters:
      path: string (required) — File path
      content: string (required) — Content to write
  - name: delete
    description: "Delete a file or directory. REQUIRES USER CONFIRMATION.
      First call fails asking for confirmation. Explain to user what
      you're deleting and why, then call again with confirmed=True."
    parameters:
      path: string (required) — Path to delete
      confirmed: boolean — Set to true after user approves
---

# Bash

The agent's hands. LLM is the brain, bash is the body.  
Create tools: `run("cat > .generated/x.py << 'EOF'...")`  
Fix problems: `run("pip install ...")`  
Inspect state: `run("which browser-harness")`
