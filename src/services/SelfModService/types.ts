/**
 * Type definitions for therain2020-agent SelfModService.
 */

export interface ToolFailure {
  toolName: string
  toolInput: unknown
  error: string
  isInterrupt: boolean
  timestamp: string
}

export interface Diagnosis {
  bugDescription: string
  rootCause: string
  affectedFiles: string[]
  suggestedFix: string
  tier: 1 | 2 | 3
  confidence: number
}

export type HealStatus = 'diagnosing' | 'fixing' | 'verifying' | 'applied' | 'rolled_back' | 'failed'

export interface HealResult {
  status: HealStatus
  diagnosis: Diagnosis
  modifiedFiles: string[]
  checkpointId?: string
  error?: string
  journalEntry?: JournalEntry
}

export interface CapabilityGap {
  id: string
  type: 'missing_tool' | 'broken_behavior' | 'user_requested'
  description: string
  occurrences: number
  firstSeen: string
  lastSeen: string
  status: 'open' | 'designing' | 'implementing' | 'verifying' | 'integrated' | 'failed'
}

export type GapSignal =
  | { source: 'tool_failure'; toolName: string; errorPattern: string; count: number }
  | { source: 'user_request'; capability: string }
  | { source: 'self_analysis'; gap: string }

export interface EvolutionDesign {
  gapId: string
  tier: 1 | 2 | 3
  name: string
  description: string
  approach: string
  code: string
  targetPath: string
}

export type EvolveStatus = 'designing' | 'generating' | 'validating' | 'integrating' | 'verifying' | 'integrated' | 'failed'

export interface EvolveResult {
  status: EvolveStatus
  gapId: string
  design: EvolutionDesign
  createdFiles: string[]
  checkpointId?: string
  error?: string
  journalEntry?: JournalEntry
}

export type JournalEventType =
  | 'self_heal_start'
  | 'self_heal_applied'
  | 'self_heal_rollback'
  | 'self_heal_verified'
  | 'evolution_start'
  | 'evolution_integrated'
  | 'evolution_rollback'
  | 'evolution_verified'

export interface JournalEntry {
  type: JournalEventType
  sessionId: string
  description: string
  files: string[]
  tier: number
  timestamp: string
  verdict?: 'PASS' | 'FAIL'
  error?: string
}
