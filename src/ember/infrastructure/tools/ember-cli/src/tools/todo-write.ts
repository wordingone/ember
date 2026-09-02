// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// tools/todo-write.ts — TodoWrite tool for atomic task list replacement.
//
// The tool overwrites the session's todo list in app state with the supplied array.
// When all todos are completed, the list is cleared (completed state is transient).
// Agent-scoped sessions get a separate key from the main session.

import { z } from "zod";
import { buildTool } from "../core/tool-interface.ts";
import type { ToolUseContext } from "../core/tool-interface.ts";

// ---------------------------------------------------------------------------
// Feature flags
// ---------------------------------------------------------------------------

const isTodoV2Active = (): boolean => process.env["EMBER_TODO_V2"] === "1";
const isVerificationAgentEnabled = (): boolean =>
  process.env["EMBER_VERIFICATION_AGENT"] === "1";

// ---------------------------------------------------------------------------
// State key
// ---------------------------------------------------------------------------

function todoScopeKey(context: ToolUseContext): string {
  return context.agentId ? `todos_agent_${context.agentId}` : "todos";
}

// ---------------------------------------------------------------------------
// Schemas
// ---------------------------------------------------------------------------

const TodoItemSchema = z
  .object({
    content: z.string(),
    activeForm: z.string(),
    status: z.enum(["pending", "in_progress", "completed"]),
  })
  .strict();

const TodoWriteInputSchema = z
  .object({
    todos: z.array(TodoItemSchema),
  })
  .strict();

export type TodoItem = z.infer<typeof TodoItemSchema>;
export type TodoWriteInput = z.infer<typeof TodoWriteInputSchema>;

// ---------------------------------------------------------------------------
// Messages
// ---------------------------------------------------------------------------

const VERIFICATION_NUDGE = `

All tasks are complete. Please spawn a verification agent to confirm your work before proceeding.`;

const BASE_RESULT_MESSAGE =
  "Todos have been modified successfully. Ensure that you continue to use the todo list to track your progress. Please proceed with the current tasks if applicable.";

// ---------------------------------------------------------------------------
// Tool definition
// ---------------------------------------------------------------------------

export const TodoWriteTool = buildTool<TodoWriteInput, unknown>({
  name: "todowrite",
  inputSchema: TodoWriteInputSchema,

  isReadOnly: () => false,
  isConcurrencySafe: () => true,
  isEnabled: () => !isTodoV2Active(),
  maxResultSizeChars: 100_000,

  checkPermissions: async (_input, _context) => ({
    behavior: "allow" as const,
    updatedInput: _input,
  }),

  validateInput: (rawInput: unknown) => {
    const parsed = TodoWriteInputSchema.safeParse(rawInput);
    if (!parsed.success) {
      return {
        result: false as const,
        message: parsed.error.message,
        errorCode: "INVALID_INPUT",
      };
    }
    return { result: true as const };
  },

  call: async (rawArgs: unknown, context: ToolUseContext) => {
    const args = rawArgs as TodoWriteInput;
    const key = todoScopeKey(context);
    const state = context.getAppState() as Record<string, unknown>;
    const oldTodos = (state[key] as TodoItem[] | undefined) ?? [];

    let newTodos = args.todos;
    const allCompleted =
      newTodos.length > 0 && newTodos.every((t) => t.status === "completed");
    if (allCompleted) {
      newTodos = [];
    }

    await context.setAppState((prev) => ({
      ...(prev as Record<string, unknown>),
      [key]: newTodos,
    }));

    const isMainSession = !context.agentId;
    const enoughTodos = args.todos.length >= 3;
    const noVerifTodo = !args.todos.some((t) => /verif/i.test(t.content));
    const verificationNudgeNeeded =
      isVerificationAgentEnabled() &&
      isMainSession &&
      allCompleted &&
      enoughTodos &&
      noVerifTodo;

    const message = verificationNudgeNeeded
      ? BASE_RESULT_MESSAGE + VERIFICATION_NUDGE
      : BASE_RESULT_MESSAGE;

    return {
      data: {
        oldTodos,
        newTodos,
        verificationNudgeNeeded: verificationNudgeNeeded || undefined,
        message,
      },
    };
  },

  description: () =>
    "Write or replace the todo list. Accepts the complete new list; overwrites the current one atomically.",

  prompt: () =>
    "Use todowrite to update the task list. Pass the COMPLETE replacement list — partial updates are not supported. All previous todos are replaced.",

  mapToolResultToToolResultBlockParam: (content, toolUseId) => ({
    type: "tool_result" as const,
    tool_use_id: toolUseId,
    content:
      typeof content === "string" ? content : JSON.stringify(content),
  }),
});
