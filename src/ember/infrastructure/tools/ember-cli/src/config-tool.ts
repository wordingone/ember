// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// config-tool.ts — user-facing /config tool (DI).
// Covers AC1–AC9.

import { buildTool } from './core/tool-interface.ts';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ConfigToolDeps {
  getGlobalConfigValue: (path: string[]) => unknown;
  setGlobalConfigValue: (path: string[], value: unknown) => Promise<void>;
  deleteGlobalConfigKey: (path: string[]) => Promise<void>;
  getProjectSettingsValue: (path: string[]) => unknown;
  setProjectSettingsValue: (path: string[], value: unknown) => Promise<void>;
  setAppState: (key: string, value: unknown) => void;
  validateModel: (model: string) => Promise<void>;
  runVoicePreflight: () => Promise<void>;
  askPermission: (message: string) => Promise<boolean>;
  emitAnalytics: (event: string, data: Record<string, unknown>) => void;
}

export interface ConfigOutput {
  success: boolean;
  operation: 'get' | 'set' | 'delete';
  setting: string;
  value?: unknown;
  newValue?: unknown;
  error?: string;
}

// ---------------------------------------------------------------------------
// Known settings registry
// ---------------------------------------------------------------------------

type SettingKind =
  | 'boolean'
  | 'string'
  | { options: string[] }
  | 'model'
  | 'voice'
  | 'deleteOnDefault';

interface SettingDef {
  kind: SettingKind;
  path: string[];
  liveStateKey?: string;
}

const SETTINGS: Record<string, SettingDef> = {
  theme:                  { kind: 'string',                 path: ['theme'] },
  verbose:                { kind: 'boolean',                path: ['verbose'], liveStateKey: 'verbose' },
  model:                  { kind: 'model',                  path: ['model'], liveStateKey: 'mainLoopModel' },
  voiceEnabled:           { kind: 'voice',                  path: ['voiceEnabled'], liveStateKey: 'voiceEnabled' },
  editorMode:             { kind: { options: ['vim', 'emacs', 'none'] }, path: ['editorMode'] },
  remoteControlAtStartup: { kind: 'deleteOnDefault',        path: ['remoteControlAtStartup'] },
};

// ---------------------------------------------------------------------------
// Type coercion
// ---------------------------------------------------------------------------

function coerceValue(value: unknown, kind: SettingKind): unknown {
  if (value === 'true' && (kind === 'boolean' || kind === 'voice')) return true;
  if (value === 'false' && (kind === 'boolean' || kind === 'voice')) return false;
  return value;
}

// ---------------------------------------------------------------------------
// buildConfigTool
// ---------------------------------------------------------------------------

export function buildConfigTool(deps: ConfigToolDeps) {
  return buildTool<{ setting: string; value?: unknown }, ConfigOutput>({
    name: 'Config',
    description: () => 'Read or write user configuration settings.',
    isReadOnly: (input?: { setting: string; value?: unknown }) => !input?.value,
    mapToolResultToToolResultBlockParam: (content, id) => ({
      type: 'tool_result' as const,
      tool_use_id: id,
      content: JSON.stringify(content),
    }),
    call: async (args, _ctx, _canUse, _parent) => {
      const { setting, value } = args;

      const def = SETTINGS[setting];
      if (!def) {
        return {
          data: {
            success: false,
            operation: 'get' as const,
            setting,
            error: `Unknown setting: "${setting}". Valid settings: ${Object.keys(SETTINGS).join(', ')}`,
          },
        };
      }

      // READ operation
      if (value === undefined) {
        let raw = deps.getGlobalConfigValue(def.path);
        if (raw === null || raw === undefined) raw = 'default';
        return {
          data: {
            success: true,
            operation: 'get' as const,
            setting,
            value: raw,
          },
        };
      }

      // WRITE operation

      // AC3: coerce string booleans
      const coerced = coerceValue(value, def.kind);

      // AC5: option validation
      if (typeof def.kind === 'object' && 'options' in def.kind) {
        if (!def.kind.options.includes(String(coerced))) {
          return {
            data: {
              success: false,
              operation: 'set' as const,
              setting,
              error: `Invalid value for "${setting}". Valid options: ${def.kind.options.join(', ')}`,
            },
          };
        }
      }

      // AC6: model validation
      if (def.kind === 'model') {
        try {
          await deps.validateModel(String(coerced));
        } catch (e) {
          return {
            data: {
              success: false,
              operation: 'set' as const,
              setting,
              error: (e as Error).message,
            },
          };
        }
      }

      // AC7: voice preflight
      if (def.kind === 'voice' && coerced === true) {
        try {
          await deps.runVoicePreflight();
        } catch (e) {
          return {
            data: {
              success: false,
              operation: 'set' as const,
              setting,
              error: (e as Error).message,
            },
          };
        }
      }

      // AC2: ask permission
      const allowed = await deps.askPermission(
        `Allow setting "${setting}" to ${JSON.stringify(coerced)}?`,
      );
      if (!allowed) {
        return {
          data: {
            success: false,
            operation: 'set' as const,
            setting,
            error: 'Permission denied by user',
          },
        };
      }

      // AC8: delete-on-default
      if (def.kind === 'deleteOnDefault' && coerced === 'default') {
        await deps.deleteGlobalConfigKey(def.path);
        return {
          data: {
            success: true,
            operation: 'delete' as const,
            setting,
            newValue: 'default',
          },
        };
      }

      await deps.setGlobalConfigValue(def.path, coerced);

      // AC9: sync live app state
      if (def.liveStateKey) {
        deps.setAppState(def.liveStateKey, coerced);
      }

      deps.emitAnalytics('config_set', { setting, value: coerced });

      return {
        data: {
          success: true,
          operation: 'set' as const,
          setting,
          newValue: coerced,
        },
      };
    },
  });
}
