/**
 * OpenTelemetry stubs for therain2020-agent.
 * OTEL removed — all types and classes are empty/noop.
 */

// @opentelemetry/api
export type Attributes = Record<string, unknown>
export type MetricOptions = Record<string, unknown>
export interface Meter { }
export interface Tracer { }

// @opentelemetry/api-logs
export const logs = { getLogger: () => null as unknown }

// @opentelemetry/sdk-logs
export type LoggerProvider = unknown

// @opentelemetry/sdk-metrics
export type MeterProvider = unknown

// @opentelemetry/sdk-trace-base
export type BasicTracerProvider = unknown
