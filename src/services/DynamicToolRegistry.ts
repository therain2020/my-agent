/**
 * DynamicToolRegistry — Runtime tool loading for therain2020-agent.
 *
 * Built-in tools are statically registered at build time (src/tools.ts).
 * Dynamic tools are loaded at runtime from ~/.claude/dynamic-tools/*.ts
 * via Bun's dynamic import(). This enables self-evolution: the agent can
 * write a new .ts tool file and register it without a rebuild.
 *
 * Each dynamic tool file must export default a Tool object (matching the
 * Tool<Input, Output, P> interface from src/Tool.ts).
 */

import { homedir } from 'os'
import { join } from 'path'
import { existsSync, mkdirSync, readdirSync } from 'fs'
import type { Tool } from '../Tool.js'

const DYNAMIC_TOOLS_DIR = join(homedir(), '.claude', 'dynamic-tools')

let registry: DynamicToolRegistry | null = null

export class DynamicToolRegistry {
  private tools = new Map<string, Tool>()

  static instance(): DynamicToolRegistry {
    if (!registry) {
      registry = new DynamicToolRegistry()
    }
    return registry
  }

  /** Register a tool at runtime (called after agent writes a new .ts file). */
  async register(toolPath: string): Promise<Tool> {
    const module = (await import(toolPath)) as { default: Tool }
    const tool = module.default
    this.tools.set(tool.name, tool)
    return tool
  }

  /** Load all dynamic tools from ~/.claude/dynamic-tools/*.ts at startup. */
  async loadAll(): Promise<Tool[]> {
    if (!existsSync(DYNAMIC_TOOLS_DIR)) {
      return []
    }

    const files = readdirSync(DYNAMIC_TOOLS_DIR).filter(
      (f) => f.endsWith('.ts') || f.endsWith('.tsx'),
    )

    const tools: Tool[] = []
    for (const file of files) {
      try {
        const tool = await this.register(join(DYNAMIC_TOOLS_DIR, file))
        tools.push(tool)
      } catch (err) {
        // Failed to load a dynamic tool — skip it rather than crashing
        console.error(
          `[DynamicToolRegistry] Failed to load ${file}:`,
          (err as Error).message,
        )
      }
    }
    return tools
  }

  /** Get all registered dynamic tools (called by assembleToolPool). */
  getAll(): Tool[] {
    return [...this.tools.values()]
  }

  /** Remove a dynamic tool by name. */
  remove(toolName: string): void {
    this.tools.delete(toolName)
  }

  /** Check if a tool is dynamic (for conflict detection). */
  has(toolName: string): boolean {
    return this.tools.has(toolName)
  }

  /** Get the tools directory path (for agent self-reference). */
  static getToolsDir(): string {
    if (!existsSync(DYNAMIC_TOOLS_DIR)) {
      mkdirSync(DYNAMIC_TOOLS_DIR, { recursive: true })
    }
    return DYNAMIC_TOOLS_DIR
  }
}

export function getDynamicToolRegistry(): DynamicToolRegistry {
  return DynamicToolRegistry.instance()
}
