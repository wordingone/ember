// AskUserQuestion tool — behavioral spec implementation.
//
// Blocks agent execution to present 1–4 multiple-choice questions to the user,
// collect answers, and return them. Automatically appends an "Other" option to each
// question to allow custom text input.
//
// TUI rendering is an L4 concern — this module defines the contract and validation;
// the rendering/answer-collection hook is injected via ToolUseContext.setToolJSX.

import { z } from "zod";
import { buildTool } from "../core/tool-interface.ts";
import type { ToolResult } from "../core/tool-interface.ts";
import type { ToolUseContext } from "../core/tool-use-context.ts";

// --- Schema ---

const OptionSchema = z
  .object({
    label: z.string(),
    description: z.string(),
    preview: z.string().optional(),
  })
  .strict();

const QuestionSchema = z
  .object({
    question: z.string(),
    header: z.string().max(12),
    options: z.array(OptionSchema).min(2).max(4),
    multiSelect: z.boolean().optional(),
  })
  .strict();

const AskUserQuestionInputSchema = z
  .object({
    questions: z.array(QuestionSchema).min(1).max(4),
    answers: z.record(z.string(), z.string()).optional(),
    annotations: z.record(z.string(), z.unknown()).optional(),
    metadata: z.record(z.string(), z.unknown()).optional(),
  })
  .strict();

export type QuestionOption = z.infer<typeof OptionSchema>;
export type Question = z.infer<typeof QuestionSchema>;
export type AskUserQuestionInput = z.infer<typeof AskUserQuestionInputSchema>;

export type AnswerMap = Record<string, string>;

// --- Feature flag hook ---

/** Returns true when KAIROS channel integration is active with channels configured.
 *  When true, the tool is disabled (no terminal available for interactive prompt). */
export let isKairosChannelIntegrationActive: () => boolean = () =>
  process.env["EMBER_KAIROS_CHANNELS"] === "1";

export function _overrideAskFeatureFlags(overrides: {
  isKairosChannelIntegrationActive?: () => boolean;
}): void {
  if (overrides.isKairosChannelIntegrationActive !== undefined)
    isKairosChannelIntegrationActive = overrides.isKairosChannelIntegrationActive;
}

// --- Answer collection interface (L4 TUI concern — injectable) ---

/**
 * Collects answers to the given questions interactively.
 * In real sessions: renders a dialog via Ink and blocks until the user submits.
 * In tests: can be replaced with a fake that resolves immediately.
 *
 * The "Other" option is always appended to each question and handled at this layer.
 */
export type AnswerCollector = (
  questions: Question[],
  prefilledAnswers?: AnswerMap,
  multiSelectMap?: Record<string, boolean>
) => Promise<AnswerMap>;

/** Session-scoped answer collector (set by L4 TUI layer on session start). */
export let _answerCollector: AnswerCollector | null = null;

export function setAnswerCollector(fn: AnswerCollector): void {
  _answerCollector = fn;
}

// --- Validation helpers ---

/** Validates uniqueness of question texts and option labels per spec AC2/AC3. */
function validateQuestions(
  questions: Question[]
): { valid: true } | { valid: false; message: string } {
  // AC2: all question texts must be unique
  const questionTexts = questions.map((q) => q.question);
  const uniqueTexts = new Set(questionTexts);
  if (uniqueTexts.size !== questionTexts.length) {
    return {
      valid: false,
      message: "All question texts must be unique across the questions array.",
    };
  }

  // AC3: option labels within each question must be unique
  for (const q of questions) {
    const labels = q.options.map((o) => o.label);
    const uniqueLabels = new Set(labels);
    if (uniqueLabels.size !== labels.length) {
      return {
        valid: false,
        message: `Duplicate option labels in question: "${q.question}".`,
      };
    }
  }

  return { valid: true };
}

// --- Answer persistence ---

const ANSWERS_STATE_KEY = "askUserQuestionAnswers";

function persistAnswers(context: ToolUseContext, answers: AnswerMap): void {
  context.setAppState((prev) => ({
    ...(prev as Record<string, unknown>),
    [ANSWERS_STATE_KEY]: {
      ...((prev as Record<string, unknown>)[ANSWERS_STATE_KEY] as Record<string, unknown> | undefined),
      ...answers,
    },
  }));
}

// --- Tool definition ---

export const AskUserQuestionTool = buildTool({
  name: "AskUserQuestion",

  inputSchema: AskUserQuestionInputSchema,

  isReadOnly: () => true,
  isConcurrencySafe: () => true,

  isEnabled: () => !isKairosChannelIntegrationActive(),

  maxResultSizeChars: 100_000,

  userFacingName: () => "", // no label shown to user per spec

  validateInput: (rawInput: unknown) => {
    const input = rawInput as AskUserQuestionInput;
    const parsed = AskUserQuestionInputSchema.safeParse(input);
    if (!parsed.success) {
      return {
        result: false as const,
        message: parsed.error.message,
        errorCode: "INVALID_INPUT",
      };
    }
    const check = validateQuestions(parsed.data.questions);
    if (!check.valid) {
      return {
        result: false as const,
        message: check.message,
        errorCode: "VALIDATION_ERROR",
      };
    }
    return { result: true as const };
  },

  call: async (rawArgs: unknown, context: ToolUseContext): Promise<ToolResult<unknown>> => {
    const args = rawArgs as AskUserQuestionInput;
    // Validate before any I/O
    const check = validateQuestions(args.questions);
    if (!check.valid) {
      throw new Error(check.message);
    }

    // Collect answers — use pre-filled if provided, otherwise interactive
    let answers: AnswerMap;
    if (args.answers && Object.keys(args.answers).length > 0) {
      answers = args.answers;
    } else if (_answerCollector) {
      // AC1: render dialog and block until user submits
      const multiSelectMap: Record<string, boolean> = {};
      for (const q of args.questions) {
        if (q.multiSelect) multiSelectMap[q.question] = true;
      }
      answers = await _answerCollector(args.questions, args.answers, multiSelectMap);
    } else {
      // Non-interactive session: return an error result
      return {
        data: {
          questions: args.questions,
          answers: {},
          error: "Interactive prompt not available in this session.",
        },
      };
    }

    // AC5: multi-select answers are comma-separated in the map (already handled by collector)
    // AC7: returned answers map question text → chosen option label

    // Persist answers in session state (permission UI can read them on subsequent calls)
    persistAnswers(context, answers);

    return {
      data: {
        questions: args.questions,
        answers,
        annotations: args.annotations,
      },
    };
  },

  description: () =>
    "Ask the user 1–4 multiple-choice questions and return their answers. Use when preferences, clarification, or a choice among specific options is needed before proceeding.",

  prompt: (options) => {
    const isPrivileged = process.env["USER_TYPE"] === "ant";
    if (isPrivileged) {
      return `Use AskUserQuestion for genuine architectural ambiguity, truly unclear requirements, or high-impact restructuring.
Do NOT use AskUserQuestion to ask "Is my plan ready?" — use ExitPlanMode for plan approval.`;
    }
    return `Use AskUserQuestion to gather preferences, clarify ambiguity, or offer choices before proceeding.
Mark the recommended option by prepending "(Recommended)" to its label.
Use multiSelect: true when the user can pick multiple options.
Do NOT use for "Is my plan ready?" or "Can I proceed?" — use ExitPlanMode instead.
Do NOT reference "the plan" in questions — the user cannot see an in-progress plan.`;
  },

  mapToolResultToToolResultBlockParam: (content, toolUseId) => ({
    type: "tool_result" as const,
    tool_use_id: toolUseId,
    content: JSON.stringify(content),
  }),
});
