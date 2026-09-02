// clear.ts — /clear, /reset, /new slash command.

import type { RegistryCommand, CommandContext } from './types/command-types.ts';
import type { Message } from './types/message-types.ts';

export interface ClearTask {
  taskType: string;
  isBackgrounded: boolean;
  agentId: string;
}

interface ClearCommandDeps {
  setMessages: (msgs: Message[]) => void;
  regenerateSessionId: (opts: { oldSessionId: string }) => string;
  resetSessionFilePointer: (id: string) => void;
  getTasks: () => ClearTask[];
  killTask: (t: ClearTask) => void;
  relinkBackgroundedAgents: (sessionId: string, agentIds: string[]) => void;
  resetWorkingDirectory: () => void;
  emitCacheEvictionEvent: (scope: string) => void;
  runSessionStartHooks: (src: string) => Promise<Message[]>;
  runSessionEndHooks: () => Promise<void>;
  isInteractive: () => boolean;
}

const noopDeps: ClearCommandDeps = {
  setMessages: () => {},
  regenerateSessionId: () => crypto.randomUUID(),
  resetSessionFilePointer: () => {},
  getTasks: () => [],
  killTask: () => {},
  relinkBackgroundedAgents: () => {},
  resetWorkingDirectory: () => {},
  emitCacheEvictionEvent: () => {},
  runSessionStartHooks: async () => [],
  runSessionEndHooks: async () => {},
  isInteractive: () => true,
};

let deps: ClearCommandDeps = { ...noopDeps };

export function setClearCommandDeps(overrides: Partial<ClearCommandDeps>): void {
  deps = { ...deps, ...overrides };
}

export function resetClearCommandDeps(): void {
  deps = { ...noopDeps };
}

export const clearCommand: RegistryCommand = {
  name: 'clear',
  description: 'Clear the conversation and start a new session',
  aliases: ['reset', 'new'],

  isEnabled() {
    return deps.isInteractive();
  },

  async execute(_args: string, ctx: CommandContext) {
    // AC6: session-end hooks run before clear
    await deps.runSessionEndHooks();

    // AC1: empty the message history
    deps.setMessages([]);

    // AC1: generate a new session ID
    const newId = deps.regenerateSessionId({ oldSessionId: ctx.sessionId });

    // AC1: reset file pointer to new session
    deps.resetSessionFilePointer(newId);

    // AC2/AC3: handle tasks
    const tasks = deps.getTasks();
    const bgAgentIds: string[] = [];
    for (const task of tasks) {
      if (task.isBackgrounded) {
        bgAgentIds.push(task.agentId);
      } else {
        deps.killTask(task);
      }
    }
    if (bgAgentIds.length > 0) {
      deps.relinkBackgroundedAgents(newId, bgAgentIds);
    }

    // AC5: reset working directory
    deps.resetWorkingDirectory();

    // AC6: emit cache eviction
    deps.emitCacheEvictionEvent('conversation_clear');

    // AC7: update env for ant users
    if (process.env['USER_TYPE'] === 'ant') {
      process.env['EMBER_SESSION_ID'] = newId;
    }

    // AC4: run session-start hooks; apply hook messages if any
    const hookMsgs = await deps.runSessionStartHooks('clear');
    if (hookMsgs.length > 0) {
      deps.setMessages(hookMsgs);
    }
  },
};
