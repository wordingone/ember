// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// commands/bridge-kick.ts — /bridge-kick slash command.
// Allows internal users to manually trigger bridge operations.

import type { CommandContext } from '../types/command-types.ts';

// ---------------------------------------------------------------------------
// Bridge interface (injectable)
// ---------------------------------------------------------------------------

interface BridgeInterface {
  close: () => void;
  poll: () => void;
  register: () => void;
  reconnectSession: () => void;
  heartbeat: () => void;
  reconnect: () => void;
  getStatus: () => string;
}

interface BridgeKickDeps {
  getUserType: () => string;
  bridge: BridgeInterface;
}

type BridgeKickResult = { type: 'message'; message: string };

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

export function createBridgeKickCommand(deps: BridgeKickDeps) {
  return {
    name: 'bridge-kick',
    description: 'Manually trigger bridge operations (internal use only)',

    isEnabled(): boolean {
      return deps.getUserType() === 'ant';
    },

    async execute(args: string, _ctx: CommandContext): Promise<BridgeKickResult> {
      const sub = args.trim();

      switch (sub) {
        case 'close':
          deps.bridge.close();
          return { type: 'message', message: 'Bridge closed.' };

        case 'poll':
          deps.bridge.poll();
          return { type: 'message', message: 'Bridge polled.' };

        case 'register':
          deps.bridge.register();
          return { type: 'message', message: 'Bridge registered.' };

        case 'reconnect-session':
          deps.bridge.reconnectSession();
          return { type: 'message', message: 'Bridge session reconnected.' };

        case 'heartbeat':
          deps.bridge.heartbeat();
          return { type: 'message', message: 'Bridge heartbeat sent.' };

        case 'reconnect':
          deps.bridge.reconnect();
          return { type: 'message', message: 'Bridge reconnected.' };

        case 'status':
          return { type: 'message', message: deps.bridge.getStatus() };

        default:
          return {
            type: 'message',
            message: `Unknown subcommand: "${sub}". Valid subcommands: close, poll, register, reconnect-session, heartbeat, reconnect, status.`,
          };
      }
    },
  };
}
