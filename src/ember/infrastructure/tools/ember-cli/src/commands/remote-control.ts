// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// commands/remote-control.ts — /remote-control (/rc) slash command.

import type { CommandContext } from '../types/command-types.ts';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface RemoteControlDeps {
  isBridgeModeEnabled: () => boolean;
  isBridgeEligible: () => boolean;
  isReplBridgeEnabled: () => boolean;
  isReplBridgeConnected: () => boolean;
  getSessionUrl: () => string;
  getConnectUrl: () => string;
  isSessionActive: () => boolean;
  setReplBridgeEnabled: (v: boolean) => void;
  setReplBridgeOutboundOnly: (v: boolean) => void;
  setShowRemoteCallout: (v: boolean) => void;
  setReplBridgeInitialName: (v: string) => void;
  runPrerequisiteChecks: () => Promise<string | null>;
  shouldShowRemoteCallout: () => boolean;
  generateQrCode: (url: string) => string;
  emitAnalytics: (event: string, props: { action: string }) => void;
  renderBridgeDisconnectDialog: (props: {
    onContinue: () => void;
    onDisconnect: () => void;
    onShowQr: () => void;
  }) => Promise<void>;
}

// ---------------------------------------------------------------------------
// createRemoteControlCommand
// ---------------------------------------------------------------------------

type RemoteControlResult = { type: 'message'; message: string } | { type: 'none' };

export function createRemoteControlCommand(deps: RemoteControlDeps) {
  return {
    name: 'remote-control',
    type: 'local-jsx',
    description: 'Enable or disable Remote Control to use Ember from your phone or another device',
    aliases: ['rc'],

    isEnabled(): boolean {
      return deps.isBridgeModeEnabled() && deps.isBridgeEligible();
    },

    async execute(_args: string, _ctx: CommandContext): Promise<RemoteControlResult> {
      if (deps.isReplBridgeEnabled()) {
        // Bridge is active — show disconnect dialog
        let result: RemoteControlResult = { type: 'none' };

        await deps.renderBridgeDisconnectDialog({
          onContinue() {
            result = { type: 'none' };
          },
          onDisconnect() {
            deps.setReplBridgeEnabled(false);
            deps.emitAnalytics('remote_control', { action: 'disconnect' });
            result = { type: 'none' };
          },
          onShowQr() {
            const url = deps.getConnectUrl();
            const qr = deps.generateQrCode(url);
            result = { type: 'message', message: qr };
          },
        });

        return result;
      }

      // Bridge not active — run prerequisites and enable
      const errorMsg = await deps.runPrerequisiteChecks();
      if (errorMsg !== null) {
        deps.emitAnalytics('remote_control', { action: 'preflight_failed' });
        return { type: 'message', message: errorMsg };
      }

      deps.setReplBridgeEnabled(true);
      deps.emitAnalytics('remote_control', { action: 'connect' });
      return { type: 'message', message: 'Remote Control connecting…' };
    },
  };
}
