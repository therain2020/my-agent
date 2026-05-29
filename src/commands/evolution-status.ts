/**
 * /evolution-status — Display self-healing and self-evolution history.
 *
 * Shows counts, recent modifications, detected capability gaps,
 * and active evolved prompt sections.
 */
import type { Command } from '../types/command.js'

const evolutionStatusCommand: Command = {
  name: 'evolution-status',
  description: 'Show self-healing and self-evolution history and status',
  type: 'local-jsx',
  async call() {
    const fs = await import('fs')
    const journalPath = `${process.env.HOME ?? process.env.USERPROFILE ?? '.'}/.claude/evolution-journal.jsonl`
    const gapsPath = `${process.env.HOME ?? process.env.USERPROFILE ?? '.'}/.claude/capability-gaps.json`

    const lines: string[] = []

    // Heal/Evolve stats
    try {
      if (fs.existsSync(journalPath)) {
        const entries = fs
          .readFileSync(journalPath, 'utf-8')
          .trim()
          .split('\n')
          .filter(Boolean)
          .map(l => JSON.parse(l))

        const heals = entries.filter(
          (e: { type: string }) =>
            e.type === 'self_heal_applied' || e.type === 'self_heal_verified',
        )
        const evolutions = entries.filter(
          (e: { type: string }) =>
            e.type === 'evolution_integrated' || e.type === 'evolution_verified',
        )

        lines.push('## Self-Modification Stats')
        lines.push(`- Self-heals: ${heals.length}`)
        lines.push(`- Evolutions: ${evolutions.length}`)
        lines.push('')

        const recent = entries.slice(-5).reverse()
        if (recent.length > 0) {
          lines.push('### Recent Activity')
          for (const entry of recent) {
            const emoji = entry.type.includes('heal') ? '  [Heal]' : '  [Evolve]'
            lines.push(`- ${emoji} ${entry.description}`)
            lines.push(`  Files: ${(entry.files as string[]).join(', ') || 'none'}`)
            lines.push(`  Time: ${entry.timestamp}`)
          }
        }
      } else {
        lines.push('No self-modifications recorded yet.')
      }
    } catch {
      lines.push('Could not read evolution journal.')
    }

    lines.push('')

    // Capability gaps
    try {
      if (fs.existsSync(gapsPath)) {
        const gaps = JSON.parse(fs.readFileSync(gapsPath, 'utf-8'))
        const open = gaps.filter(
          (g: { status: string }) => g.status === 'open',
        )
        lines.push('### Open Capability Gaps')
        if (open.length === 0) {
          lines.push('No open gaps.')
        } else {
          for (const gap of open) {
            lines.push(`- [${gap.type}] ${gap.description}`)
            lines.push(`  Occurrences: ${gap.occurrences}`)
            lines.push(`  First seen: ${gap.firstSeen}`)
          }
        }
      }
    } catch {
      lines.push('No capability gaps recorded.')
    }

    return lines.join('\n')
  },
}

export default evolutionStatusCommand
