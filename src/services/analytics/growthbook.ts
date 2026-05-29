/**
 * GrowthBook stub for therain2020-agent.
 *
 * All feature gates return false/null (feature off).
 * All init/refresh functions are no-ops.
 *
 * This matches GrowthBook's own fallback behavior when the server is unreachable.
 */

// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function checkStatsigFeatureGate_CACHED_MAY_BE_STALE(_key: string): boolean {
  return false
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function getFeatureValue_CACHED_MAY_BE_STALE(_key: string): null {
  return null
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function getFeatureValue_CACHED_WITH_REFRESH(_key: string): null {
  return null
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function getFeatureValue_DEPRECATED(_key: string): null {
  return null
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function getDynamicConfig_CACHED_MAY_BE_STALE(_key: string): null {
  return null
}

export function initializeGrowthBook(): void {}
export function refreshGrowthBookAfterAuthChange(): void {}
export function checkGate_CACHED_OR_BLOCKING(): boolean { return false }
export function hasGrowthBookEnvOverride(): boolean { return false }
export function getDynamicConfig_BLOCKS_ON_INIT(): null { return null }
export function checkSecurityRestrictionGate(): boolean { return false }
export function resetGrowthBook(): void {}
