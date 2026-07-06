// tools/goal-tools.ts — model-side goal tools (ember issue #211, spec §2):
// get_goal (read), create_goal (fails if one exists), update_goal (STATUS
// ONLY). Objective immutability is enforced in TWO independent layers so a
// single bug can't smuggle a rewrite through:
//   1. update_goal's zod schema has NO objective field at all (.strict()
//      rejects any extra key a model tries to add), so there is no wire shape
//      that could carry one.
//   2. core/goal-store.ts's updateStatus() signature never accepts an
//      objective parameter either -- even a hand-modified caller can't pass one.
//
// update_goal's allowed target statuses are deliberately narrower than the
// full GoalStatus enum: "UsageLimited" and "BudgetLimited" are SYSTEM-managed
// transitions (a real provider error, a real token tally crossing the real
// budget) applied directly by goal-runtime/goal-continuation, never something
// the model can assert about itself -- otherwise a model under budget pressure
// could self-report a fake limit to avoid the completion audit. This is one of
// this port's "then improve" deltas (spec §7).

import { z } from "zod";
import { buildTool } from "../core/tool-interface.ts";
import type { ToolUseContext } from "../core/tool-interface.ts";
import { getGoalStore, isCurrentSessionEphemeral } from "../core/goal-runtime.ts";
import type { GoalStatus } from "../core/goal-store.ts";

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

function resolveIsEphemeral(context: ToolUseContext): boolean {
  return isCurrentSessionEphemeral(context);
}

// ---------------------------------------------------------------------------
// get_goal — read-only
// ---------------------------------------------------------------------------

const GetGoalInputSchema = z.object({}).strict();
export type GetGoalInput = z.infer<typeof GetGoalInputSchema>;

export const GetGoalTool = buildTool<GetGoalInput, unknown>({
  name: "get_goal",
  inputSchema: GetGoalInputSchema,
  isReadOnly: () => true,
  isConcurrencySafe: () => true,

  call: async (_rawArgs: unknown, _context: ToolUseContext) => {
    const goal = getGoalStore().getGoal();
    if (!goal) {
      return { data: { exists: false, message: "no active goal" } };
    }
    return {
      data: {
        exists: true,
        goalId: goal.goalId,
        objective: goal.objective,
        status: goal.status,
        tokenBudget: goal.tokenBudget,
        usage: goal.usage,
        consecutiveBlockedTurns: goal.consecutiveBlockedTurns,
      },
    };
  },

  description: () =>
    "Reads the current goal (objective, status, token budget, usage). Returns exists:false when no goal is set.",

  mapToolResultToToolResultBlockParam: (content, toolUseId) => ({
    type: "tool_result" as const,
    tool_use_id: toolUseId,
    content: JSON.stringify(content),
  }),
});

// ---------------------------------------------------------------------------
// create_goal — fails if one already exists; never inferred, only explicit
// ---------------------------------------------------------------------------

const CreateGoalInputSchema = z
  .object({
    objective: z.string(),
    tokenBudget: z.number().positive().optional(),
  })
  .strict();
export type CreateGoalInput = z.infer<typeof CreateGoalInputSchema>;

export const CreateGoalTool = buildTool<CreateGoalInput, unknown>({
  name: "create_goal",
  inputSchema: CreateGoalInputSchema,
  isReadOnly: () => false,
  isConcurrencySafe: () => false,

  validateInput: (rawInput: unknown) => {
    const parsed = CreateGoalInputSchema.safeParse(rawInput);
    if (!parsed.success) {
      return { result: false as const, message: parsed.error.message, errorCode: "INVALID_INPUT" };
    }
    return { result: true as const };
  },

  call: async (rawArgs: unknown, context: ToolUseContext) => {
    const args = rawArgs as CreateGoalInput;
    const store = getGoalStore();
    const result = store.createGoal(args.objective, {
      ...(args.tokenBudget !== undefined ? { tokenBudget: args.tokenBudget } : {}),
      isEphemeralSession: resolveIsEphemeral(context),
    });
    if (!result.ok) {
      return { data: { ok: false, message: result.message } };
    }
    return { data: { ok: true, goal: result.goal } };
  },

  description: () =>
    "Creates a new goal with the given objective. ONLY call this when explicitly requested by " +
    "the operator -- never infer a goal from an ordinary task. Fails if a goal already exists.",

  mapToolResultToToolResultBlockParam: (content, toolUseId) => {
    const data = content as { ok: boolean; message?: string };
    return {
      type: "tool_result" as const,
      tool_use_id: toolUseId,
      content: JSON.stringify(content),
      is_error: data.ok === false,
    };
  },
});

// ---------------------------------------------------------------------------
// update_goal — STATUS ONLY. No objective field exists in this schema.
// ---------------------------------------------------------------------------

/** The statuses a MODEL call may target. UsageLimited/BudgetLimited are
 *  deliberately excluded -- see file header. */
const MODEL_SETTABLE_STATUSES = ["Active", "Paused", "Blocked", "Complete"] as const;
type ModelSettableStatus = (typeof MODEL_SETTABLE_STATUSES)[number];

const UpdateGoalInputSchema = z
  .object({
    status: z.enum(MODEL_SETTABLE_STATUSES),
    reason: z.string().optional(),
  })
  .strict();
export type UpdateGoalInput = z.infer<typeof UpdateGoalInputSchema>;

export const UpdateGoalTool = buildTool<UpdateGoalInput, unknown>({
  name: "update_goal",
  inputSchema: UpdateGoalInputSchema,
  isReadOnly: () => false,
  isConcurrencySafe: () => false,

  validateInput: (rawInput: unknown) => {
    const parsed = UpdateGoalInputSchema.safeParse(rawInput);
    if (!parsed.success) {
      // .strict() rejects any extra key -- including a model attempting to pass
      // "objective" alongside status -- with exactly this error path.
      return { result: false as const, message: parsed.error.message, errorCode: "INVALID_INPUT" };
    }
    return { result: true as const };
  },

  call: async (rawArgs: unknown, _context: ToolUseContext) => {
    const args = rawArgs as UpdateGoalInput;
    const store = getGoalStore();
    const status: GoalStatus = args.status as ModelSettableStatus;

    // BLOCKED AUDIT (spec §4): "never blocked merely because the work is hard,
    // slow, uncertain, incomplete" -- this is the one completion-adjacent gate
    // that IS code-checkable (a counter threshold), so it's enforced here
    // rather than left entirely to doctrine-text compliance. A Blocked call
    // must name its reason (so the "same blocker" audit has something to
    // compare) and is rejected -- without transitioning the goal -- until the
    // SAME reason has repeated on 3+ consecutive goal turns.
    if (status === "Blocked") {
      if (!args.reason || args.reason.trim().length === 0) {
        return {
          data: {
            ok: false,
            message: "update_goal(status: 'Blocked') requires a 'reason' so the blocked audit can track repetition",
          },
        };
      }
      const audit = store.noteBlocked(args.reason);
      if (!audit.readyToBlock) {
        return {
          data: {
            ok: false,
            message:
              `not blocked yet: this blocker has repeated ${audit.consecutiveBlockedTurns} consecutive ` +
              `goal turn(s); keep working -- Blocked requires the SAME blocker on 3+ consecutive turns`,
          },
        };
      }
    }

    const result = store.updateStatus(status, args.reason !== undefined ? { reason: args.reason } : {});
    if (!result.ok) {
      return { data: { ok: false, message: result.message } };
    }
    return { data: { ok: true, goal: result.goal } };
  },

  description: () =>
    "Updates the CURRENT goal's status only (active/paused/blocked/complete). The objective " +
    "itself can never be changed through this tool -- only the operator's /goal command can " +
    "edit it. Only mark 'Complete' after a requirement-by-requirement completion audit proves " +
    "it; only mark 'Blocked' after the same blocker has repeated on 3+ consecutive goal turns.",

  mapToolResultToToolResultBlockParam: (content, toolUseId) => {
    const data = content as { ok: boolean; message?: string };
    return {
      type: "tool_result" as const,
      tool_use_id: toolUseId,
      content: JSON.stringify(content),
      is_error: data.ok === false,
    };
  },
});

export const GOAL_TOOLS = [GetGoalTool, CreateGoalTool, UpdateGoalTool];
