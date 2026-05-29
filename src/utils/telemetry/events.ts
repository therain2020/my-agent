/**
 * Telemetry events stub for therain2020-agent.
 * OpenTelemetry removed — all event logging is no-op.
 */

// eslint-disable-next-line @typescript-eslint/no-explicit-any, @typescript-eslint/no-unused-vars
export function logOTelEvent(_name: string, _attributes?: Record<string, any>): void {}

export function redactIfDisabled(): boolean { return false }

export function startInteractionSpan(): { end: () => void } { return { end() {} } }
