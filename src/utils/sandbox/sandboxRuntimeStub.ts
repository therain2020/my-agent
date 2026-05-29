/**
 * Stub for @anthropic-ai/sandbox-runtime.
 * Returns "not supported" for all sandbox operations so agent runs without OS isolation.
 */
import { z } from 'zod'

// eslint-disable-next-line @typescript-eslint/no-extraneous-class
export class SandboxManager {
  static checkDependencies(): { ok: boolean } {
    return { ok: true }
  }

  static isSupportedPlatform(): boolean {
    return false
  }

  static async wrapWithSandbox(
    command: string,
    _binShell?: unknown,
    _customConfig?: unknown,
    _abortSignal?: AbortSignal,
  ): Promise<string> {
    return command
  }

  static async initialize(
    _runtimeConfig: unknown,
    _callback?: unknown,
  ): Promise<void> {}

  static getConfig(): unknown {
    return null
  }
}

// eslint-disable-next-line @typescript-eslint/no-extraneous-class
export class SandboxViolationStore {
  static instance(): SandboxViolationStore {
    return new SandboxViolationStore()
  }
}

export const SandboxRuntimeConfigSchema = z.object({})

export type SandboxDependencyCheck = { ok: boolean }
export type SandboxRuntimeConfig = Record<string, unknown>
export type SandboxViolationEvent = Record<string, unknown>
export type SandboxAskCallback = (hostPattern: NetworkHostPattern) => Promise<{ allow: boolean }>
export type NetworkHostPattern = string
