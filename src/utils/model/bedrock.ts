/**
 * Bedrock model strings stub — AWS Bedrock removed.
 * Returns empty results so callers fall back to built-in model strings.
 */

export function findFirstMatch(): undefined { return undefined }
export function getBedrockInferenceProfiles(): string[] { return [] }
export function applyBedrockRegionPrefix(model: string, _prefix?: string): string { return model }
export function getBedrockRegionPrefix(): string { return '' }
export function isFoundationModel(_model: string): boolean { return false }
export function createBedrockRuntimeClient(): null { return null }
export function getInferenceProfileBackingModel(_model: string): string { return _model }
