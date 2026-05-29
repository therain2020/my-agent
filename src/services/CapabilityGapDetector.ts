/**
 * CapabilityGapDetector — Detects when the agent lacks capabilities.
 *
 * Three signal sources:
 *   1. PostToolUseFailure — same tool failing repeatedly → self-heal trigger
 *   2. UserPromptSubmit — user requests unsupported feature → evolution trigger
 *   3. Self-analysis — scan SessionMemory for unresolved error patterns
 *
 * Detection triggers immediate pipeline execution — no confirmation, no throttling.
 */

import type { ToolPermissionContext } from '../../types/permissions.js'
import { getSelfModService } from '../SelfModService/SelfModService.js'
import type { CapabilityGap, GapSignal, ToolFailure } from '../SelfModService/types.js'

const GAPS_PATH = `${process.env.HOME ?? process.env.USERPROFILE ?? '.'}/.claude/capability-gaps.json`

let instance: CapabilityGapDetector | null = null

export class CapabilityGapDetector {
  private gaps = new Map<string, CapabilityGap>()
  private failureCounts = new Map<string, number>() // key: toolName::errorPattern
  private loaded = false

  static get(): CapabilityGapDetector {
    if (!instance) {
      instance = new CapabilityGapDetector()
    }
    return instance
  }

  /** Load previous gaps from disk. */
  async load(): Promise<void> {
    if (this.loaded) return
    try {
      const fs = await import('fs')
      if (fs.existsSync(GAPS_PATH)) {
        const data = JSON.parse(fs.readFileSync(GAPS_PATH, 'utf-8'))
        for (const g of data as CapabilityGap[]) {
          this.gaps.set(g.id, g)
        }
      }
    } catch {
      // First run, no gaps yet
    }
    this.loaded = true
  }

  /** Called on every tool failure. Triggers self-heal after 2+ repeated failures. */
  async onToolFailure(
    failure: ToolFailure,
    permissionContext: ToolPermissionContext,
  ): Promise<void> {
    // Track failure count
    const key = `${failure.toolName}::${this.extractPattern(failure.error)}`
    const count = (this.failureCounts.get(key) ?? 0) + 1
    this.failureCounts.set(key, count)

    // After 2 repeated failures → auto-trigger self-heal
    if (count >= 2) {
      const service = getSelfModService()
      await service.heal(failure, permissionContext)
    }
  }

  /** Called when user prompt indicates a missing capability. */
  async onGapDetected(
    signal: GapSignal,
    permissionContext: ToolPermissionContext,
  ): Promise<void> {
    const id = `gap-${Date.now()}`
    const gap: CapabilityGap = {
      id,
      type: signal.source === 'user_request'
        ? 'user_requested'
        : signal.source === 'tool_failure'
          ? 'broken_behavior'
          : 'missing_tool',
      description:
        signal.source === 'tool_failure'
          ? `${signal.toolName}: ${signal.errorPattern} (${signal.count}x)`
          : signal.source === 'user_request'
            ? `User requested: ${signal.capability}`
            : signal.gap,
      occurrences: signal.source === 'tool_failure' ? signal.count : 1,
      firstSeen: new Date().toISOString(),
      lastSeen: new Date().toISOString(),
      status: 'open',
    }

    this.gaps.set(id, gap)
    await this.save()

    // Auto-trigger evolution
    const service = getSelfModService()
    await service.evolve(gap, signal, permissionContext)
  }

  /** Get all open gaps for status display. */
  getOpenGaps(): CapabilityGap[] {
    return [...this.gaps.values()].filter(g => g.status === 'open')
  }

  /** Get all gaps including resolved. */
  getAllGaps(): CapabilityGap[] {
    return [...this.gaps.values()]
  }

  /** Mark a gap as resolved. */
  markResolved(id: string): void {
    const gap = this.gaps.get(id)
    if (gap) {
      gap.status = 'integrated'
      this.save()
    }
  }

  // --- private helpers ---

  private extractPattern(error: string): string {
    // Extract a stable error signature (first 80 chars, strip timestamps/UUIDs)
    return error
      .replace(/\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/gi, '<UUID>')
      .replace(/\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\b/g, '<TIME>')
      .slice(0, 80)
      .trim()
  }

  private async save(): Promise<void> {
    try {
      const fs = await import('fs')
      fs.writeFileSync(GAPS_PATH, JSON.stringify([...this.gaps.values()], null, 2), 'utf-8')
    } catch {
      // Best-effort persistence
    }
  }
}

export function getCapabilityGapDetector(): CapabilityGapDetector {
  return CapabilityGapDetector.get()
}
