---
name: browser
version: 1.0.0
objects: [web-page]
capabilities:
  - name: page_info
    description: "Get current page URL, title, viewport size, and scroll position"
  - name: capture_screenshot
    description: "Take a PNG screenshot of the current viewport"
    parameters:
      path: string — File path to save screenshot
      full: boolean — Capture full page beyond viewport
      max_dim: integer — Maximum dimension in pixels
  - name: click_at_xy
    description: "Click at pixel coordinates — works through iframes and Shadow DOM"
    parameters:
      x: integer (required) — X coordinate in CSS pixels
      "y": integer (required) — Y coordinate in CSS pixels
      button: string — Mouse button (left, right, middle)
  - name: new_tab
    description: "Open a new browser tab — always use for first navigation"
    parameters:
      url: string — URL to navigate to
  - name: goto_url
    description: "Navigate the current tab to a URL"
    parameters:
      url: string (required) — URL to navigate to
  - name: list_tabs
    description: "List all open browser tabs"
  - name: type_text
    description: "Type text at the current keyboard focus"
    parameters:
      text: string (required) — Text to type
  - name: press_key
    description: "Press a keyboard key — Enter, Tab, Escape, ArrowLeft, etc"
    parameters:
      key: string (required) — Key name
  - name: scroll
    description: "Scroll the page at given coordinates"
    parameters:
      x: integer (required) — X coordinate
      "y": integer (required) — Y coordinate
      dy: integer — Vertical scroll delta
  - name: wait
    description: "Sleep for N seconds"
    parameters:
      seconds: number — Seconds to wait
  - name: wait_for_load
    description: "Wait until the page finishes loading"
    parameters:
      timeout: number — Max seconds to wait
---

# Browser Control

Screenshot-first browser interaction via Chrome DevTools Protocol.
Connect to the user's running Chrome.
