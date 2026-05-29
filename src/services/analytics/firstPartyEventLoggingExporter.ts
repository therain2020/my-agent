/**
 * First-party event logging exporter stub — OpenTelemetry removed.
 */

export const ExportResultCode = { SUCCESS: 0, FAILED: 1 } as const
export type ExportResult = { code: number; error?: Error }

export class FirstPartyEventLoggingExporter {
  async export(): Promise<ExportResult> { return { code: 0 } }
  async shutdown(): Promise<void> {}
  async forceFlush(): Promise<void> {}
}
