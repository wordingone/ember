// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// Plan mode tools (EnterPlanMode + ExitPlanMode) — behavioral spec implementation.
//
// Two paired tools implementing a deliberate design-before-code gate.
// EnterPlanMode switches the session into a read-only planning state.
// ExitPlanMode presents the plan for approval and restores the previous mode.

import { z } from "zod";
import { buildTool } from "../core/tool-interface.ts";
import type { ToolResult } from "../core/tool-interface.ts";
import type { ToolUseContext } from "../core/tool-use-context.ts";
import type { PermissionMode } from "../types/permission-types.ts";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { dirname } from "node:path";
import { emberStatePath } from "../utils/ember-state-root.ts";

// --- AppState keys (well-known dynamic keys for permission mode tracking) ---

/** Key under which the effective permission context is stored in AppState. */
const PERMISSION_CTX_KEY = "toolPermissionContext";

interface StoredPermissionCtx {
  mode: PermissionMode;
  prePlanMode?: PermissionMode;
}

function getStoredPermCtx(context: ToolUseContext): StoredPermissionCtx {
  const state = context.getAppState() as Record<string, unknown>;
  return (state[PERMISSION_CTX_KEY] as StoredPermissionCtx | undefined) ?? { mode: "default" };
}

async function setStoredPermCtx(
  context: ToolUseContext,
  ctx: StoredPermissionCtx
): Promise<void> {
  await context.setAppState((prev) => ({
    ...(prev as Record<string, unknown>),
    [PERMISSION_CTX_KEY]: ctx,
  }));
}

// --- Plan file path ---

const PLAN_FILE_NAME = "plan.md";

function getPlanFilePath(cwd: string): string {
  return emberStatePath(cwd, PLAN_FILE_NAME);
}

// --- Feature flag hooks ---

/** Returns true when KAIROS channel integration is active with channels configured.
 *  When true, both plan-mode tools are disabled. */
export let isKairosChannelIntegrationActive: () => boolean = () =>
  process.env["EMBER_KAIROS_CHANNELS"] === "1";

export function _overridePlanFeatureFlags(overrides: {
  isKairosChannelIntegrationActive?: () => boolean;
}): void {
  if (overrides.isKairosChannelIntegrationActive !== undefined)
    isKairosChannelIntegrationActive = overrides.isKairosChannelIntegrationActive;
}

// --- User interaction interface (L4 concern — injectable) ---

/** Presents the plan to the user and resolves with approved plan content (or null on reject). */
export type PlanApprovalFn = (
  planContent: string,
  filePath: string
) => Promise<{ approved: boolean; editedContent?: string }>;

/** Session-scoped plan approval function (set by L4 TUI layer on session start). */
export let _planApprovalFn: PlanApprovalFn | null = null;

export function setPlanApprovalFn(fn: PlanApprovalFn): void {
  _planApprovalFn = fn;
}

// ============================================================
// EnterPlanMode
// ============================================================

const EnterPlanModeInputSchema = z.object({}).strict();
type EnterPlanModeInput = z.infer<typeof EnterPlanModeInputSchema>;

const ENTER_PLAN_WORKFLOW = `You are now in plan mode. Please:
1. Explore the codebase and gather information.
2. Identify existing patterns and architecture.
3. Consider multiple implementation approaches.
4. Use AskUserQuestion for clarification (NOT for plan approval).
5. Design a concrete strategy.
6. Call ExitPlanMode to present the plan to the user.`;

export const EnterPlanModeTool = buildTool({
  name: "EnterPlanMode",

  inputSchema: EnterPlanModeInputSchema,

  isEnabled: () => !isKairosChannelIntegrationActive(),

  call: async (_rawArgs: unknown, context: ToolUseContext) => {
    // AC3: error if called from inside an agent context
    if (context.agentId) {
      throw new Error("EnterPlanMode cannot be called from inside an agent context.");
    }

    // AC1: switch permission mode to 'plan'
    const current = getStoredPermCtx(context);
    await setStoredPermCtx(context, {
      mode: "plan",
      prePlanMode: current.mode,
    });

    return {
      data: {
        message: "Plan mode entered. " + ENTER_PLAN_WORKFLOW,
        previousMode: current.mode,
      },
    };
  },

  description: () =>
    "Enter plan mode. The model researches and drafts a plan before implementation. Call ExitPlanMode to present the plan for approval.",

  prompt: (options) => {
    const isPrivileged = process.env["USER_TYPE"] === "ant";
    if (isPrivileged) {
      return `Enter plan mode for genuine architectural ambiguity, truly unclear requirements, or high-impact restructuring.
Do NOT use AskUserQuestion to ask for plan approval — use ExitPlanMode.

${ENTER_PLAN_WORKFLOW}`;
    }
    return `Use EnterPlanMode proactively for: new features, multiple implementation approaches, multi-file changes,
architectural decisions, unclear requirements, or when user preferences matter before you start coding.

Do NOT reference "the plan" in AskUserQuestion — use ExitPlanMode to present the finished plan.

${ENTER_PLAN_WORKFLOW}`;
  },

  mapToolResultToToolResultBlockParam: (content, toolUseId) => ({
    type: "tool_result" as const,
    tool_use_id: toolUseId,
    content: JSON.stringify(content),
  }),
});

// ============================================================
// ExitPlanMode
// ============================================================

const ExitPlanModeInputSchema = z
  .object({
    allowedPrompts: z
      .array(
        z.object({
          tool: z.string(),
          prompt: z.string(),
        })
      )
      .optional(),
  })
  .strict();

type ExitPlanModeInput = z.infer<typeof ExitPlanModeInputSchema>;

export const ExitPlanModeTool = buildTool({
  name: "ExitPlanMode",

  inputSchema: ExitPlanModeInputSchema,

  isEnabled: () => !isKairosChannelIntegrationActive(),

  call: async (rawArgs: unknown, context: ToolUseContext): Promise<ToolResult<unknown>> => {
    const args = rawArgs as ExitPlanModeInput;
    // AC1: error if not currently in plan mode
    const permCtx = getStoredPermCtx(context);
    if (permCtx.mode !== "plan") {
      throw new Error("ExitPlanMode called but the session is not in plan mode.");
    }

    const isAgent = !!context.agentId;
    const state = context.getAppState() as Record<string, unknown>;
    const cwd = context.cwd ?? (state["cwd"] as string | undefined) ?? process.cwd();
    const filePath = getPlanFilePath(cwd);

    // Read plan from disk (or from session-provided content)
    let planContent: string | null = null;
    try {
      planContent = await readFile(filePath, "utf-8");
    } catch {
      planContent = null;
    }

    // AC3: bypassPermissions → auto-approve
    const isBypass = permCtx.mode === "plan" && (state["isBypassPermissions"] as boolean | undefined);

    let approved = false;
    let editedContent: string | undefined;

    if (isBypass || !planContent) {
      // Auto-approve when bypassing or no plan to show
      approved = true;
    } else if (_planApprovalFn) {
      const result = await _planApprovalFn(planContent, filePath);
      approved = result.approved;
      editedContent = result.editedContent;
    } else {
      // Non-interactive: auto-approve
      approved = true;
    }

    if (!approved) {
      return {
        data: {
          plan: planContent,
          isAgent,
          filePath,
          message: "Plan was not approved. Please revise and call ExitPlanMode again.",
        },
      };
    }

    // AC5: persist edited plan if user edited it before approving
    if (editedContent !== undefined && editedContent !== planContent) {
      await mkdir(dirname(filePath), { recursive: true });
      await writeFile(filePath, editedContent, "utf-8");
      planContent = editedContent;
    }

    // AC2: restore previous permission mode
    const restoredMode: PermissionMode = permCtx.prePlanMode ?? "default";
    await setStoredPermCtx(context, { mode: restoredMode });

    // Set plan-mode-exit flag in state
    await context.setAppState((prev) => ({
      ...(prev as Record<string, unknown>),
      hasPlanModeExited: true,
    }));

    // Build result message per spec
    let message: string;
    if (!planContent || planContent.trim() === "") {
      message = "User has approved exiting plan mode. You can now proceed.";
    } else if (isAgent) {
      message = "User has approved the plan. There is nothing else needed from you now. Please respond with 'ok'.";
    } else {
      message = `User has approved your plan. You can now start coding.\n\nPlan file: ${filePath}\n\n${planContent}`;
    }

    return {
      data: {
        plan: planContent,
        isAgent,
        filePath,
        planWasEdited: editedContent !== undefined && editedContent !== planContent,
        message,
      },
    };
  },

  description: () =>
    "Exit plan mode and present the drafted plan to the user for approval. After approval, the session returns to its previous permission mode and implementation can begin.",

  prompt: () =>
    "Call ExitPlanMode when you have finished drafting your plan and are ready for the user to review and approve it before implementation begins. Do NOT use AskUserQuestion for plan approval.",

  mapToolResultToToolResultBlockParam: (content, toolUseId) => ({
    type: "tool_result" as const,
    tool_use_id: toolUseId,
    content: JSON.stringify(content),
  }),
});
