// tag.ts — /tag slash command (ant-user-only session tagging).

import type { RegistryCommand, CommandContext, CommandResult } from './types/command-types.ts';

interface TagCommandDeps {
  isAntUser: () => boolean;
  getCurrentSessionTag: (sessionId: string) => Promise<string | null>;
  saveTag: (sessionId: string, tag: string) => Promise<void>;
  confirmRemoveTag: (existingTag: string) => Promise<boolean>;
  trackEvent: (eventName: string) => void;
  recursivelySanitizeUnicode: (s: string) => string;
}

const noopDeps: TagCommandDeps = {
  isAntUser: () => false,
  getCurrentSessionTag: async () => null,
  saveTag: async () => {},
  confirmRemoveTag: async () => false,
  trackEvent: () => {},
  recursivelySanitizeUnicode: (s) => s,
};

let deps: TagCommandDeps = { ...noopDeps };

export function setTagCommandDeps(overrides: Partial<TagCommandDeps>): void {
  deps = { ...deps, ...overrides };
}

export function _resetTagCommandDepsForTests(): void {
  deps = { ...noopDeps };
}

// ---------------------------------------------------------------------------
// Core logic
// ---------------------------------------------------------------------------

interface TagToggleResult {
  outcome: 'help' | 'added' | 'removed' | 'cancelled';
  message: string;
}

export async function executeTagToggle(
  args: string,
  ctx: CommandContext,
): Promise<TagToggleResult> {
  const trimmed = args.trim();
  if (!trimmed) {
    return {
      outcome: 'help',
      message: 'Usage: /tag <name>  — Tag the current session for later reference.',
    };
  }

  // AC3: sanitize before saving
  const sanitized = deps.recursivelySanitizeUnicode(trimmed);

  const existing = await deps.getCurrentSessionTag(ctx.sessionId);
  if (existing) {
    // AC5: existing tag — confirm removal
    const confirmed = await deps.confirmRemoveTag(existing);
    if (confirmed) {
      // AC6: remove tag
      await deps.saveTag(ctx.sessionId, '');
      deps.trackEvent('ember_tag_command_remove_confirmed');
      return { outcome: 'removed', message: `Tag "${existing}" removed.` };
    } else {
      // AC7: cancelled
      deps.trackEvent('ember_tag_command_remove_cancelled');
      return { outcome: 'cancelled', message: `Tag "${existing}" kept.` };
    }
  }

  // AC4: no existing tag — save new tag
  await deps.saveTag(ctx.sessionId, sanitized);
  deps.trackEvent('ember_tag_command_add');
  return { outcome: 'added', message: `Tag "${sanitized}" added.` };
}

// ---------------------------------------------------------------------------
// Command object
// ---------------------------------------------------------------------------

export const tagCommand: RegistryCommand = {
  name: 'tag',
  description: 'Tag the current session',
  type: 'local-jsx',

  isEnabled(): boolean {
    return deps.isAntUser();
  },

  async execute(args: string, ctx: CommandContext): Promise<CommandResult> {
    const result = await executeTagToggle(args, ctx);
    return { type: 'message', message: result.message };
  },
};
