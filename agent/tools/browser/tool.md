---
name: browser-harness
version: "0.1.0"
description: "Browser automation via direct CDP — coordinate-click default, screenshot-first"
objects: [web-page, web-element, browser-tab]
source: builtin
runtime: import
capabilities:
  - name: navigate
    params:
      url: {type: string, required: true}
    description: "Navigate to a URL"
  - name: capture_screenshot
    params: {}
    description: "Capture a screenshot of the current page (base64 PNG)"
  - name: click_at_xy
    params:
      x: {type: number, required: true}
      y: {type: number, required: true}
    description: "Click at pixel coordinates. Compositor-level — works through iframes and shadow DOM."
  - name: type_text
    params:
      text: {type: string, required: true}
    description: "Type text at current keyboard focus"
  - name: press_key
    params:
      key: {type: string, required: true}
    description: "Press a keyboard key (Enter, Escape, Tab, etc.)"
  - name: js
    params:
      expression: {type: string, required: true}
    description: "Execute JavaScript in the page. Auto-IIFE-wrapped."
  - name: get_page_text
    params: {}
    description: "Get all visible text content of the page"
  - name: get_element_info
    params:
      selector: {type: string, required: true}
    description: "Get position, size, and visibility of a DOM element"
  - name: fill_input
    params:
      selector: {type: string, required: true}
      value: {type: string, required: true}
    description: "Fill an input field (React/Vue/Ember aware)"
  - name: cdp
    params:
      method: {type: string, required: true}
      params: {type: object, required: false}
    description: "Raw CDP command — escape hatch for anything not in helpers"
  - name: page_info
    params: {}
    description: "Get current page title and URL"
  - name: wait_for_network_idle
    params:
      timeout: {type: number, required: false}
    description: "Wait for network activity to settle"
behavior_rules:
  - "默认使用截图+坐标点击模式: capture_screenshot() -> 从图像分析 -> click_at_xy(x,y) -> capture_screenshot() 验证"
  - "坐标点击默认。抑制 Playwright 习惯反射 '先定位，再点击'"
  - "Core helpers stay short. 缺失功能通过 user_helpers.py 扩展，不修改 helpers.py"
  - "使用 js() 做批量数据提取，不做逐个元素选择器提取"
  - "截图优先交互。对于视觉-语言模型，像素比选择器更可靠"
dont_do:
  - object: web-page
    operations: [navigate]
    unless: "URL 已在任务描述中明确给出"
    message: "导航前确认目标 URL"
---

# Browser Harness

通过 Chrome DevTools Protocol 直接控制浏览器。

## 核心交互模式

1. **截图优先**: `capture_screenshot()` -> 从图像分析页面 -> 确定操作坐标
2. **坐标点击**: `click_at_xy(x, y)` -> `capture_screenshot()` 验证 -> 继续
3. **DOM 回退**: 仅在批量数据提取时使用 `js()` 或 `get_element_info()`

## 自愈扩展

如果需要 `helpers.py` 中没有的功能，使用工具编辑器将新函数写入 `user_helpers.py`。
下次执行时自动加载，无需修改核心 helpers.py。
