/**
 * Sandbox — Safe self-modification for therain2020-agent.
 *
 * Tier 1/2: Lightweight — FileHistory checkpoint + direct file edit.
 * Tier 3:   Full sandbox — git worktree isolate → edit → bun build → verify → merge + restart.
 */

import { execFileSync } from 'child_process'
import { randomUUID } from 'crypto'
import { existsSync, mkdirSync, readFileSync, writeFileSync, rmSync } from 'fs'
import { join } from 'path'
import { getOriginalCwd } from '../../bootstrap/state.js'

interface WorktreeSession {
  id: string
  worktreePath: string
  branch: string
  sourceRoot: string
}

export class Sandbox {
  private checkpoints = new Map<string, Map<string, string>>() // checkpointId -> (filePath -> content)

  /** Lightweight checkpoint: save current content of files for rollback. */
  checkpoint(files: string[]): string {
    const id = randomUUID()
    const snapshot = new Map<string, string>()

    for (const f of files) {
      try {
        snapshot.set(f, readFileSync(f, 'utf-8'))
      } catch {
        // File may not exist yet — that's fine
      }
    }

    this.checkpoints.set(id, snapshot)
    return id
  }

  /** Lightweight rollback: restore files from checkpoint. */
  rollback(checkpointId: string): boolean {
    const snapshot = this.checkpoints.get(checkpointId)
    if (!snapshot) return false

    for (const [filePath, content] of snapshot) {
      try {
        writeFileSync(filePath, content, 'utf-8')
      } catch {
        // If we can't restore, skip — the file may have been created by this change
      }
    }

    this.checkpoints.delete(checkpointId)
    return true
  }

  /** Full sandbox: create an isolated git worktree for Tier 3 modifications. */
  createWorktree(sourceRoot?: string): WorktreeSession {
    const root = sourceRoot ?? getOriginalCwd()
    const id = randomUUID()
    const branch = `selfmod-${id.slice(0, 8)}`
    const worktreePath = join(root, '.claude', 'worktrees', branch)

    try {
      // Create branch from current HEAD
      execFileSync('git', ['branch', branch], { cwd: root })
      // Create worktree
      execFileSync('git', ['worktree', 'add', worktreePath, branch], {
        cwd: root,
      })
    } catch (err) {
      throw new Error(
        `Failed to create worktree: ${(err as Error).message}`,
      )
    }

    return { id, worktreePath, branch, sourceRoot: root }
  }

  /** Merge worktree back to main branch. */
  mergeWorktree(session: WorktreeSession): void {
    try {
      execFileSync('git', ['checkout', session.branch], {
        cwd: session.sourceRoot,
      })
      execFileSync('git', ['checkout', 'master'], {
        cwd: session.sourceRoot,
      })
      execFileSync('git', ['merge', session.branch], {
        cwd: session.sourceRoot,
      })
      execFileSync('git', ['branch', '-d', session.branch], {
        cwd: session.sourceRoot,
      })
      // Clean up worktree
      execFileSync('git', ['worktree', 'remove', session.worktreePath, '--force'], {
        cwd: session.sourceRoot,
      })
    } catch (err) {
      throw new Error(
        `Failed to merge worktree: ${(err as Error).message}`,
      )
    }
  }

  /** Discard worktree without merging (on verification failure). */
  discardWorktree(session: WorktreeSession): void {
    try {
      execFileSync('git', ['worktree', 'remove', session.worktreePath, '--force'], {
        cwd: session.sourceRoot,
      })
      execFileSync('git', ['branch', '-D', session.branch], {
        cwd: session.sourceRoot,
      })
    } catch {
      // Best-effort cleanup
    }
  }

  /** Build and restart for Tier 3 changes. */
  rebuildAndRestart(sourceRoot?: string): boolean {
    const root = sourceRoot ?? getOriginalCwd()
    try {
      execFileSync('bun', ['build', '--target=bun', '--outdir=dist/'], {
        cwd: root,
        stdio: 'inherit',
      })
      return true
    } catch {
      return false
    }
  }
}

export function createSandbox(): Sandbox {
  return new Sandbox()
}
