# Browser Harness 全面解析

## 一、项目定位

**Browser Harness** 是 browser-use 团队开发的极薄 CDP (Chrome DevTools Protocol) 代理层，让 LLM Agent 直接操控用户的真实 Chrome 浏览器。核心理念是：一个 WebSocket 连到 Chrome，中间没有框架横在中间。

> "The Bitter Lesson of Agent Harnesses": 越薄的代理越好。代码越少，Agent 自己写的东西越多。

- 仓库: `https://github.com/browser-use/browser-harness`
- 许可证: MIT
- Python ≥ 3.11
- 核心代码约 2100 行

## 二、架构概览

```
Chrome (用户浏览器) ←→ CDP WebSocket ←→ Daemon (常驻进程) ←→ IPC (Unix Socket/TCP) ←→ browser-harness CLI + Helpers
```

- Daemon: CDP WS 持有者、事件缓冲 (500条 deque)、Session 管理、Dialog 状态追踪
- Helpers: 浏览器控制 primitives，自动加载 `agent_helpers.py`
- Admin: daemon 生命周期、诊断、更新、远程浏览器管理
- IPC: 一行 JSON 一发，支持 Unix Domain Socket (POSIX) 和 TCP loopback + token (Windows)

## 三、核心设计原则

### 3.1 截图优先、坐标点击

```
capture_screenshot() → 看图找目标 → click_at_xy(x, y) → capture_screenshot() 验证
```

点击走 Input.dispatchMouseEvent，在 Chrome compositor 层完成，天然穿透 iframe / Shadow DOM / 跨域。只有当目标不可见时才退到 DOM 操作。与 Playwright "先定位再点击" 的思维完全相反。

### 3.2 Agent 扩展自身

Agent 想做 X → agent_helpers.py 里没有 → Agent 自己写 helper → 下次就有了。agent-workspace/agent_helpers.py 是 Agent 可编辑的帮助代码，每次 browser-harness 调用时自动加载。

### 3.3 极简设计约束

- 连接用户的已有 Chrome，不自己启动浏览器
- run.py 保持极简，无 argparse、无 subcommand、无额外控制层
- 不加 manager 层：无重试框架、无 session manager、无 daemon supervisor、无 config system、无 logging framework
- CDP 调用优先用原始字符串，不用类型化 wrapper

### 3.4 双模式浏览器连接

| 方式 | 特征 | 适用场景 |
|------|------|----------|
| Way 1: chrome://inspect 复选框 | 使用用户真实 Profile（登录态/扩展/历史全在） | Agent 帮用户在真实浏览器中做任务 |
| Way 2: --remote-debugging-port=9222 | 独立 Profile，无弹窗 | 无人值守自动化 |
| Cloud: Browser Use Cloud API | 远程浏览器，含代理/验证码解决 | 并行子 Agent、无头部署 |

## 四、核心模块详解

### 4.1 daemon.py — 守护进程 (约 420 行)

生命周期: start() → get_ws_url() → CDPClient.connect() → attach_first_page() → 注册事件拦截 → handle() 循环处理 IPC → serve()

关键机制:
- attach_first_page(): 优先 attach 真实页面，过滤掉 omnibox-popup 等假目标
- 事件缓冲: deque(maxlen=500)，通过 meta: drain_events 拉取
- Session 恢复: CDP session 过期时自动重新 attach
- 远程浏览器管理: 通过 api.browser-use.com/api/v3
- 多 Profile 发现: 支持 macOS/Linux/Windows 上 20+ 种 Chromium 浏览器路径
- Chrome 147+ 兼容: /json/version 返回 404 时回退到 DevToolsActivePort 中的 ws path

### 4.2 helpers.py — 浏览器操作 (约 500 行)

导航: new_tab(url) / goto_url(url) / switch_tab(target) / ensure_real_tab() / close_tab() / list_tabs()

交互: click_at_xy(x, y) / type_text(text) / fill_input(sel, text) / press_key(key) / scroll(x, y, dy) / dispatch_key(sel, key)

视觉: capture_screenshot(path, full, max_dim) / page_info()

工具: js(expression) / http_get(url) / cdp(method, **params) / wait_for_load(timeout) / wait_for_element(sel, visible) / wait_for_network_idle(timeout, idle_ms) / upload_file(sel, path)

特色函数:
- fill_input: 解决 React/Vue 受控组件问题，模拟真实 key 事件 + dispatch input/change
- http_get: 纯 HTTP（不走浏览器），支持 fetch-use 代理和 gzip，配合 ThreadPoolExecutor 做批量
- wait_for_network_idle: 按 session 过滤事件，防止背景 tab 的轮询干扰

### 4.3 admin.py — 管理与诊断 (约 860 行)

- ensure_daemon(): 幂等启动 daemon，自愈 stale daemon / 冷 Chrome / 未 Allow 权限
- restart_daemon(): 安全停止，含进程指纹验证 + PID 复用防护 + SIGTERM 回退
- run_doctor(): 11 项诊断（平台/Python/版本/Chrome/daemon/连接/profile-use/API key/Snap检测）
- run_update(): 自动更新（git pull --ff-only 或 uv tool upgrade）
- start_remote_daemon(): 云浏览器配置（profile/代理/超时/分辨率）
- sync_local_profile(): 本地 Chrome cookies → 云 Profile
- 进程指纹: 跨平台验证（Linux /proc/stat / macOS ps lstart / Windows GetProcessTimes 64-bit FILETIME）

### 4.4 _ipc.py — IPC 通信 (约 200 行)

| 平台 | 传输 | 安全 |
|------|------|------|
| POSIX | Unix Domain Socket (/tmp/bu-{NAME}.sock, umask 0o077 → chmod 600) | 文件权限隔离 |
| Windows | TCP loopback (127.0.0.1:动态端口) | 32 字节 secrets.token_hex 随机 token |

- identify() 严格类型检查: type(pid) is int 排除 bool 类型混淆，pid 范围校验防溢出
- ping() 验证 pong 结构，防止非 daemon 进程冒充

### 4.5 run.py — CLI 入口 (约 130 行)

极简 CLI: browser-harness <<'PY' ... PY
- 自动 ensure_daemon() + exec()
- --doctor / --update / --version / --reload
- 云自动启动需同时满足: BROWSER_USE_API_KEY + BU_AUTOSPAWN + 无 daemon + 无本地 Chrome + 无显式端点

## 五、Agent 工作空间

### agent_helpers.py

Agent 在运行中自行编辑的 helper 文件。每次 browser-harness 调用时自动 import 到全局命名空间。

### domain-skills/ (90+ 站点)

社区贡献的站点特定 playbook，每站点一个目录。涵盖电商 (Amazon, eBay, Walmart, Shopify)、社交媒体 (LinkedIn, Reddit, X, 小红书)、学术 (arXiv, PubMed)、招聘 (BOSS直聘, Indeed, Glassdoor)、开发 (GitHub, StackOverflow, Vercel)、金融 (CoinGecko, CoinMarketCap)、娱乐 (YouTube, Spotify, Steam)、旅行 (Expedia, 携程) 等。

关键规则: Skills 由 Agent 编写而非人类。Agent 发现非显而易见的规律后自己写 skill。

### interaction-skills/ (17 个)

可复用的 UI 交互模式: connection, cookies, cross-origin-iframes, dialogs, downloads, drag-and-drop, dropdowns, iframes, network-requests, print-as-pdf, profile-sync, screenshots, scrolling, shadow-dom, tabs, uploads, viewport

## 六、环境变量参考

| 变量 | 用途 |
|------|------|
| BU_NAME | daemon 实例名（默认 default），多实例隔离 |
| BU_CDP_WS | 远程浏览器 WebSocket URL |
| BU_CDP_URL | 远程浏览器 DevTools HTTP endpoint |
| BU_BROWSER_ID | 云浏览器 ID（用于关闭） |
| BROWSER_USE_API_KEY | Browser Use Cloud API 密钥 |
| BU_AUTOSPAWN | 设为 1 时自动在云端创建浏览器 |
| BH_AGENT_WORKSPACE | agent-workspace 目录路径 |
| BH_CHROME_PATH | Chrome 二进制路径 |
| BH_DOMAIN_SKILLS | 设为 1 启用 domain-skills |
| BH_DEBUG_CLICKS | 设为 1 截图标注点击位置 |
| BH_RUNTIME_DIR | 运行时文件目录（sock/port/pid） |
| BH_TMP_DIR | 临时文件目录（截图/log） |

## 七、质量属性

### 安全性
- Windows TCP IPC 需要 32 字节随机 token 认证
- POSIX 使用 Unix Socket + umask 0o077（无 TOCTOU 窗口）
- restart_daemon() 有完整的 PID 复用防护（进程指纹验证）
- identify() 严格类型检查防止类型混淆攻击
- BU_NAME 有正则校验防止路径遍历

### 可靠性
- Daemon 自动自愈（stale session 检测 + 重新 attach）
- Chrome 发现有多层回退（DevToolsActivePort → /json/version → 端口探测）
- ensure_real_tab() 自动从内部页恢复到真实 tab
- 远程浏览器关闭时自动 PATCH stop，防止持续计费

### 性能
- CDP 域启用并行化（Page/DOM/Runtime/Network 四个 enable 并发）
- tab switch 时新旧 session 操作并行
- http_get() 支持 ThreadPoolExecutor 批量获取（README 声称 249 个 Netflix 页面 2.8 秒）

### 可观测性
- --doctor 11 项诊断
- --debug-clicks 截图标注
- daemon 日志文件
- 每日更新检查（24h 缓存）
- 马 emoji 标记控制的 tab

## 八、依赖项

```
cdp-use==1.4.5       # CDP WebSocket 客户端
fetch-use==0.4.0     # HTTP 代理（绕过 bot 检测）
pillow==12.2.0       # 截图处理和尺寸限制
websockets==15.0.1   # WebSocket 底层
```

通过 uv tool install -e . 或 pip install 安装。

## 九、与本项目 (therain2020-agent) 的关联

### 9.1 工具适配器

therain2020-agent 的 agent/tools/adapters/ 可以做一个 browser-harness adapter，将 browser-harness 的能力注册为 Agent tool。browser-harness 的 CLI heredoc 模式天然适合被 Agent 调用。

### 9.2 浏览器驱动

therain2020-agent 的 agent/tools/browser/ (CDP daemon, screenshot-first interaction) 与 browser-harness 的设计理念完全一致：截图优先、坐标点击、薄层设计。可以直接复用 browser-harness 的 CDP daemon 和 helpers 作为浏览器驱动层。

### 9.3 Skill 系统

两边的 skill 机制可以互通。browser-harness 的 domain-skills 可以作为 therain2020-agent 中 browser tool 的参考 playbook 库。interaction-skills 覆盖了 agent/tools/browser/ 需要处理的全部 UI 交互场景。

### 9.4 设计哲学一致

| 维度 | therain2020-agent | browser-harness |
|------|-------------------|-----------------|
| 架构 | OS 内核类比（Process/Scheduler/VFS/LSM） | Thin harness（无框架、无 manager 层） |
| 扩展 | agent/tools/adapters/ + agent/skills/ | agent_helpers.py + domain-skills/ |
| 安全 | Credential guard + prompt injection defense | Token auth + PID 复用防护 |
| 记忆 | Episodic + Semantic + Consolidation | Self-evolving helpers（Agent 写代码） |

### 9.5 具体整合建议

1. 创建 agent/tools/adapters/browser_harness.py，将 browser-harness CLI 封装为 Agent tool
2. 在 agent/tools/browser/ 中复用 daemon.py 的 CDP 连接管理和 _ipc.py 的 IPC 通信
3. 将 domain-skills/ 和 interaction-skills/ 作为 agent/skills/ 的 browser 子类
4. 参考 admin.py 的 ensure_daemon() 自愈模式改进 Agent daemon 的生命周期管理
5. 借鉴进程指纹验证机制增强 Agent 进程管理的安全性

## 十、关键洞察

### 10.1 最薄即是最好

2100 行核心代码做到框架几千行才能做的事。不加 manager 层、config system、logging framework——这些都是 Agent 不需要的。每次想加东西时先问：Agent 自己能写吗？

### 10.2 自我进化闭环

Agent 在运行中编辑自己的 helper 代码和 skill 文件，积累经验。这是真正的 "Agent that learns"——不是微调权重，而是写可执行的代码。

### 10.3 截图优先交互模型

坐标点击穿透一切 DOM 边界，这是与传统浏览器自动化框架的根本区别。Playwright/Selenium 在 iframe、Shadow DOM、跨域 iframe 面前需要特殊处理，browser-harness 不需要。

### 10.4 IPC 设计精巧

非对称设计：POSIX 用文件权限，Windows 用 token。Daemon 只做中继不做逻辑——所有智能在 helpers 层，daemon 是纯 CDP 代理。

### 10.5 云浏览器是杀手锏

本地浏览器 + 远程云浏览器的统一抽象。start_remote_daemon() 一行启动远程浏览器，profile sync 上传 cookies。这让子 Agent 并行成为可能，每个 Agent 一个独立云浏览器。
