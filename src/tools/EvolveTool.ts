/**
 * EvolveTool — Allows the agent to trigger self-evolution.
 *
 * When the agent discovers it lacks a capability, it calls this tool to
 * design and install a new skill, dynamic tool, or engine modification.
 * The EvolutionLoop orchestrates the full lifecycle.
 */

import { z } from 'zod/v4'
import { buildTool } from '../Tool.js'
import { getSelfModService } from '../services/SelfModService/SelfModService.js'
import { getCapabilityGapDetector } from '../services/CapabilityGapDetector.js'
import { createEvolutionLoop } from '../services/SelfModService/EvolutionLoop.js'

const inputSchema = z.strictObject({
  capability: z.string().describe('What new capability is needed'),
  reason: z.string().describe('Why this capability is needed (context)'),
  suggestion: z.string().optional().describe('Suggested approach for implementing the capability'),
})

export const EvolveTool = buildTool({
  name: 'EvolveTool',
  description: () => `Triggers self-evolution: creates a new tool, skill, or engine modification to add a missing capability. Call when you discover you cannot do something the user needs.`,
  searchHint: 'self-evolution grow new capability install create',
  inputSchema,
  outputSchema: z.object({
    status: z.string(),
    tier: z.number(),
    createdFiles: z.array(z.string()),
    message: z.string(),
  }),

  isEnabled: () => true,
  isReadOnly: () => false,
  isDestructive: () => false,
  isConcurrencySafe: () => false,
  maximumResultSizeChars: 10000,

  async call(input, context) {
    const service = getSelfModService()
    const detector = getCapabilityGapDetector()
    const evolutionLoop = createEvolutionLoop()

    // Detect or create a gap
    const existingGaps = detector.getOpenGaps()
    const existing = existingGaps.find(
      g => g.description.toLowerCase().includes(input.capability.toLowerCase()),
    )

    const gap = existing ?? {
      id: `gap-${Date.now()}`,
      type: 'user_requested' as const,
      description: input.capability,
      occurrences: 1,
      firstSeen: new Date().toISOString(),
      lastSeen: new Date().toISOString(),
      status: 'open' as const,
    }

    // Execute evolution
    const result = await evolutionLoop.execute(gap, context.options.toolPermissionContext)

    return {
      data: {
        status: result.status,
        tier: result.design.tier,
        createdFiles: result.createdFiles,
        message:
          result.status === 'integrated'
            ? `Evolution complete (Tier ${result.design.tier}). Created: ${result.createdFiles.join(', ')}. Approach: ${result.design.approach}`
            : `Evolution failed: ${result.error ?? 'unknown error'}`,
      },
    }
  },

  renderToolUseMessage(input) {
    return `Evolving: creating "${input.capability}" capability`
  },

  renderToolResultMessage(output) {
    return output.data.status === 'integrated'
      ? `Evolution complete (Tier ${output.data.tier}): ${output.data.createdFiles.join(', ')}`
      : `Evolution failed: ${output.data.message}`
  },

  mapToolResultToToolResultBlockParam(output, toolUseID) {
    return {
      type: 'tool_result',
      content: `Status: ${output.data.status} (Tier ${output.data.tier})\nFiles: ${output.data.createdFiles.join(', ')}\n${output.data.message}`,
      tool_use_id: toolUseID,
    }
  },
})
