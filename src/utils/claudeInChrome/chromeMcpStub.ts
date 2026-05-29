/**
 * Stub for @ant/claude-for-chrome-mcp.
 * Returns empty browser tools so Chrome features self-disable.
 */
export const BROWSER_TOOLS: string[] = []
export type ClaudeForChromeContext = Record<string, unknown>
export type Logger = Record<string, unknown>
export type PermissionMode = string

export async function createClaudeForChromeMcpServer(): Promise<null> {
  return null
}
