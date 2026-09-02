// Tests for config-tool.ts
// Covers AC1-AC9.

import { test, expect, describe } from 'bun:test';
import { buildConfigTool } from './config-tool.ts';
import type { ConfigToolDeps, ConfigOutput } from './config-tool.ts';

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

function makeCtx(): Parameters<ReturnType<typeof buildConfigTool>['call']>[1] {
  return {
    options: {},
    abortController: new AbortController(),
    getAppState: () => ({}),
    setAppState: async () => {},
    setAppStateForTasks: () => {},
    readFileState: new Map(),
    messages: [],
    appendSystemMessage: () => {},
    nestedMemoryAttachmentTriggers: new Set(),
    loadedNestedMemoryPaths: new Set(),
    dynamicSkillDirTriggers: new Set(),
    discoveredSkillNames: new Set(),
    fileReadingLimits: { maxTokens: 100_000, maxSizeBytes: 10_000_000 },
    globLimits: { maxResults: 1000 },
    toolUseId: 'test-config-id',
  } as unknown as Parameters<ReturnType<typeof buildConfigTool>['call']>[1];
}

function makeDeps(overrides: Partial<ConfigToolDeps> = {}): ConfigToolDeps {
  const store = new Map<string, unknown>([['theme', 'light'], ['verbose', false], ['model', null]]);
  const projectStore: Map<string, unknown> = new Map();
  const appState: Map<string, unknown> = new Map();

  return {
    getGlobalConfigValue(path: string[]) {
      const key = path.join('.');
      return store.get(key);
    },
    async setGlobalConfigValue(path: string[], value: unknown) {
      store.set(path.join('.'), value);
    },
    async deleteGlobalConfigKey(path: string[]) {
      store.delete(path.join('.'));
    },
    getProjectSettingsValue(path: string[]) {
      return projectStore.get(path.join('.'));
    },
    async setProjectSettingsValue(path: string[], value: unknown) {
      projectStore.set(path.join('.'), value);
    },
    setAppState(key: string, value: unknown) {
      appState.set(key, value);
    },
    async validateModel(_model: string) {
      // No-op: valid by default
    },
    async runVoicePreflight() {
      // No-op: passes by default
    },
    async askPermission(_message: string) {
      return true; // auto-approve in tests
    },
    emitAnalytics(_event: string, _data: Record<string, unknown>) {},
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// AC1: Read returns current value without permission check
// ---------------------------------------------------------------------------

describe('Config — read', () => {
  test('AC1: read theme returns current value without asking permission', async () => {
    let askCalled = false;
    const deps = makeDeps({
      async askPermission(_msg) {
        askCalled = true;
        return true;
      },
    });
    const tool = buildConfigTool(deps);
    const result = await tool.call(
      { setting: 'theme' },
      makeCtx(),
      async () => true,
      undefined,
    );
    expect(askCalled).toBe(false);
    expect((result.data as ConfigOutput).success).toBe(true);
    expect((result.data as ConfigOutput).operation).toBe('get');
    expect((result.data as ConfigOutput).setting).toBe('theme');
    expect((result.data as ConfigOutput).value).toBe('light');
  });

  test('read model null returns "default"', async () => {
    const deps = makeDeps();
    const tool = buildConfigTool(deps);
    const result = await tool.call(
      { setting: 'model' },
      makeCtx(),
      async () => true,
      undefined,
    );
    expect((result.data as ConfigOutput).value).toBe('default');
  });
});

// ---------------------------------------------------------------------------
// AC2: Write prompts for permission
// ---------------------------------------------------------------------------

describe('Config — write permission', () => {
  test('AC2: write theme prompts for permission and writes on approval', async () => {
    let permissionMessage = '';
    const deps = makeDeps({
      async askPermission(msg: string) {
        permissionMessage = msg;
        return true;
      },
    });
    const tool = buildConfigTool(deps);
    const result = await tool.call(
      { setting: 'theme', value: 'dark' },
      makeCtx(),
      async () => true,
      undefined,
    );
    expect(permissionMessage).toContain('theme');
    expect(permissionMessage).toContain('dark');
    expect((result.data as ConfigOutput).success).toBe(true);
    expect((result.data as ConfigOutput).operation).toBe('set');
    expect((result.data as ConfigOutput).newValue).toBe('dark');
  });

  test('write denied by user returns success: false', async () => {
    const deps = makeDeps({
      async askPermission(_msg) { return false; },
    });
    const tool = buildConfigTool(deps);
    const result = await tool.call(
      { setting: 'theme', value: 'dark' },
      makeCtx(),
      async () => true,
      undefined,
    );
    expect((result.data as ConfigOutput).success).toBe(false);
    expect((result.data as ConfigOutput).error).toContain('denied');
  });
});

// ---------------------------------------------------------------------------
// AC3: String "true" / "false" coerced to boolean
// ---------------------------------------------------------------------------

describe('Config — type coercion', () => {
  test('AC3: "true" string is coerced to boolean true for verbose', async () => {
    const deps = makeDeps();
    const tool = buildConfigTool(deps);
    const result = await tool.call(
      { setting: 'verbose', value: 'true' },
      makeCtx(),
      async () => true,
      undefined,
    );
    expect((result.data as ConfigOutput).success).toBe(true);
    expect((result.data as ConfigOutput).newValue).toBe(true);
  });

  test('"false" string is coerced to boolean false', async () => {
    const deps = makeDeps();
    const tool = buildConfigTool(deps);
    const result = await tool.call(
      { setting: 'verbose', value: 'false' },
      makeCtx(),
      async () => true,
      undefined,
    );
    expect((result.data as ConfigOutput).success).toBe(true);
    expect((result.data as ConfigOutput).newValue).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// AC4: Unknown setting key returns error
// ---------------------------------------------------------------------------

describe('Config — unknown setting', () => {
  test('AC4: unknown setting returns success:false with error', async () => {
    const deps = makeDeps();
    const tool = buildConfigTool(deps);
    const result = await tool.call(
      { setting: 'nonExistentKey' },
      makeCtx(),
      async () => true,
      undefined,
    );
    expect((result.data as ConfigOutput).success).toBe(false);
    expect((result.data as ConfigOutput).error).toContain('Unknown');
  });
});

// ---------------------------------------------------------------------------
// AC5: Invalid value not in allowed options
// ---------------------------------------------------------------------------

describe('Config — option validation', () => {
  test('AC5: invalid editorMode returns error listing valid options', async () => {
    const deps = makeDeps();
    const tool = buildConfigTool(deps);
    const result = await tool.call(
      { setting: 'editorMode', value: 'nano' },
      makeCtx(),
      async () => true,
      undefined,
    );
    expect((result.data as ConfigOutput).success).toBe(false);
    expect((result.data as ConfigOutput).error).toContain('vim');
    expect((result.data as ConfigOutput).error).toContain('emacs');
  });
});

// ---------------------------------------------------------------------------
// AC6: Model write performs async validation
// ---------------------------------------------------------------------------

describe('Config — model validation', () => {
  test('AC6: model write calls validateModel before committing', async () => {
    let validatedModel: string | undefined;
    const deps = makeDeps({
      async validateModel(model: string) {
        validatedModel = model;
      },
    });
    const tool = buildConfigTool(deps);
    await tool.call(
      { setting: 'model', value: 'qwen-3.6' },
      makeCtx(),
      async () => true,
      undefined,
    );
    expect(validatedModel).toBe('qwen-3.6');
  });

  test('AC6: model validation failure returns error', async () => {
    const deps = makeDeps({
      async validateModel(_model: string) {
        throw new Error('Model not found in registry');
      },
    });
    const tool = buildConfigTool(deps);
    const result = await tool.call(
      { setting: 'model', value: 'bad-model' },
      makeCtx(),
      async () => true,
      undefined,
    );
    expect((result.data as ConfigOutput).success).toBe(false);
    expect((result.data as ConfigOutput).error).toContain('Model not found');
  });
});

// ---------------------------------------------------------------------------
// AC7: voiceEnabled runs preflight checks
// ---------------------------------------------------------------------------

describe('Config — voice preflight', () => {
  test('AC7: voiceEnabled:true runs preflight before writing', async () => {
    let preflightRan = false;
    const deps = makeDeps({
      async runVoicePreflight() {
        preflightRan = true;
      },
    });
    const tool = buildConfigTool(deps);
    await tool.call(
      { setting: 'voiceEnabled', value: true },
      makeCtx(),
      async () => true,
      undefined,
    );
    expect(preflightRan).toBe(true);
  });

  test('AC7: voice preflight failure returns error', async () => {
    const deps = makeDeps({
      async runVoicePreflight() {
        throw new Error('ffmpeg not installed. Run: brew install ffmpeg');
      },
    });
    const tool = buildConfigTool(deps);
    const result = await tool.call(
      { setting: 'voiceEnabled', value: true },
      makeCtx(),
      async () => true,
      undefined,
    );
    expect((result.data as ConfigOutput).success).toBe(false);
    expect((result.data as ConfigOutput).error).toContain('ffmpeg');
  });
});

// ---------------------------------------------------------------------------
// AC8: remoteControlAtStartup "default" deletes the key
// ---------------------------------------------------------------------------

describe('Config — delete-on-default', () => {
  test('AC8: remoteControlAtStartup "default" deletes the key', async () => {
    let deletedPath: string[] | undefined;
    const deps = makeDeps({
      async deleteGlobalConfigKey(path: string[]) {
        deletedPath = path;
      },
    });
    const tool = buildConfigTool(deps);
    const result = await tool.call(
      { setting: 'remoteControlAtStartup', value: 'default' },
      makeCtx(),
      async () => true,
      undefined,
    );
    expect((result.data as ConfigOutput).success).toBe(true);
    expect(deletedPath).toBeDefined();
    expect(deletedPath).toContain('remoteControlAtStartup');
  });
});

// ---------------------------------------------------------------------------
// AC9: live state settings synced immediately
// ---------------------------------------------------------------------------

describe('Config — live state sync', () => {
  test('AC9: verbose write syncs to live app state', async () => {
    let syncedKey: string | undefined;
    let syncedValue: unknown = null;
    const deps = makeDeps({
      setAppState(key: string, value: unknown) {
        syncedKey = key;
        syncedValue = value;
      },
    });
    const tool = buildConfigTool(deps);
    await tool.call(
      { setting: 'verbose', value: true },
      makeCtx(),
      async () => true,
      undefined,
    );
    expect(syncedKey).toBe('verbose');
    expect(syncedValue).toBe(true);
  });

  test('AC9: model write syncs mainLoopModel to app state', async () => {
    let syncedKey: string | undefined;
    let syncedValue: unknown = null;
    const deps = makeDeps({
      setAppState(key: string, value: unknown) {
        syncedKey = key;
        syncedValue = value;
      },
    });
    const tool = buildConfigTool(deps);
    await tool.call(
      { setting: 'model', value: 'qwen-3.6-haiku' },
      makeCtx(),
      async () => true,
      undefined,
    );
    expect(syncedKey).toBe('mainLoopModel');
    expect(syncedValue).toBe('qwen-3.6-haiku');
  });
});
