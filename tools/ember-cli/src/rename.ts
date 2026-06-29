// rename.ts — /rename slash command.

import type { RegistryCommand, CommandContext, CommandResult } from './types/command-types.ts';
import type { Message } from './types/message-types.ts';

interface RenameDeps {
  isTeammate: () => boolean;
  getSessionId: () => string | undefined;
  getMessages: () => Message[];
  extractConversationText: (msgs: Message[]) => string;
  queryLocalModel: (prompt: string, ctx: CommandContext, tag: string) => Promise<{ name: string } | null>;
  saveCustomTitle: (sessionId: string, name: string, transcriptPath: string) => Promise<void>;
  saveAgentName: (sessionId: string, name: string, transcriptPath: string) => Promise<void>;
  getTranscriptPath: () => string;
  getReplBridgeSessionId: () => string | null | undefined;
  updateBridgeSessionTitle: (bridgeId: string, name: string) => Promise<void>;
  getStandaloneAgentContext: () => { name: string };
}

const noopDeps: RenameDeps = {
  isTeammate: () => false,
  getSessionId: () => undefined,
  getMessages: () => [],
  extractConversationText: () => '',
  queryLocalModel: async () => null,
  saveCustomTitle: async () => {},
  saveAgentName: async () => {},
  getTranscriptPath: () => '',
  getReplBridgeSessionId: () => null,
  updateBridgeSessionTitle: async () => {},
  getStandaloneAgentContext: () => ({ name: '' }),
};

let deps: RenameDeps = { ...noopDeps };

export function setRenameDeps(overrides: Partial<RenameDeps>): void {
  deps = { ...deps, ...overrides };
}

export function resetRenameDeps(): void {
  deps = { ...noopDeps };
}

// ---------------------------------------------------------------------------
// Bridge sync (fire-and-forget, never propagates errors)
// ---------------------------------------------------------------------------

async function syncBridgeTitle(name: string): Promise<void> {
  try {
    const bridgeId = deps.getReplBridgeSessionId();
    if (bridgeId) {
      await deps.updateBridgeSessionTitle(bridgeId, name);
    }
  } catch {
    // intentionally ignored — bridge sync is best-effort
  }
}

// ---------------------------------------------------------------------------
// Command
// ---------------------------------------------------------------------------

export const renameCommand: RegistryCommand = {
  name: 'rename',
  description: 'Rename the current session',

  isEnabled(): boolean {
    return true;
  },

  async execute(args: string, ctx: CommandContext): Promise<CommandResult> {
    // Guard: teammate sessions cannot be renamed
    if (deps.isTeammate()) {
      return { type: 'message', message: 'Cannot rename a teammate session.' };
    }

    // Guard: require an active session ID
    const sessionId = deps.getSessionId() || ctx.sessionId;
    if (!sessionId) {
      return { type: 'message', message: 'No active session to rename.' };
    }

    const transcriptPath = deps.getTranscriptPath();
    const nameArg = args.trim();

    if (nameArg) {
      // Manual rename with provided name
      await deps.saveCustomTitle(sessionId, nameArg, transcriptPath);
      await deps.saveAgentName(sessionId, nameArg, transcriptPath);
      try { deps.getStandaloneAgentContext().name = nameArg; } catch { /* best-effort */ }
      void syncBridgeTitle(nameArg);
      return { type: 'message', message: `Session renamed to "${nameArg}".` };
    }

    // Auto-rename via local model
    const messages = deps.getMessages();
    const text = deps.extractConversationText(messages);

    if (!text.trim()) {
      return { type: 'message', message: 'No conversation context available for auto-rename.' };
    }

    const prompt = `Generate a short kebab-case name for this conversation: ${text.slice(0, 500)}`;
    const result = await deps.queryLocalModel(prompt, ctx, 'rename_generate_name');

    if (!result) {
      return { type: 'message', message: 'Local model unavailable for auto-rename.' };
    }

    const name = result.name;
    await deps.saveCustomTitle(sessionId, name, transcriptPath);
    await deps.saveAgentName(sessionId, name, transcriptPath);
    try { deps.getStandaloneAgentContext().name = name; } catch { /* best-effort */ }
    void syncBridgeTitle(name);
    return { type: 'message', message: `Session renamed to "${name}".` };
  },
};
