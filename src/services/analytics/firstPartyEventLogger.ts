/**
 * First-party event logger stub — OpenTelemetry removed.
 */

export type EventSamplingConfig = Record<string, never>

export function getEventSamplingConfig(): EventSamplingConfig { return {} }

export function shouldSampleEvent(_eventName: string): null { return null }

export async function shutdown1PEventLogging(): Promise<void> {}
export function logEventTo1P(): void {}
