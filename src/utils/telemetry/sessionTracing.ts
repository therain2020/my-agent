export const startHookSpan = () => ({}) as unknown
export const endHookSpan = () => {}
export const isBetaTracingEnabled = () => false
export const startToolBlockedOnUserSpan = () => ({ end: () => {} })
export const startToolExecutionSpan = () => ({ end: () => {} })
export const endToolExecutionSpan = () => {}
export const startInteractionSpan = () => ({ end: () => {} })
export const endInteractionSpan = () => {}
export const endToolBlockedOnUserSpan = () => {}
export const endToolSpan = () => {}
export const addToolContentEvent = () => {}
export const endLLMRequestSpan = () => {}
export type Span = unknown
export const startToolSpan = () => ({ end: () => {} })
export const startLLMRequestSpan = () => ({ end: () => {} })
export type LLMRequestNewContext = unknown
