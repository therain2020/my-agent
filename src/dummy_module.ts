process.stderr.write("[DIAG] imports starting...\n")
process.on('uncaughtException', (err) => {
  process.stderr.write(`[DIAG] UNCAUGHT: ${err.stack || err.message || String(err)}\n`)
  process.exit(1)
})
process.on('unhandledRejection', (reason, promise) => {
  const msg = reason instanceof Error ? (reason.stack || reason.message) : String(reason)
  process.stderr.write(`[DIAG] UNHANDLED REJECTION: ${msg}\n`)
})
