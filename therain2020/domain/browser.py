"""Browser domain tool — screenshots, coordinate clicks, CDP primitives.

Thin integration with browser-harness daemon over IPC. Prefers
screenshot-first interaction: capture → find target → click_at_xy
→ capture to verify. Only drops to DOM when the target has no
visible geometry.
"""


def capture_screenshot(path=None, full=False, max_dim=None):
    return "[browser] capture_screenshot not yet connected"


def click_at_xy(x, y, button="left", clicks=1):
    return f"[browser] click_at_xy({x}, {y})"


def page_info():
    return "[browser] page_info not yet connected"


def new_tab(url="about:blank"):
    return "[browser] new_tab"


def goto_url(url):
    return "[browser] goto_url"


def list_tabs(include_chrome=True):
    return []


def js(expression):
    return "[browser] js"


def type_text(text):
    return "[browser] type_text"


def press_key(key, modifiers=0):
    return "[browser] press_key"


def scroll(x, y, dy=-300, dx=0):
    return "[browser] scroll"


def wait(seconds=1.0):
    import time
    time.sleep(seconds)


def wait_for_load(timeout=15):
    import time
    time.sleep(0.5)
    return True
