// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// spawn-teammate.ts — Team member spawning (in-process or split-pane).
// Covers AC1–AC9.

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SpawnTeammateConfig {
  name: string;
  prompt: string;
  model?: string;
  plan_mode_required?: boolean;
  use_splitpane?: boolean;
}

export interface SpawnContext {
  cwd: string;
  teamName: string;
  sessionId: string;
  leaderModel?: string;
  leaderPermissionMode?: string;
  leaderHasBypassPermissions?: boolean;
}

export interface TeamMemberStorage {
  listMemberNames(teamName: string): Promise<string[]>;
  registerMember(teamName: string, member: { name: string; agentId: string }): Promise<void>;
}

export interface ColorManager {
  assignColor(name: string): string;
}

export interface InProcessAgentRunner {
  start(params: { name: string; prompt: string; model: string; agentId: string; teamName: string; cwd: string }): void;
}

export interface TmuxPane {
  paneId: string;
  windowName: string;
  sessionName: string;
}

export interface TerminalBackend {
  type: 'tmux' | 'none';
  isInsideTmux(): boolean;
  createPane(params: { windowName: string; sessionName: string }): Promise<TmuxPane>;
  sendKeys(paneId: string, keys: string): void;
}

export interface SpawnTeammateDeps {
  // NOTE: the module consumes only the long-named deps (teamMemberStorage / inProcessRunner /
  // colorManager). The former optional short aliases (storage? / runner? / colorMgr?) were
  // unused here and their BASE typing collided with the test's richer makeDeps intersection
  // (`& { storage: ReturnType<typeof makeStorage>; … }`), which TS contextually resolved against
  // the optional base and rejected (TS2322). The test still supplies/reads storage/runner via
  // its own makeDeps return-type intersection; dropping the dead base aliases here resolves it.
  agentDefinitions: { get(name: string): unknown };
  colorManager: ColorManager;
  teamMemberStorage: TeamMemberStorage;
  defaultTeammateModel: string;
  inProcessRunner: InProcessAgentRunner;
  terminalBackend: TerminalBackend;
  useInProcess: boolean;
  mailbox?: { deliver(params: { name: string; content: string }): Promise<void> };
}

export interface SpawnTeammateResult {
  name: string;
  agentId: string;
  model: string;
  tmux_session_name?: string;
}

// ---------------------------------------------------------------------------
// resolveTeammateModel — AC6
// ---------------------------------------------------------------------------

export function resolveTeammateModel(
  requested: string | undefined,
  leaderModel: string | undefined,
  defaultModel: string,
): string {
  if (requested === 'inherit') return leaderModel ?? defaultModel;
  if (requested !== undefined) return requested;
  return defaultModel;
}

// ---------------------------------------------------------------------------
// generateUniqueTeammateName — AC2
// ---------------------------------------------------------------------------

export async function generateUniqueTeammateName(
  baseName: string,
  teamName: string,
  storage: TeamMemberStorage,
): Promise<string> {
  const existing = await storage.listMemberNames(teamName);
  if (!existing.includes(baseName)) return baseName;

  let suffix = 2;
  while (existing.includes(`${baseName}-${suffix}`)) {
    suffix++;
  }
  return `${baseName}-${suffix}`;
}

// ---------------------------------------------------------------------------
// buildInheritedCliFlags — AC3
// ---------------------------------------------------------------------------

export function buildInheritedCliFlags(params: {
  leaderHasBypassPermissions: boolean;
  planModeRequired?: boolean;
}): string[] {
  const flags: string[] = [];

  // AC3: plan_mode_required overrides bypass propagation
  if (params.leaderHasBypassPermissions && !params.planModeRequired) {
    flags.push('--dangerously-skip-permissions');
  }

  if (params.planModeRequired) {
    flags.push('--plan-mode-required');
  }

  return flags;
}

// ---------------------------------------------------------------------------
// spawnTeammate — AC1–AC9
// ---------------------------------------------------------------------------

export async function spawnTeammate(
  config: SpawnTeammateConfig,
  ctx: SpawnContext,
  deps: SpawnTeammateDeps,
): Promise<SpawnTeammateResult> {
  const storage = deps.teamMemberStorage;
  const colorMgr = deps.colorManager;

  // AC2: deduplicate name
  const uniqueName = await generateUniqueTeammateName(config.name, ctx.teamName, storage);

  // Resolve model — AC6
  const model = resolveTeammateModel(
    config.model,
    ctx.leaderModel,
    deps.defaultTeammateModel,
  );

  const agentId = `agent-${uniqueName}-${Date.now()}`;

  // Assign color
  colorMgr.assignColor(uniqueName);

  // AC1: register in storage
  await storage.registerMember(ctx.teamName, { name: uniqueName, agentId });

  if (deps.useInProcess) {
    // AC4: in-process — deliver via runner, not mailbox
    deps.inProcessRunner.start({
      name: uniqueName,
      prompt: config.prompt,
      model,
      agentId,
      teamName: ctx.teamName,
      cwd: ctx.cwd,
    });

    return { name: uniqueName, agentId, model };
  }

  // Out-of-process — AC8: tmux session routing
  const insideTmux = deps.terminalBackend.isInsideTmux();
  const sessionName = insideTmux ? 'current' : 'ember-swarm';

  const pane = await deps.terminalBackend.createPane({
    windowName: uniqueName,
    sessionName,
  });

  // AC3: build CLI flags
  const cliFlags = buildInheritedCliFlags({
    leaderHasBypassPermissions: ctx.leaderHasBypassPermissions ?? false,
    planModeRequired: config.plan_mode_required,
  });

  // AC9: CLI command with --agent-id and --team-name
  const cmd = [
    'ember',
    ...cliFlags,
    `--agent-id ${agentId}`,
    `--team-name ${ctx.teamName}`,
    `--model ${model}`,
  ].join(' ');

  deps.terminalBackend.sendKeys(pane.paneId, cmd);

  // AC5: out-of-process — deliver prompt via mailbox
  if (deps.mailbox) {
    await deps.mailbox.deliver({ name: uniqueName, content: config.prompt });
  }

  return {
    name: uniqueName,
    agentId,
    model,
    tmux_session_name: sessionName,
  };
}
