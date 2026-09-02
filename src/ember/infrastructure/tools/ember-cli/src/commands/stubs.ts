// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// commands/stubs.ts — Disabled / null-export stub slots.
// These hold the shape of features that are not yet enabled or that have been
// replaced by plugin-delivered equivalents. All stubs are hidden from /help and
// never enabled at startup.

import type { CommandContext } from '../types/command-types.ts';

// ---------------------------------------------------------------------------
// Stub shape
// ---------------------------------------------------------------------------

interface StubCommand {
  name: string;
  description: string;
  isEnabled: () => boolean;
  isHidden: true;
  execute: (args: string, ctx: CommandContext) => Promise<{ type: 'none' }>;
}

function makeStub(name: string, description = name): StubCommand {
  return {
    name,
    description,
    isEnabled: (): boolean => false,
    isHidden: true,
    async execute(_args: string, _ctx: CommandContext): Promise<{ type: 'none' }> {
      return { type: 'none' };
    },
  };
}

// ---------------------------------------------------------------------------
// Null-export pattern — feature slots reserved but not yet activated
// ---------------------------------------------------------------------------

export const fork = null;
export const workflows = null;

// ---------------------------------------------------------------------------
// Disabled command stubs
// ---------------------------------------------------------------------------

export const forceSnip = makeStub('force-snip', 'Force a context snip');
export const proactive = makeStub('proactive', 'Proactive suggestions');
export const subscribePr = makeStub('subscribe-pr', 'Subscribe to PR events');
export const torch = makeStub('torch', 'Torch the context');
export const buddy = makeStub('buddy', 'Buddy system pairing');
export const peers = makeStub('peers', 'Peer session listing');
export const issue = makeStub('issue', 'Create or view an issue');
export const bughunter = makeStub('bughunter', 'Bug-hunt mode');
export const summary = makeStub('summary', 'Summarize the session');
export const share = makeStub('share', 'Share the session');
export const antTrace = makeStub('ant-trace', 'Internal trace viewer');
export const autofixPr = makeStub('autofix-pr', 'Auto-fix PR issues');
export const backfillSessions = makeStub('backfill-sessions', 'Backfill session history');
export const breakCache = makeStub('break-cache', 'Break the prompt cache');
export const ctxViz = makeStub('ctx-viz', 'Context visualizer');
export const debugToolCall = makeStub('debug-tool-call', 'Debug a tool call');
export const goodAssistant = makeStub('good-assistant', 'Good-assistant evaluation');
export const mockLimits = makeStub('mock-limits', 'Mock rate limits');
export const oauthRefresh = makeStub('oauth-refresh', 'Force OAuth token refresh');
export const perfIssue = makeStub('perf-issue', 'Report a performance issue');

// Rate-limit stubs
export const resetLimitsCommand = makeStub('reset-limits', 'Reset rate limits');
export const resetLimits = makeStub('reset-limits-user', 'Reset user rate limits');
export const resetLimitsNonInteractive = makeStub(
  'reset-limits-ni',
  'Reset rate limits (non-interactive)',
);

// ---------------------------------------------------------------------------
// Component stubs — functions and components not yet available
// ---------------------------------------------------------------------------

export function launchAssistantCommandHandler(): void {}
export function launchAssistantInstallWizard(): void {}
export function launchAssistantSessionChooser(): void {}
export const AssistantComponent = null;

export const remoteControlServer = {
  handleRemoteControlServer(): void {},
  startRemoteControlServer(): void {},
  stopRemoteControlServer(): void {},
};

export const agentsPlatform = {
  launchAgentsPlatform(): void {},
  handleAgentsPlatform(): void {},
};

// ---------------------------------------------------------------------------
// Aggregate — all disabled stub command objects
// ---------------------------------------------------------------------------

export const ALL_DISABLED_STUBS: StubCommand[] = [
  forceSnip,
  proactive,
  subscribePr,
  torch,
  buddy,
  peers,
  issue,
  bughunter,
  summary,
  share,
  antTrace,
  autofixPr,
  backfillSessions,
  breakCache,
  ctxViz,
  debugToolCall,
  goodAssistant,
  mockLimits,
  oauthRefresh,
  perfIssue,
  resetLimitsCommand,
  resetLimits,
  resetLimitsNonInteractive,
];
