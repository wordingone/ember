// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// types/command-types.ts — shared command interfaces for the slash-command layer.

export interface CommandContext {
  sessionId: string;
  mode: string;
  cwd: string;
}

export interface CommandResult {
  type: 'message';
  message: string;
  /** Process/command exit code for the CLI's caller; absent means success (0).
   * Added for cond3 inc2a (checkpoint-identity fail-closed commands). */
  exitCode?: number;
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
