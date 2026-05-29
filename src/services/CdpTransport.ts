/**
 * CdpTransport — Minimal Chrome DevTools Protocol transport.
 *
 * Connects to Chrome's remote debugging port (default 9222), discovers
 * available tabs, and provides a send() method for CDP commands.
 *
 * The agent self-evolves CDP tools (Page.navigate, Runtime.evaluate, etc.)
 * via DynamicToolRegistry — we only provide the plumbing.
 *
 * Usage:
 *   const cdp = new CdpTransport()
 *   await cdp.connect(9222)           // Chrome must run with --remote-debugging-port=9222
 *   const title = await cdp.send('Page.getNavigationHistory')
 *   cdp.disconnect()
 */

export class CdpTransport {
  private ws: WebSocket | null = null
  private msgId = 0
  private pending = new Map<number, { resolve: (v: unknown) => void; reject: (e: Error) => void }>()

  async connect(port = 9222): Promise<string[]> {
    // Discover available debugging targets
    const res = await fetch(`http://localhost:${port}/json`)
    const targets = (await res.json()) as Array<{
      webSocketDebuggerUrl: string
      title: string
      type: string
      url: string
    }>

    if (targets.length === 0) {
      throw new Error(`No Chrome tabs found on port ${port}. Start Chrome with --remote-debugging-port=${port}`)
    }

    // Pick the first page target
    const page = targets.find(t => t.type === 'page') ?? targets[0]!
    return this.connectToWs(page.webSocketDebuggerUrl)
  }

  async connectToWs(debuggerUrl: string): Promise<string[]> {
    this.ws = new WebSocket(debuggerUrl)

    const tabList = await new Promise<string[]>((resolve, reject) => {
      this.ws!.onopen = async () => {
        // Enable Page domain to get started
        await this.send('Page.enable')
        resolve([])
      }
      this.ws!.onerror = () => reject(new Error(`WebSocket connection failed: ${debuggerUrl}`))
      this.ws!.onmessage = (event) => {
        const msg = JSON.parse(event.data as string)
        if (msg.id !== undefined && this.pending.has(msg.id)) {
          const handler = this.pending.get(msg.id)!
          this.pending.delete(msg.id)
          if (msg.error) {
            handler.reject(new Error(`CDP error: ${JSON.stringify(msg.error)}`))
          } else {
            handler.resolve(msg.result)
          }
        }
      }
    })

    return tabList
  }

  async send(method: string, params?: Record<string, unknown>): Promise<unknown> {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      throw new Error('CDP not connected. Call connect() first.')
    }

    const id = ++this.msgId
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject })
      this.ws!.send(JSON.stringify({ id, method, params }))
    })
  }

  disconnect(): void {
    if (this.ws) {
      this.ws.close()
      this.ws = null
    }
    this.pending.clear()
    this.msgId = 0
  }

  /** Get list of open tabs (useful for agent to know what's available). */
  async listTabs(port = 9222): Promise<Array<{ title: string; url: string; type: string }>> {
    const res = await fetch(`http://localhost:${port}/json`)
    const targets = (await res.json()) as Array<{ title: string; url: string; type: string }>
    return targets
  }
}
