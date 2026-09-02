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
  /**
   * Shape of the arguments this command CANNOT run without, e.g.
   * `"--workspace <path> --descriptor <path>"`. Presence is the single declaration that a bare
   * `/name` invocation is a usage error — the command bar reads it here, from the registry
   * itself, so clicking such a command's button composes `/name ` for the operator to finish
   * instead of dispatching an invocation that can only fail. Commands whose bare form does
   * something useful (`/model` -> status, `/benchmark` -> table) leave this unset.
   */
  argumentHint?: string;
}
