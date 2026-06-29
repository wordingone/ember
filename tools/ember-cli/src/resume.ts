// resume.ts — /resume, /continue slash command.

import type { RegistryCommand, CommandContext, CommandResult } from './types/command-types.ts';
import type { LogOption } from './types/session-persistence-types.ts';

type PickerResult = { type: 'none' } | { type: 'select'; log: LogOption };

interface ResumeDeps {
  getSessions: () => Promise<LogOption[]>;
  openPicker: (opts: { sessions: LogOption[] }) => Promise<PickerResult>;
  onResume: (sessionId: string, log: LogOption) => void | Promise<void | CommandResult>;
  loadFullLog: (log: LogOption) => Promise<LogOption>;
  writeToClipboard: (text: string) => void;
  checkCrossProjectResume: (log: LogOption) => { type: 'different-project' | 'same-dir' };
  filterResumableSessions: (logs: LogOption[]) => LogOption[];
  resumeHelpMessage: () => string;
}

const noopDeps: ResumeDeps = {
  getSessions: async () => [],
  openPicker: async () => ({ type: 'none' }),
  onResume: () => {},
  loadFullLog: async (log) => log,
  writeToClipboard: () => {},
  checkCrossProjectResume: () => ({ type: 'same-dir' }),
  filterResumableSessions: (logs) => logs,
  resumeHelpMessage: () => 'Session not found.',
};

let deps: ResumeDeps = { ...noopDeps };

export function setResumeDeps(overrides: Partial<ResumeDeps>): void {
  deps = { ...deps, ...overrides };
}

export function resetResumeDeps(): void {
  deps = { ...noopDeps };
}

// ---------------------------------------------------------------------------
// handleSessionSelect
// ---------------------------------------------------------------------------

export async function handleSessionSelect(
  log: LogOption,
  _cwd: string,
): Promise<CommandResult | void> {
  const crossProject = deps.checkCrossProjectResume(log);
  if (crossProject.type === 'different-project') {
    const cmd = `ember -r ${log.sessionId}`;
    deps.writeToClipboard(cmd);
    return {
      type: 'message',
      message: `Session is in a different project. Resume command copied to clipboard: ${cmd}`,
    };
  }

  // Lite log — load full version first
  let target = log;
  if (log.isLite) {
    target = await deps.loadFullLog(log);
  }

  await deps.onResume(log.sessionId, target);
}

// ---------------------------------------------------------------------------
// Command object
// ---------------------------------------------------------------------------

export const resumeCommand: RegistryCommand = {
  name: 'resume',
  description: 'Resume a previous session',
  aliases: ['continue'],
  type: 'local-jsx',

  isEnabled(): boolean {
    return true;
  },

  async execute(args: string, ctx: CommandContext): Promise<CommandResult | void> {
    const allSessions = await deps.getSessions();

    // Remove current session and sidechains, then apply custom filter
    const basic = allSessions.filter(
      (s) => s.sessionId !== ctx.sessionId && !s.isSidechain,
    );
    const sessions = deps.filterResumableSessions(basic);

    // Headless search: if args provided, filter by firstPrompt
    if (args.trim()) {
      const query = args.trim().toLowerCase();
      const matches = sessions.filter((s) =>
        s.firstPrompt.toLowerCase().includes(query),
      );
      if (matches.length !== 1) {
        return { type: 'message', message: deps.resumeHelpMessage() };
      }
      return handleSessionSelect(matches[0]!, ctx.cwd);
    }

    // Interactive picker
    const result = await deps.openPicker({ sessions });
    if (result.type === 'select') {
      return handleSessionSelect(result.log, ctx.cwd);
    }
  },
};
