// types/message-types.ts — canonical message and content-block type definitions.
// Shared by the API adapter, state layer, and rendering layer.

// ---------------------------------------------------------------------------
// Ember content block discriminated union
// ---------------------------------------------------------------------------

export type EmberContentBlock =
  | { type: "text"; text: string }
  | { type: "thinking"; thinking: string }
  | { type: "tool_use"; id: string; name: string; input: unknown }
  | {
      type: "tool_result";
      tool_use_id: string;
      content: string | Array<{ type: "text"; text: string }>;
    }
  | { type: "image"; source: { media_type: string; data: string } };

// ---------------------------------------------------------------------------
// Ember message
// ---------------------------------------------------------------------------

export interface EmberMessage {
  role: "user" | "assistant" | "system" | "tool";
  content: string | EmberContentBlock[];
  // Optional API-envelope fields carried on raw assistant/tool messages from
  // the model backend. Optional so minimal { role, content } literals stay valid.
  id?: string;
  type?: string;
  model?: string;
  stop_reason?: string | null;
  stop_sequence?: string | null;
  // Raw backend messages also carry usage and other envelope fields; the index
  // signature keeps EmberMessage an open envelope (and assignable to Record).
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Renderer-facing message aliases
// Message is the open union base used by the rendering layer.  The role
// field uses string (not a literal union) because the session JSONL stream
// also carries synthetic roles such as "progress" and "tool_call_start".
// Additional properties (toolUseId, type, etc.) are accessed via the index
// signature on concrete subtypes.
// ---------------------------------------------------------------------------

export interface Message {
  role: string;
  content?: unknown;
  // Index signature with `any` lets callers access synthetic fields
  // (e.g. toolUseId, type) without narrowing failures on Map operations.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  [key: string]: any;
}

export interface AssistantMessage extends Message {
  role: "assistant";
  content: unknown[];
}

export interface UserMessage extends Message {
  role: "user";
}

export interface SystemMessage extends Message {
  role: "system";
}
