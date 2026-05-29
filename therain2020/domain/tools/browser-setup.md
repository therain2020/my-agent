---
name: browser-setup
version: 1.0.0
objects: [browser]
capabilities:
  - name: setup
    description: "Auto-configure browser connection. Call this FIRST when browser
      tools fail with 'daemon not running' or 'No browser connected'. It will
      find Chrome, launch it with remote debugging, and start the daemon."
    parameters:
      port: integer — Chrome debugging port, default 9222
  - name: status
    description: "Check current browser connection status"
---

# Browser Setup

Agent self-bootstraps the browser-harness connection so browser tools
work without manual user intervention. Uses Way 2 (dedicated Chrome profile
with --remote-debugging-port) which doesn't require the user to click
anything in their browser.
