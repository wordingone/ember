// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// message-mappers.ts — bidirectional conversion between internal and SDK message shapes.

import { randomUUID } from 'crypto';

// ---- Tool name constants ----

/** Primary agent tool name used in the current protocol version. */
export const PRIMARY_AGENT_TOOL_NAME = 'Task';

/** Legacy alias for the agent tool, retained for SDK back-compat. */
export const LEGACY_AGENT_TOOL_NAME = 'computer';

// ---- InternalMessage ----

/**
 * Internal representation of a conversation turn.
 * Used within the session layer before conversion to SDK wire format.
 */
export interface InternalMessage {
  role: 'user' | 'assistant';
  content: unknown;
  uuid?: string;
  isCompactBoundary?: boolean;
  isLocalCommand?: boolean;
  localCommandOutput?: string;
}

// ---- ANSI stripping ----

const ANSI_ESCAPE_RE =
  // eslint-disable-next-line no-control-regex
  /[\x1B\x9B][[()#;?]*(?:[0-9]{1,4}(?:;[0-9]{0,4})*)?[0-9A-ORZcf-nqry=><~]/g;

/** Removes ANSI escape codes from a string. */
export function stripAnsi(text: string): string {
  return text.replace(ANSI_ESCAPE_RE, '');
}

// ---- SDK compat tool name ----

/**
 * Translates the primary agent tool name to its legacy alias for SDK compatibility.
 * All other tool names pass through unchanged.
 */
export function sdkCompatToolName(name: string): string {
  return name === PRIMARY_AGENT_TOOL_NAME ? LEGACY_AGENT_TOOL_NAME : name;
}

// ---- SDK message output shape ----

interface SDKOutputMessage {
  role: 'user' | 'assistant';
  content: unknown;
  uuid: string;
}

// ---- toSDKMessages ----

/**
 * Converts internal messages to the SDK wire format.
 *
 * - compact_boundary entries are dropped
 * - local_command entries become assistant turns with ANSI stripped from their output
 * - Every message is assigned a UUID when one is not already present
 */
export function toSDKMessages(messages: InternalMessage[]): SDKOutputMessage[] {
  const result: SDKOutputMessage[] = [];

  for (const msg of messages) {
    if (msg.isCompactBoundary) continue;

    const uuid = msg.uuid ?? randomUUID();

    if (msg.isLocalCommand) {
      const raw = msg.localCommandOutput ?? '';
      const cleaned = stripAnsi(raw);
      result.push({
        role: 'assistant',
        content: [{ type: 'text', text: cleaned }],
        uuid,
      });
      continue;
    }

    result.push({ role: msg.role, content: msg.content, uuid });
  }

  return result;
}

// ---- toInternalMessages ----

/**
 * Converts SDK-shaped messages (from history or API responses) to the internal format.
 * Assigns UUIDs to any messages that lack them.
 */
export function toInternalMessages(
  sdk: Array<{ role: 'user' | 'assistant'; content: unknown; uuid?: string }>,
): InternalMessage[] {
  return sdk.map((m) => ({
    role: m.role,
    content: m.content,
    uuid: m.uuid ?? randomUUID(),
  }));
}

// ---- buildSystemInitMessage ----

interface BuildSystemInitOpts {
  tools?: Array<{ name: string }>;
  activeModel?: string;
  udsInboxFeatureEnabled?: boolean;
  mcpServers?: string[];
}

interface SystemInitMessage {
  model?: string;
  tools: string[];
  mcpServers?: string[];
  udsInboxPath?: string;
}

/**
 * Constructs the system-init message payload sent at the start of each session.
 *
 * - tools: names extracted from the provided tool descriptors
 * - model: forwarded from activeModel when present
 * - udsInboxPath: included when udsInboxFeatureEnabled is true and UDS_INBOX env is set
 */
export function buildSystemInitMessage(opts: BuildSystemInitOpts = {}): SystemInitMessage {
  const tools = (opts.tools ?? []).map((t) => t.name);

  const msg: SystemInitMessage = { tools };

  if (opts.activeModel !== undefined) {
    msg.model = opts.activeModel;
  }

  if (opts.mcpServers !== undefined && opts.mcpServers.length > 0) {
    msg.mcpServers = opts.mcpServers;
  }

  if (opts.udsInboxFeatureEnabled) {
    const udsInboxPath = process.env['UDS_INBOX'];
    if (udsInboxPath) {
      msg.udsInboxPath = udsInboxPath;
    }
  }

  return msg;
}
