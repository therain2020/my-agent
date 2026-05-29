export const DEFAULT_UPLOAD_CONCURRENCY = 3
export const FILE_COUNT_LIMIT = 100
export const OUTPUTS_SUBDIR = 'outputs'

export interface FailedPersistence {
  file: string
  error: string
}

export interface PersistedFile {
  path: string
  size: number
  persistedAt: number
}

export interface FilesPersistedEventData {
  files: PersistedFile[]
  failed: FailedPersistence[]
}

export type TurnStartTime = number
