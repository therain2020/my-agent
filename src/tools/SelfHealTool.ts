/**
 * SelfHealTool — Allows the agent to trigger self-healing.
 *
 * When the agent detects a bug in its own tools, skills, or services,
 * it calls this tool to enter self-modification mode, apply a fix,
 * and exit safely. The SelfModService orchestrates the process.
 */

import { z } from 'zod/v4'
import { buildTool } from '../Tool.js'
import { getSelfModService } from '../services/SelfModService/SelfModService.js'

const inputSchema = z.strictObject({
  toolName: z.string().describe('Name of the broken tool to fix'),
  errorDescription: z.string().describe('Description of the bug or error'),
  affectedFiles: z.array(z.string()).describe('Source files that need modification'),
  fixDescription: z.string().describe('Description of the planned fix'),
})

export const SelfHealTool = buildTool({
  name: 'SelfHealTool',
  description: () => `Triggers self-healing: fixes bugs in the agent's own source code. Call when you detect a bug in your own tools, skills, or services. Enter self-modification mode, apply the fix, and exit safely.`,
  searchHint: 'self-healing fix repair auto-fix',
  inputSchema,
  outputSchema: z.object({ status: z.string(), modifiedFiles: z.array(z.string()), message: z.string() }),

  isEnabled: () => true,
  isReadOnly: () => false,
  isDestructive: () => true,
  isConcurrencySafe: () => false,
  maximumResultSizeChars: 10000,

  async call(input, context) {
    const service = getSelfModService()

    service.enterSelfModMode(context.options.toolPermissionContext)

    const result = await service.heal(
      {
        toolName: input.toolName,
        toolInput: input,
        error: input.errorDescription,
        isInterrupt: false,
        timestamp: new Date().toISOString(),
      },
      context.options.toolPermissionContext,
    )

    service.exitSelfModMode(context.options.toolPermissionContext)

    return {
      data: {
        status: result.status,
        modifiedFiles: result.modifiedFiles,
        message: result.status === 'applied'
          ? `Self-heal applied to ${input.toolName}. Modified: ${result.modifiedFiles.join(', ')}. Verification running in background.`
          : `Self-heal failed: ${result.error ?? 'unknown error'}`,
      },
    }
  },

  renderToolUseMessage(input) {
    return `Self-healing ${input.toolName}: ${input.errorDescription.slice(0, 100)}`
  },

  renderToolResultMessage(output) {
    return output.data.status === 'applied'
      ? `Self-heal applied. Modified: ${output.data.modifiedFiles.join(', ')}`
      : `Self-heal failed: ${output.data.message}`
  },

  mapToolResultToToolResultBlockParam(output, toolUseID) {
    return {
      type: 'tool_result',
      content: `Status: ${output.data.status}\nFiles: ${output.data.modifiedFiles.join(', ')}\n${output.data.message}`,
      tool_use_id: toolUseID,
    }
  },
})
