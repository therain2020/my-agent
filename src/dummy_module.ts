// Phase 1: Track ALL async completions before createRoot yields
let pendingCount = 0
const origThen = Promise.prototype.then
Promise.prototype.then = function (onFulfilled: any, onRejected: any) {
  pendingCount++
  const wrappedFulfilled = onFulfilled ? function (v: any) {
    pendingCount--
    return onFulfilled(v)
  } : undefined
  const wrappedRejected = onRejected ? function (e: any) {
    pendingCount--
    if (e && !e._logged) {
      process.stderr.write(`[DBG] pending=${pendingCount} rejected: ${e?.stack || e}\n`)
      ;(e as any)._logged = true
    }
    return onRejected(e)
  } : undefined
  return origThen.call(this, wrappedFulfilled, wrappedRejected)
} as any

// Phase 2: Track setImmediate/nextTick
const origNextTick = process.nextTick
process.nextTick = function (cb: any, ...args: any[]) {
  process.stderr.write(`[DBG] nextTick enqueued, pending=${pendingCount}\n`)
  return origNextTick.call(process, cb, ...args)
} as any

// Phase 3: Override only process.exit, log stack
const origExit = process.exit
process.exit = function (code?: number) {
  process.stderr.write(`[FATAL] exit(${code}) pending=${pendingCount}\n${new Error().stack}\n`)
  origExit.call(process, code)
} as any

process.stderr.write("0 init\n")
