// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// command-registry.ts — loads, caches, and queries the slash-command registry.

import type { RegistryCommand } from './types/command-types.ts';
import { createObservatoryCommand } from './commands/observatory.ts';
import { createWatchCommand } from './commands/watch.ts';
import { createFinetuneCommand } from './commands/finetune.ts';
import { createModelCommand } from './commands/model.ts';
import { createTrainCommand } from './commands/train.ts';
import { createAdmitCommand } from './commands/admit.ts';
import { createGoalCommand } from './commands/goal.ts';
import { createWorldStateCommand } from './commands/world-state.ts';
import { createCustodyCommand } from './commands/custody.ts';
import { createBenchmarkCommand } from './commands/benchmark.ts';
import { createSpinePanelCommand } from './components/spine-panel.ts';
import { getModeHistory } from './state/app-state.ts';

export type { RegistryCommand };

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const REMOTE_SAFE_COMMANDS: readonly string[] = [
  'session', 'exit', 'clear', 'help', 'theme', 'color', 'vim',
  'cost', 'usage', 'copy', 'btw', 'feedback', 'plan',
  'keybindings', 'statusline', 'stickers', 'mobile',
];

export const BRIDGE_SAFE_COMMANDS: readonly string[] = [
  'compact', 'clear', 'cost', 'summary', 'releaseNotes', 'files',
];

// ---------------------------------------------------------------------------
// Dependency injection
// ---------------------------------------------------------------------------

interface CommandRegistryDeps {
  getBuiltinCommands: () => RegistryCommand[];
  getSkillDirCommands: (cwd: string) => Promise<RegistryCommand[]>;
  getPluginCommands: () => Promise<RegistryCommand[]>;
  getDynamicSkillCommands: () => Promise<RegistryCommand[]>;
  getMcpCommandList: () => RegistryCommand[];
  isCloudSubscriber: () => boolean;
  isConsoleUser: () => boolean;
  isMcpSkillsEnabled: () => boolean;
}

const defaultDeps: CommandRegistryDeps = {
  getBuiltinCommands: () => [
    createObservatoryCommand({ getModeHistory }),
    createWatchCommand(),
    createFinetuneCommand(),
    createModelCommand(),
    createTrainCommand(),
    createAdmitCommand(),
    createGoalCommand(),
    createWorldStateCommand(),
    createCustodyCommand(),
    createBenchmarkCommand(),
    createSpinePanelCommand(),
  ],
  getSkillDirCommands: async () => [],
  getPluginCommands: async () => [],
  getDynamicSkillCommands: async () => [],
  getMcpCommandList: () => [],
  isCloudSubscriber: () => false,
  isConsoleUser: () => false,
  isMcpSkillsEnabled: () => false,
};

let deps: CommandRegistryDeps = { ...defaultDeps };

export function setCommandRegistryDeps(overrides: Partial<CommandRegistryDeps>): void {
  deps = { ...deps, ...overrides };
}

export function resetCommandRegistryForTests(): void {
  deps = { ...defaultDeps };
  cwdCache.clear();
  pluginCache = null;
}

// ---------------------------------------------------------------------------
// Two-tier cache
// ---------------------------------------------------------------------------

// Per-cwd memoization cache — cleared by clearCommandMemoizationCaches()
const cwdCache = new Map<string, RegistryCommand[]>();

// Plugin cache — cleared only by clearCommandsCache()
let pluginCache: RegistryCommand[] | null = null;

export function clearCommandMemoizationCaches(): void {
  cwdCache.clear();
}

export function clearCommandsCache(): void {
  cwdCache.clear();
  pluginCache = null;
}

// ---------------------------------------------------------------------------
// Availability filtering
// ---------------------------------------------------------------------------

export function meetsAvailabilityRequirement(cmd: RegistryCommand): boolean {
  if (!cmd.availability || cmd.availability.length === 0) return true;
  for (const req of cmd.availability) {
    if (req === 'cloud' && deps.isCloudSubscriber()) return true;
    if (req === 'console' && deps.isConsoleUser()) return true;
  }
  return false;
}

// ---------------------------------------------------------------------------
// Core registry loader
// ---------------------------------------------------------------------------

export async function getCommands(cwd: string): Promise<RegistryCommand[]> {
  const cached = cwdCache.get(cwd);
  if (cached) return cached;

  // Builtins
  const builtins = deps.getBuiltinCommands();

  // Skill-dir commands (per-cwd)
  const skillDir = await deps.getSkillDirCommands(cwd);

  // Plugin commands (shared cache)
  if (pluginCache === null) {
    pluginCache = await deps.getPluginCommands();
  }
  const plugins = pluginCache;

  // Dynamic skill commands
  const dynamic = await deps.getDynamicSkillCommands();

  // MCP commands (only when enabled)
  const mcp = deps.isMcpSkillsEnabled() ? deps.getMcpCommandList() : [];

  // Merge: builtins win over dynamic with same name
  const allNames = new Set<string>(builtins.map((c) => c.name));
  const dedupedDynamic = dynamic.filter((c) => !allNames.has(c.name));

  const merged = [...builtins, ...skillDir, ...plugins, ...dedupedDynamic, ...mcp];

  // Apply availability filter
  const filtered = merged.filter(meetsAvailabilityRequirement);

  cwdCache.set(cwd, filtered);
  return filtered;
}

// ---------------------------------------------------------------------------
// Filtering helpers
// ---------------------------------------------------------------------------

export function filterCommandsForRemoteMode(commands: RegistryCommand[]): RegistryCommand[] {
  const safe = new Set(REMOTE_SAFE_COMMANDS);
  return commands.filter((c) => safe.has(c.name));
}

export function isBridgeSafeCommand(cmd: RegistryCommand): boolean {
  if (cmd.type === 'local-jsx') return false;
  if (cmd.type === 'prompt') return true;
  return BRIDGE_SAFE_COMMANDS.includes(cmd.name);
}

// ---------------------------------------------------------------------------
// Lookup helpers
// ---------------------------------------------------------------------------

export function findCommand(
  nameOrAlias: string,
  commands: RegistryCommand[],
): RegistryCommand | undefined {
  return commands.find(
    (c) => c.name === nameOrAlias || (c.aliases ?? []).includes(nameOrAlias),
  );
}

export function getCommand(nameOrAlias: string, commands: RegistryCommand[]): RegistryCommand {
  const found = findCommand(nameOrAlias, commands);
  if (!found) {
    const available = commands.map((c) => c.name).join(', ');
    throw new Error(
      `Command "${nameOrAlias}" not found. Available: ${available}`,
    );
  }
  return found;
}

export function hasCommand(nameOrAlias: string, commands: RegistryCommand[]): boolean {
  return findCommand(nameOrAlias, commands) !== undefined;
}

// ---------------------------------------------------------------------------
// Description annotation
// ---------------------------------------------------------------------------

export function formatDescriptionWithSource(cmd: RegistryCommand): string {
  const { description, pluginName, isBundled, isWorkflow, settingsSource } = cmd;
  if (pluginName) return `${description} (${pluginName})`;
  if (isBundled) return `${description} (bundled)`;
  if (isWorkflow) return `${description} (workflow)`;
  if (settingsSource) return `${description} (${settingsSource})`;
  return description;
}

// ---------------------------------------------------------------------------
// Skill-tool subsets
// ---------------------------------------------------------------------------

export async function getSkillToolCommands(cwd: string): Promise<RegistryCommand[]> {
  const all = await getCommands(cwd);
  return all.filter(
    (c) => c.type === 'prompt' && !c.disableModelInvocation,
  );
}

export async function getSlashCommandToolSkills(cwd: string): Promise<RegistryCommand[]> {
  const all = await getCommands(cwd);
  return all.filter((c) => c.description || c.whenToUse);
}

export function getMcpSkillCommands(): RegistryCommand[] {
  return deps.getMcpCommandList().filter(
    (c) => c.isMcpSkill && c.type === 'prompt' && !c.disableModelInvocation,
  );
}
