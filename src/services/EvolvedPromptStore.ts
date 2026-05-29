/**
 * EvolvedPromptStore — System prompt auto-evolution for therain2020-agent.
 *
 * Stores evolved prompt sections in ~/.claude/evolved-prompts/{name}.md.
 * These are loaded at session start and merged into the system prompt via
 * systemPromptSection('evolved_prompts', ...) registration.
 *
 * The agent can propose, apply, and rollback prompt evolutions.
 * Each evolution is a markdown file with a frontmatter block recording
 * the rationale, version, and verification status.
 */

import { homedir } from 'os'
import { join } from 'path'
import {
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  writeFileSync,
  unlinkSync,
} from 'fs'

const EVOLVED_PROMPTS_DIR = join(homedir(), '.claude', 'evolved-prompts')

interface EvolvedPromptSection {
  name: string
  content: string
  rationale: string
  version: number
  active: boolean
}

let store: EvolvedPromptStore | null = null

export class EvolvedPromptStore {
  private sections = new Map<string, EvolvedPromptSection>()

  static instance(): EvolvedPromptStore {
    if (!store) {
      store = new EvolvedPromptStore()
    }
    return store
  }

  /** Load all evolved prompt sections from disk at startup. */
  async loadAll(): Promise<void> {
    if (!existsSync(EVolved_PROMPTS_DIR)) {
      return
    }

    const files = readdirSync(EVolved_PROMPTS_DIR).filter(
      (f) => f.endsWith('.md'),
    )

    for (const file of files) {
      try {
        const content = readFileSync(
          join(EVolved_PROMPTS_DIR, file),
          'utf-8',
        )
        const parsed = this.parseFrontmatter(content)
        if (parsed) {
          this.sections.set(parsed.name, {
            name: parsed.name,
            content: parsed.body,
            rationale: parsed.rationale ?? '',
            version: parsed.version ?? 1,
            active: parsed.active ?? true,
          })
        }
      } catch {
        // Skip unparseable files
      }
    }
  }

  /** Propose a new prompt evolution (agent writes this). */
  async propose(
    name: string,
    content: string,
    rationale: string,
  ): Promise<EvolvePromptSection> {
    const section: EvolvePromptSection = {
      name,
      content,
      rationale,
      version: (this.sections.get(name)?.version ?? 0) + 1,
      active: true,
    }

    this.sections.set(name, section)
    await this.persist(name, section)
    return section
  }

  /** Apply a proposed evolution (activate it). */
  async apply(name: string): Promise<void> {
    const section = this.sections.get(name)
    if (section) {
      section.active = true
      await this.persist(name, section)
    }
  }

  /** Rollback (deactivate or delete) an evolution. */
  async rollback(name: string): Promise<void> {
    const section = this.sections.get(name)
    if (section) {
      section.active = false
      await this.persist(name, section)
    }
  }

  /** Delete an evolution permanently. */
  async delete(name: string): Promise<void> {
    this.sections.delete(name)
    const filePath = join(EVolved_PROMPTS_DIR, `${name}.md`)
    if (existsSync(filePath)) {
      unlinkSync(filePath)
    }
  }

  /** Get content of all active evolutions, merged into one string. */
  getActiveContent(): string {
    const active = [...this.sections.values()].filter((s) => s.active)
    if (active.length === 0) return ''

    return active
      .map(
        (s, i) =>
          `## Evolved Guideline ${i + 1}: ${s.name}
${s.content}`,
      )
      .join('\n\n')
  }

  /** List all sections for /evolution-status. */
  listAll(): EvolvePromptSection[] {
    return [...this.sections.values()]
  }

  // -- private helpers --

  private parseFrontmatter(raw: string): {
    name: string
    body: string
    rationale?: string
    version?: number
    active?: boolean
  } | null {
    const match = raw.match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/)
    if (!match) return null

    const header = match[1]!
    const body = match[2]!

    const parsed: Record<string, string> = {}
    for (const line of header.split('\n')) {
      const kv = line.match(/^(\w+):\s*(.*)$/)
      if (kv) {
        parsed[kv[1]!] = kv[2]!
      }
    }

    return {
      name: parsed.name ?? 'unnamed',
      body: body.trim(),
      rationale: parsed.rationale,
      version: parsed.version ? parseInt(parsed.version, 10) : undefined,
      active: parsed.active !== 'false',
    }
  }

  private async persist(
    name: string,
    section: EvolvePromptSection,
  ): Promise<void> {
    if (!existsSync(EVolved_PROMPTS_DIR)) {
      mkdirSync(EVolved_PROMPTS_DIR, { recursive: true })
    }

    const frontmatter = [
      `name: ${section.name}`,
      `rationale: ${section.rationale}`,
      `version: ${section.version}`,
      `active: ${section.active}`,
    ].join('\n')

    const fileContent = `---\n${frontmatter}\n---\n\n${section.content}\n`
    writeFileSync(join(EVolved_PROMPTS_DIR, `${name}.md`), fileContent, {
      encoding: 'utf-8',
    })
  }
}

export function getEvolvedPromptStore(): EvolvedPromptStore {
  return EvolvedPromptStore.instance()
}
