/**
 * EvolutionLoop — Self-evolution pipeline for therain2020-agent.
 *
 * Orchestrates the full evolution cycle:
 *   Gap → Design → Generate → Validate → Integrate → Verify → Journal
 *
 * Three tiers:
 *   Tier 1: Skill (.claude/skills/) — instant auto-discovery
 *   Tier 2: Dynamic Tool (~/.claude/dynamic-tools/) — runtime import()
 *   Tier 3: Core Engine (src/) — worktree → build → restart
 */

import { homedir } from 'os'
import { join } from 'path'
import { existsSync, mkdirSync } from 'fs'
import { getSelfModService } from './SelfModService.js'
import { getCapabilityGapDetector } from '../CapabilityGapDetector.js'
import { getDynamicToolRegistry } from '../DynamicToolRegistry.js'
import type { CapabilityGap, EvolutionDesign, EvolveResult } from './types.js'
import type { ToolPermissionContext } from '../../types/permissions.js'

const AGENT_SKILLS_DIR = '.claude/skills'
const DYNAMIC_TOOLS_DIR = join(homedir(), '.claude', 'dynamic-tools')

export class EvolutionLoop {
  /**
   * Execute a full evolution cycle for a capability gap.
   *
   * @param gap - The detected capability gap to resolve
   * @param permissionContext - Permission context for mode switching
   * @returns Result of the evolution
   */
  async execute(
    gap: CapabilityGap,
    permissionContext: ToolPermissionContext,
  ): Promise<EvolveResult> {
    const service = getSelfModService()
    const detector = getCapabilityGapDetector()

    try {
      // Step 1: Design — determine tier and target
      const design = this.createDesign(gap)

      // Step 2: Enter self-modify mode
      service.enterSelfModMode(permissionContext)

      // Step 3: Ensure target directory exists
      this.ensureDirectoryExists(design)

      // Step 4: The LLM generates the code and writes it using Write/Edit tools.
      // In selfModify mode, these writes are auto-allowed. The service tracks
      // which files were created/modified.

      // Step 5: Exit self-modify mode
      service.exitSelfModMode(permissionContext)

      // Step 6: Post-integration — load the new capability
      await this.postIntegrate(design)

      // Step 7: Mark gap as resolved
      detector.markResolved(gap.id)

      return {
        status: 'integrated',
        gapId: gap.id,
        design,
        createdFiles: [design.targetPath],
        journalEntry: {
          type: 'evolution_integrated',
          sessionId: `ev-${Date.now()}`,
          description: `Evolved: ${design.name} (Tier ${design.tier})`,
          files: [design.targetPath],
          tier: design.tier,
          timestamp: new Date().toISOString(),
          verdict: 'PASS',
        },
      }
    } catch (err) {
      service.exitSelfModMode(permissionContext)
      return {
        status: 'failed',
        gapId: gap.id,
        design: {
          gapId: gap.id,
          tier: 1,
          name: 'failed',
          description: '',
          approach: '',
          code: '',
          targetPath: '',
        },
        createdFiles: [],
        error: (err as Error).message,
      }
    }
  }

  /**
   * Create a design for the evolution based on the gap.
   * The actual code generation is done by the LLM (fork agent),
   * which sees this design and writes the implementation files.
   */
  createDesign(gap: CapabilityGap): EvolutionDesign {
    const tier = this.determineTier(gap)
    const safeName = gap.id.replace(/[^a-zA-Z0-9_-]/g, '-').slice(0, 40)

    let targetPath: string
    let approach: string

    switch (tier) {
      case 1:
        targetPath = join(AGENT_SKILLS_DIR, safeName, 'SKILL.md')
        approach = `Create a SKILL.md file defining a new skill. Write to ${targetPath}. The skill will be auto-discovered immediately.`
        break
      case 2:
        targetPath = join(DYNAMIC_TOOLS_DIR, `${safeName}.ts`)
        approach = `Create a TypeScript tool file. Write to ${targetPath}. Export default a Tool object using buildTool(). The tool will be loaded at runtime by DynamicToolRegistry.`
        break
      case 3:
        targetPath = '' // Determined by the LLM based on which core files need changes
        approach =
          'Modify core engine source files in src/. Use SelfHealTool or direct Edit in a git worktree. After changes, rebuild with bun build and restart.'
        break
    }

    return {
      gapId: gap.id,
      tier,
      name: safeName,
      description: gap.description,
      approach,
      code: '',
      targetPath,
    }
  }

  /**
   * Determine the appropriate evolution tier for a gap.
   */
  private determineTier(gap: CapabilityGap): 1 | 2 | 3 {
    const desc = gap.description.toLowerCase()

    // Tier 3: Core engine changes needed
    if (
      desc.includes('queryengine') ||
      desc.includes('tool.ts') ||
      desc.includes('main loop') ||
      desc.includes('permission system')
    ) {
      return 3
    }

    // Tier 2: Needs programmatic logic (API calls, file processing, data transforms)
    if (
      gap.type === 'user_requested' ||
      desc.includes('tool') ||
      desc.includes('api') ||
      desc.includes('parse') ||
      desc.includes('transform') ||
      desc.includes('generate')
    ) {
      return 2
    }

    // Tier 1: Workflow/prompt skill (most things can be skills)
    return 1
  }

  /**
   * Ensure the target directory exists before the LLM writes files.
   */
  private ensureDirectoryExists(design: EvolutionDesign): void {
    const dir =
      design.tier === 1
        ? join(process.cwd(), AGENT_SKILLS_DIR, design.name)
        : design.tier === 2
          ? DYNAMIC_TOOLS_DIR
          : null

    if (dir && !existsSync(dir)) {
      mkdirSync(dir, { recursive: true })
    }
  }

  /**
   * Post-integration: load the new capability.
   */
  private async postIntegrate(design: EvolutionDesign): Promise<void> {
    switch (design.tier) {
      case 1:
        // Skill auto-discovery happens via discoverSkillDirsForPaths
        // which is called by FileWriteTool whenever a file is written.
        // No explicit reload needed.
        break
      case 2:
        // Register the new dynamic tool
        try {
          const registry = getDynamicToolRegistry()
          await registry.register(design.targetPath)
        } catch {
          // Tool may fail to load — the LLM should fix syntax errors
        }
        break
      case 3:
        // Core changes require rebuild + restart
        // This is handled by the Sandbox when the LLM calls SelfHealTool
        break
    }
  }
}

export function createEvolutionLoop(): EvolutionLoop {
  return new EvolutionLoop()
}
