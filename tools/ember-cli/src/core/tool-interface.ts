// core/tool-interface.ts — canonical Tool shape and buildTool factory.
//
// Defines:
//   - Tool: the full runtime interface for a registered tool.
//   - ToolResult<T>: the value returned by tool.call().
//   - ToolUseContext: the execution context injected into every call().
//   - DescriptionOptions: options passed to tool.description().
//   - buildTool: merges caller-supplied definition with TOOL_DEFAULTS.
//
// L2: depends on zod for inputJSONSchema derivation; no other intra-ember deps.

import { z } from "zod";
import { toJSONSchema } from "zod/v4";

// ---------------------------------------------------------------------------
// ToolUseContext — execution context injected into tool.call()
//
// Full shape is owned by core/tool-use-context.ts (not yet reconstructed).
// This inline definition captures the contract that call() implementations
// actually use and that _buildToolUseContext() in QueryEngine produces.
// ---------------------------------------------------------------------------

export interface ToolUseContextOptions {
  tools?: Tool[];
  commands?: unknown[];
  verbose?: boolean;
  thinkingConfig?: unknown;
  mcpClients?: unknown;
  mainLoopModel?: string;
  customSystemPrompt?: string;
  appendSystemPrompt?: string;
  maxBudgetUsd?: number;
}

export interface ToolUseContext {
  options: ToolUseContextOptions;
  abortController: AbortController;
  /**
   * Resolved working directory tool executors must use in place of raw
   * process.cwd() (issue #182: process.cwd() is the launch cwd, which is
   * unreliable for a compiled binary launched from an arbitrary directory —
   * the same class of bug #172 fixed for repo-root resolution). Sourced from
   * QueryEngineConfig.cwd; falls back to process.cwd() only when the caller
   * never set one (e.g. minimal contexts built for unit tests).
   */
  cwd?: string;
  getAppState: () => unknown;
  setAppState: (updater: (prev: unknown) => unknown) => void | Promise<void>;
  setAppStateForTasks?: (updater: (prev: unknown) => unknown) => void;
  readFileState?: Map<string, unknown>;
  messages: unknown[];
  appendSystemMessage?: () => void;
  nestedMemoryAttachmentTriggers?: Set<string>;
  loadedNestedMemoryPaths?: Set<string>;
  dynamicSkillDirTriggers?: Set<string>;
  discoveredSkillNames?: Set<string>;
  fileReadingLimits?: { maxTokens: number; maxSizeBytes: number };
  globLimits?: { maxResults: number };
  toolUseId?: string;
  setSDKStatus?: unknown;
  /** Present when call() is invoked from within an agent task. */
  agentId?: string;
  isNonInteractiveSession?: boolean;
  fileStateCache?: unknown;
  setResponseLength?: () => void;
  setFileHistory?: () => void;
  setAttribution?: () => void;
}

// ---------------------------------------------------------------------------
// DescriptionOptions — ambient context passed to tool.description()
// ---------------------------------------------------------------------------

export interface DescriptionOptions {
  isNonInteractiveSession?: boolean;
  toolPermissionContext?: unknown;
  tools?: Tool[];
}

// ---------------------------------------------------------------------------
// PermissionCheckResult — returned by tool.checkPermissions()
// ---------------------------------------------------------------------------

export type PermissionBehavior = "allow" | "deny" | "ask";

export interface PermissionCheckResult<TInput = unknown> {
  behavior: PermissionBehavior;
  updatedInput: TInput;
  /** Human-readable message shown in the permission dialog (deny/ask returns). */
  message?: string;
}

// ---------------------------------------------------------------------------
// ValidationResult — returned by tool.validateInput() (optional method)
// ---------------------------------------------------------------------------

export type ValidationResult =
  | { result: true }
  | { result: false; message: string; errorCode: string };

// ---------------------------------------------------------------------------
// ToolResult<T> — the value tool.call() resolves with
// ---------------------------------------------------------------------------

export interface ToolResult<T = unknown> {
  data: T;
}

// ---------------------------------------------------------------------------
// ToolResultBlockParam — the content block pushed into the message list
// ---------------------------------------------------------------------------

export interface ToolResultBlockParam {
  type: "tool_result";
  tool_use_id: string;
  content: string | unknown[];
  is_error?: boolean;
}

// ---------------------------------------------------------------------------
// Tool — full runtime interface for a registered tool
// ---------------------------------------------------------------------------

export interface Tool<TInput = unknown, TOutput = unknown> {
  /** Machine-readable tool name (used in the API schema). */
  name: string;

  /**
   * Human-readable description sent to the model.
   * Receives the current call input (if available) and ambient context options.
   */
  description: (input?: TInput, opts?: DescriptionOptions) => string;

  /**
   * Zod schema used for input validation and JSON-schema derivation.
   * Optional if inputJSONSchema is provided directly.
   */
  inputSchema?: z.ZodTypeAny;

  /**
   * Derived JSON schema (auto-derived from inputSchema via toJSONSchema if not set explicitly).
   * Sent to the model as the tool's parameter schema.
   */
  inputJSONSchema?: Record<string, unknown>;

  /** Returns true when this tool is available for use in the current session. */
  isEnabled: () => boolean;

  /**
   * Returns true when this tool can safely execute in parallel with other tools
   * (i.e., it has no shared mutable state or external side-effects).
   */
  isConcurrencySafe: (input?: TInput) => boolean;

  /**
   * Returns true when this tool only reads data and never writes or changes state.
   * Read-only tools may receive more permissive treatment in permission checks.
   */
  isReadOnly: (input?: TInput) => boolean;

  /**
   * Returns true when this tool performs a destructive or irreversible operation.
   * Destructive tools trigger additional confirmation steps.
   */
  isDestructive: (input?: TInput) => boolean;

  /**
   * Checks whether the tool is permitted to run with the given input.
   * Returns the (potentially mutated) input alongside the permission verdict.
   */
  checkPermissions: (
    input: TInput,
    context: ToolUseContext,
  ) => Promise<PermissionCheckResult<TInput>>;

  /**
   * Converts the raw input to a string suitable for the auto-classifier model.
   * Returns an empty string when this tool does not participate in classification.
   */
  toAutoClassifierInput: (input?: TInput) => string;

  /**
   * Returns a short, user-facing display name for the tool (shown in the TUI header).
   * Defaults to `name` if not overridden.
   */
  userFacingName: (input?: TInput) => string;

  /**
   * Controls how a running Esc/interrupt is handled mid-execution.
   * "block": wait for completion before acting on the interrupt.
   * "stop": halt execution immediately on interrupt.
   */
  interruptBehavior: () => "block" | "stop";

  /**
   * Executes the tool with the given arguments and context.
   * @param args - The validated input arguments.
   * @param context - Per-call execution context (abort, app state, permissions…).
   * @param canUseTool - Optional predicate for nested tool authorization.
   * @param parentMessage - Optional parent message for nested invocations.
   */
  call: (
    args: TInput,
    context: ToolUseContext,
    canUseTool?: unknown,
    parentMessage?: unknown,
    onEvent?: (event: unknown) => void,
  ) => Promise<ToolResult<TOutput>>;

  /**
   * Converts the value returned by call() into the tool_result content block
   * pushed onto the message list for the next model turn.
   */
  mapToolResultToToolResultBlockParam: (
    content: TOutput,
    toolUseId: string,
  ) => ToolResultBlockParam;

  // --- Optional / extended surface ---

  /**
   * Validates the raw input before call() is invoked.
   * Returns a ValidationResult or null when no custom validation is needed.
   */
  validateInput?: (args: unknown) => ValidationResult | null;

  /** Maximum number of characters the tool result content is allowed to contain. */
  maxResultSizeChars?: number;

  /**
   * Returns the system-prompt snippet describing when/how to use this tool.
   * Called once during system prompt assembly.
   */
  prompt?: (options?: unknown) => string;

  /**
   * Renders a successful tool result in the TUI.
   * When provided, overrides the default card renderer.
   */
  renderToolResultMessage?: (
    content: TOutput,
    messages: unknown[],
    opts: { verbose: boolean },
  ) => import("react").ReactElement | null;

  /**
   * Renders a tool-use rejection notice in the TUI.
   * When provided, overrides the default "Tool use rejected" text.
   */
  renderToolUseRejectedMessage?: (
    result: unknown,
    opts: Record<string, unknown>,
  ) => import("react").ReactElement | null;

  /**
   * Returns a JSON schema describing the tool's output shape.
   * Used by the MCP server to advertise output types. Optional.
   */
  outputSchema?: () => Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// TOOL_DEFAULTS — baseline behavior merged into every buildTool() call
// ---------------------------------------------------------------------------

/**
 * Default implementations for every optional/behavioral Tool field.
 * buildTool() merges the caller's definition on top of this object.
 */
const TOOL_DEFAULTS: Omit<
  Tool,
  "name" | "description" | "call" | "mapToolResultToToolResultBlockParam"
> = {
  isEnabled: () => true,
  isConcurrencySafe: (_input?: unknown) => false,
  isReadOnly: (_input?: unknown) => false,
  isDestructive: (_input?: unknown) => false,
  checkPermissions: async (_input: unknown, _context: ToolUseContext) => ({
    behavior: "allow" as const,
    updatedInput: _input,
  }),
  toAutoClassifierInput: (_input?: unknown) => "",
  userFacingName: function (this: Tool) {
    return this.name;
  },
  interruptBehavior: () => "block" as const,
};

// ---------------------------------------------------------------------------
// ToolDefinition — the shape passed to buildTool()
// ---------------------------------------------------------------------------

/**
 * The caller-supplied definition: required fields plus any optional overrides.
 * buildTool() fills in TOOL_DEFAULTS for anything not provided.
 */
export type ToolDefinition<TInput = unknown, TOutput = unknown> = Pick<
  Tool<TInput, TOutput>,
  "name" | "description" | "call" | "mapToolResultToToolResultBlockParam"
> &
  Partial<Omit<Tool<TInput, TOutput>, "name" | "description" | "call" | "mapToolResultToToolResultBlockParam">>;

// ---------------------------------------------------------------------------
// buildTool — the canonical factory
// ---------------------------------------------------------------------------

/**
 * Creates a fully-resolved Tool object from a caller-supplied definition.
 * Merges TOOL_DEFAULTS first, then the caller's fields, then derives
 * inputJSONSchema from inputSchema via toJSONSchema() if not already set.
 *
 * @param def - Partial tool definition (name, description, call are required).
 * @returns A complete, runtime-ready Tool object.
 */
export function buildTool<TInput = unknown, TOutput = unknown>(
  def: ToolDefinition<TInput, TOutput>,
): Tool<TInput, TOutput> {
  // Merge defaults → name-derived userFacingName → caller definition
  const tool = Object.assign(
    {} as Tool<TInput, TOutput>,
    TOOL_DEFAULTS as unknown as Partial<Tool<TInput, TOutput>>,
    { userFacingName: (_input?: TInput) => def.name } as Partial<Tool<TInput, TOutput>>,
    def,
  );

  // Derive inputJSONSchema from inputSchema when not provided explicitly
  if (tool.inputJSONSchema === undefined && def.inputSchema !== undefined) {
    try {
      tool.inputJSONSchema = toJSONSchema(def.inputSchema) as Record<string, unknown>;
    } catch {
      // Silently skip: schema derivation is best-effort
    }
  }

  return tool;
}
