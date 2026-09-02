// message-adapter.ts — converts raw SDK protocol messages to internal display types.
// CONTRACT-GAP: message-adapter.test.ts imports EmberMessage from "../types/message-types.ts"
// which resolves to the repo-level src/ember/infrastructure/tools/ember-cli/types/message-types.ts shim (outside src/).
// EmberMessage (types/message-types.ts) carries an index signature, so a raw
// EmberMessage is assignable to Record<string, unknown> — the SDK message field
// stays a generic record and accepts an EmberMessage without special typing.

// ---- SDK message types (wire protocol) ----

export interface RemoteAssistantSDKMsg {
  type: 'assistant';
  uuid: string;
  message: Record<string, unknown>;
  timestamp: string;
}

export interface RemoteResultSDKMsg {
  type: 'result';
  subtype: string;
  result?: string;
  error?: string;
}

export interface RemoteCompactBoundarySDKMsg {
  type: 'compact_boundary';
  summary?: string;
  tokens_saved?: number;
}

// Forward-compat catch-all alongside well-known variants
export type SDKMessage =
  | RemoteAssistantSDKMsg
  | { type: 'stream_event'; event: unknown }
  | { type: 'user'; message?: { content?: unknown[] } }
  | { type: 'system'; status?: string; subtype?: string; model?: string }
  | RemoteResultSDKMsg
  | RemoteCompactBoundarySDKMsg
  | { type: 'tool_use_summary'; summary?: string; precedingToolUseIds?: string[] }
  | { type: 'auth_status' }
  | { type: 'rate_limit_event' }
  | { type: string }; // forward-compat for unknown future message types

// ---- Internal display types ----

type AssistantOutputMessage = {
  role: 'assistant';
  uuid: string;
  timestamp: string;
  message: Record<string, unknown>;
};

type UserOutputMessage = {
  role: 'user';
  content: unknown[];
};

type SystemOutputMessage = {
  role: 'system';
  content?: string;
  type?: string;
  compactMetadata?: { summary: string; tokensSaved: number };
};

type OutputMessage = AssistantOutputMessage | UserOutputMessage | SystemOutputMessage;

type ConvertedSDKMessage =
  | { type: 'message'; message: OutputMessage }
  | { type: 'stream_event'; event: unknown }
  | { type: 'ignored' };

// ---- Conversion options ----

export interface ConvertSDKMessageOpts {
  /** When true, user messages containing tool_result content are converted to UserMessage. */
  convertToolResults?: boolean;
  /** When true, user messages containing plain text content are converted to UserMessage. */
  convertUserTextMessages?: boolean;
}

// ---- Helpers ----

function isToolResultContent(content: unknown[]): boolean {
  return content.some(
    (block) =>
      typeof block === 'object' &&
      block !== null &&
      (block as Record<string, unknown>)['type'] === 'tool_result',
  );
}

function isTextContent(content: unknown[]): boolean {
  return content.some(
    (block) =>
      typeof block === 'object' &&
      block !== null &&
      (block as Record<string, unknown>)['type'] === 'text',
  );
}

// ---- Main converter ----

/**
 * Converts a raw SDK protocol message to an internal display-ready message.
 * Unknown or filtered message types return `{ type: 'ignored' }`.
 */
export function convertSDKMessage(
  msg: SDKMessage,
  opts?: ConvertSDKMessageOpts,
): ConvertedSDKMessage {
  const raw = msg as Record<string, unknown>;
  const msgType = raw['type'] as string;

  switch (msgType) {
    case 'assistant': {
      const am = msg as RemoteAssistantSDKMsg;
      return {
        type: 'message',
        message: {
          role: 'assistant',
          uuid: am.uuid,
          timestamp: am.timestamp,
          message: am.message,
        },
      };
    }

    case 'stream_event': {
      return { type: 'stream_event', event: raw['event'] };
    }

    case 'user': {
      const userMsg = (raw['message'] as Record<string, unknown> | undefined) ?? {};
      const content = (userMsg['content'] as unknown[] | undefined) ?? [];

      if (isToolResultContent(content)) {
        if (opts?.convertToolResults) {
          return { type: 'message', message: { role: 'user', content } };
        }
        return { type: 'ignored' };
      }

      if (isTextContent(content)) {
        if (opts?.convertUserTextMessages) {
          return { type: 'message', message: { role: 'user', content } };
        }
        return { type: 'ignored' };
      }

      return { type: 'ignored' };
    }

    case 'system': {
      const status = raw['status'] as string | undefined;
      const subtype = raw['subtype'] as string | undefined;
      const model = raw['model'] as string | undefined;

      if (status !== undefined) {
        const text = status === 'compacting' ? 'Compacting conversation…' : `Status: ${status}`;
        return { type: 'message', message: { role: 'system', content: text } };
      }

      if (subtype === 'init' && model !== undefined) {
        return { type: 'message', message: { role: 'system', content: model } };
      }

      return { type: 'ignored' };
    }

    case 'result': {
      const rm = msg as RemoteResultSDKMsg;
      if (rm.subtype === 'success') {
        return {
          type: 'message',
          message: { role: 'system', type: 'info', content: rm.result ?? '' } as SystemOutputMessage,
        };
      }
      const errText = (raw['error'] as string | undefined) ?? rm.subtype;
      return {
        type: 'message',
        message: { role: 'system', type: 'api_error', content: errText } as SystemOutputMessage,
      };
    }

    case 'compact_boundary': {
      const cm = msg as RemoteCompactBoundarySDKMsg;
      return {
        type: 'message',
        message: {
          role: 'system',
          type: 'compact_boundary',
          content: 'Conversation compacted',
          compactMetadata: fromSDKCompactMetadata(cm),
        } as SystemOutputMessage,
      };
    }

    default:
      return { type: 'ignored' };
  }
}

// ---- Predicates ----

/** Returns true when `msg` signals the end of a session (result type). */
export function isSessionEndMessage(msg: SDKMessage): boolean {
  return (msg as Record<string, unknown>)['type'] === 'result';
}

/** Returns true when the result message indicates a successful completion. */
export function isSuccessResult(msg: SDKResultMessage): boolean {
  return msg.subtype === 'success';
}

/** Returns the result text for a successful result message, or null otherwise. */
export function getResultText(msg: SDKResultMessage): string | null {
  if (msg.subtype !== 'success') return null;
  return msg.result ?? null;
}

// ---- SDKResultMessage (convenience alias) ----

export type SDKResultMessage = RemoteResultSDKMsg;

// ---- Compact metadata ----

export interface CompactMetadata {
  summary: string;
  tokensSaved: number;
}

/**
 * Maps a RemoteCompactBoundarySDKMsg to the internal CompactMetadata shape.
 * Defaults to empty string and 0 when fields are absent.
 */
export function fromSDKCompactMetadata(
  msg: RemoteCompactBoundarySDKMsg,
): CompactMetadata {
  return {
    summary: msg.summary ?? '',
    tokensSaved: msg.tokens_saved ?? 0,
  };
}
