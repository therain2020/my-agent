process.stderr.write("[DIAG] imports starting...\n")
process.on('uncaughtException', (err) => {
  process.stderr.write(`[DIAG] UNCAUGHT: ${err.stack || err.message}\n`)
  process.exit(1)
})
process.on('unhandledRejection', (reason) => {
  process.stderr.write(`[DIAG] UNHANDLED REJECTION: ${(reason as Error).stack || reason}\n`)
})
