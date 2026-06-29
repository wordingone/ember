// types/command-types.ts — shared command interfaces for the slash-command layer.

export interface CommandContext {
  sessionId: string;
  mode: string;
  cwd: string;
}

export interface CommandResult {
  type: 'message';
  message: string;
}

export interface RegistryCommand {
  name: string;
  description: string;
  isEnabled: () => boolean;
  execute: (args: string, ctx: CommandContext) => Promise<CommandResult | void>;
  aliases?: string[];
  type?: string;
  pluginName?: string;
  isBundled?: boolean;
  isWorkflow?: boolean;
  settingsSource?: string;
  availability?: string[];
  disableModelInvocation?: boolean;
  isDynamic?: boolean;
  isMcpSkill?: boolean;
  whenToUse?: string;
}
