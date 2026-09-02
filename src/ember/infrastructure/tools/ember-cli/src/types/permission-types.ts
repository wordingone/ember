// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// types/permission-types.ts
// Permission mode lifecycle, rule evaluation sources, and decision tree types.
// L1 leaf: no intra-ember dependencies. Types only — no runtime implementation.

// ---- Content block (ember-native; no third-party vendor SDK imports) ----

export type ContentBlockParam =
  | { type: 'text'; text: string }
  | { type: 'image'; source: unknown }
  | { type: 'tool_use'; id: string; name: string; input: unknown }
  | { type: 'tool_result'; tool_use_id: string; content: unknown; is_error?: boolean }
  | { type: string; [key: string]: unknown };

// ---- Permission modes ----

/** All modes addressable by external callers (CLI flags, project settings, etc.). */
export const EXTERNAL_PERMISSION_MODES = [
  'acceptEdits',
  'bypassPermissions',
  'default',
  'dontAsk',
  'plan',
] as const;

export type ExternalPermissionMode = (typeof EXTERNAL_PERMISSION_MODES)[number];

/** All modes, including internal-only variants used within the session loop. */
export type InternalPermissionMode = ExternalPermissionMode | 'auto' | 'bubble';

/** Union of all valid permission mode values. */
export type PermissionMode = InternalPermissionMode;

/** Runtime array of all user-addressable permission modes. */
export const INTERNAL_PERMISSION_MODES: readonly PermissionMode[] = [
  ...EXTERNAL_PERMISSION_MODES,
  'auto',
  'bubble',
] as const;

/** Alias for INTERNAL_PERMISSION_MODES (used by settings validation). */
export const PERMISSION_MODES = INTERNAL_PERMISSION_MODES;

// ---- Rule types ----

/** The verdict a permission check returns for a specific tool invocation. */
export type PermissionBehavior = 'allow' | 'deny' | 'ask';

/** Where a permission rule was originally loaded from. */
export type PermissionRuleSource =
  | 'userSettings'
  | 'projectSettings'
  | 'localSettings'
  | 'flagSettings'
  | 'policySettings'
  | 'cliArg'
  | 'command'
  | 'session';

/** The tool-name and optional constraint string that a rule matches against. */
export interface PermissionRuleValue {
  toolName: string;
  ruleContent?: string;
}

/** A single permission rule with its provenance and verdict. */
export interface PermissionRule {
  source: PermissionRuleSource;
  ruleBehavior: PermissionBehavior;
  ruleValue: PermissionRuleValue;
}

// ---- Permission update operations ----

/** Where a permission update is persisted. */
export type PermissionUpdateDestination =
  | 'userSettings'
  | 'projectSettings'
  | 'localSettings'
  | 'session'
  | 'cliArg';

/**
 * Discriminated union of all permission mutation operations.
 * Each operation targets a specific `destination` scope.
 */
export type PermissionUpdate =
  | {
      type: 'addRules';
      destination: PermissionUpdateDestination;
      rules: string[];
      behavior: PermissionBehavior;
    }
  | {
      type: 'replaceRules';
      destination: PermissionUpdateDestination;
      rules: string[];
      behavior: PermissionBehavior;
    }
  | {
      type: 'removeRules';
      destination: PermissionUpdateDestination;
      rules: string[];
    }
  | {
      type: 'setMode';
      destination: PermissionUpdateDestination;
      mode: PermissionMode;
    }
  | {
      type: 'addDirectories';
      destination: PermissionUpdateDestination;
      directories: string[];
    }
  | {
      type: 'removeDirectories';
      destination: PermissionUpdateDestination;
      directories: string[];
    };

// ---- Decision reason ----

/**
 * Structured reason for why a permission decision was made.
 * Enables UI rendering of explanations and audit logging.
 */
export type PermissionDecisionReason =
  | { type: 'rule'; rule: PermissionRule }
  | { type: 'mode'; mode: PermissionMode }
  | { type: 'subcommandResults'; results: unknown[] }
  | { type: 'permissionPromptTool'; toolName: string }
  | { type: 'hook'; hookResult: unknown }
  | { type: 'asyncAgent'; agentId: string }
  | { type: 'sandboxOverride' }
  | { type: 'classifier'; classifierResult: unknown }
  | { type: 'workingDir'; path: string }
  | { type: 'safetyCheck' }
  | { type: 'other'; details?: string };

// ---- Decision types ----

/** Permission check resolved to "allow". */
export interface PermissionAllowDecision<T = unknown> {
  behavior: 'allow';
  updatedInput?: T;
  userModified?: boolean;
  decisionReason?: PermissionDecisionReason;
  toolUseID?: string;
  acceptFeedback?: string;
  contentBlocks?: ContentBlockParam[];
}

/** Permission check requires a prompt to the user before proceeding. */
export interface PermissionAskDecision<T = unknown> {
  behavior: 'ask';
  message: string;
  updatedInput?: T;
  decisionReason?: PermissionDecisionReason;
  suggestions?: PermissionUpdate[];
  blockedPath?: string;
  metadata?: Record<string, unknown>;
  isBashSecurityCheckForMisparsing?: boolean;
  pendingClassifierCheck?: {
    classifierId: string;
    startedAtMs: number;
    inputTokens?: number;
    outputTokens?: number;
  };
  contentBlocks?: ContentBlockParam[];
}

/** Permission check resolved to "deny". */
export interface PermissionDenyDecision {
  behavior: 'deny';
  message: string;
  decisionReason: PermissionDecisionReason;
  toolUseID?: string;
}

/** Union of all concrete permission decision outcomes. */
export type PermissionDecision<T = unknown> =
  | PermissionAllowDecision<T>
  | PermissionAskDecision<T>
  | PermissionDenyDecision;

/**
 * Full result of a permission check, including a passthrough variant that
 * signals the check was skipped and the input should be forwarded unchanged.
 */
export type PermissionResult<T = unknown> =
  | PermissionDecision<T>
  | { behavior: 'passthrough'; updatedInput?: T };

// ---- App-level types ----

/** An in-flight permission request stored in AppState pending user resolution. */
export interface PermissionRequest {
  id: string;
  toolName: string;
  input: unknown;
  message?: string;
  decisionReason?: PermissionDecisionReason;
  suggestions?: PermissionUpdate[];
}

/** Cached permission status for a specific tool (keyed by tool name in AppState). */
export type ToolPermissionStatus = 'allow' | 'deny' | 'ask' | 'pending';
