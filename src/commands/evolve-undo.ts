/**
 * /evolve-undo — Rollback the most recent self-modification.
 *
 * Reads the evolution journal to find the last modification and attempts
 * to rollback using git or FileHistory checkpoint.
 */
import type { Command } from '../types/command.js'

const evolveUndoCommand: Command = {
  name: 'evolve-undo',
  description: 'Rollback the most recent self-heal or self-evolution modification',
  type: 'local-jsx',
  async call() {
    const fs = await import('fs')
    const { execFileSync } = await import('child_process')
    const journalPath = `${process.env.HOME ?? process.env.USERPROFILE ?? '.'}/.claude/evolution-journal.jsonl`

    // Read journal to find last modification
    let lastEntry: Record<string, unknown> | null = null
    try {
      if (fs.existsSync(journalPath)) {
        const lines = fs.readFileSync(journalPath, 'utf-8').trim().split('\n')
        const lastLine = lines[lines.length - 1] ?? ''
        if (lastLine) {
          lastEntry = JSON.parse(lastLine)
        }
      }
    } catch {
      return 'No evolution journal found. Nothing to undo.'
    }

    if (!lastEntry) {
      return 'No previous self-modifications found. Nothing to undo.'
    }

    // Attempt git revert for the last modification
    try {
      const files = lastEntry.files as string[] | undefined
      if (files && files.length > 0) {
        execFileSync('git', ['checkout', '--', ...files])
        return `Rolled back ${files.length} file(s) from: ${lastEntry.description}\n\nFiles restored: ${files.join(', ')}`
      }
    } catch {
      return `Could not automatically rollback. Last modification: ${lastEntry.description}\nTry: git checkout -- <files>`
    }

    return `Last modification: ${lastEntry.description}\nUse git to manually rollback if needed.`
  },
}

export default evolveUndoCommand
