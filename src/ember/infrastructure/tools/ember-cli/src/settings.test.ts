// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, test, beforeEach, afterEach } from 'bun:test';
import { join } from 'path';
import { rm, mkdir, writeFile } from 'fs/promises';
import {
  loadSettingsFromDisk,
  validatePermissionRule,
  updateSettingsForSource,
  getSettingsFilePathForSource,
  SettingsChangeDetector,
  InternalWriteTracker,
  SETTINGS_STABILITY_THRESHOLD_MS,
  _resetSettingsCache,
} from './settings';
import { _resetConfigHomeMemo } from './env-detection';

const TEST_HOME = join(import.meta.dir, '__settings_test_home__');
const TEST_GIT_ROOT = join(TEST_HOME, 'project');
// Project/local settings live OUTSIDE the checkout (#1330); pin the root so the suite
// does not fall back to the real user config home.
const TEST_STATE_ROOT = join(TEST_HOME, 'cockpit-state');

function pause(ms: number) {
  return new Promise<void>((r) => setTimeout(r, ms));
}

beforeEach(async () => {
  process.env['EMBER_HOME'] = TEST_HOME;
  process.env['EMBER_STATE_ROOT'] = TEST_STATE_ROOT;
  _resetConfigHomeMemo();
  _resetSettingsCache();
  try { await rm(TEST_HOME, { recursive: true, force: true }); } catch { /* ok */ }
  await mkdir(join(TEST_HOME, '.ember'), { recursive: true });
  await mkdir(join(TEST_GIT_ROOT, '.git'), { recursive: true });
  await mkdir(TEST_STATE_ROOT, { recursive: true });
});

afterEach(async () => {
  delete process.env['EMBER_HOME'];
  delete process.env['EMBER_STATE_ROOT'];
  _resetConfigHomeMemo();
  _resetSettingsCache();
  try { await rm(TEST_HOME, { recursive: true, force: true }); } catch { /* ok */ }
});

describe('settings cascade', () => {
  test('AC1: policy setting wins over user setting for the same key', async () => {
    const userPath = getSettingsFilePathForSource('user', TEST_GIT_ROOT);
    await writeFile(userPath, JSON.stringify({ model: 'user-sonnet' }), 'utf-8');

    const policySettings = { model: 'policy-haiku' };
    const merged = await loadSettingsFromDisk(TEST_GIT_ROOT, {}, policySettings);
    expect(merged['model']).toBe('policy-haiku');
  });

  test('AC2: array in project settings replaces (not merges with) user array', async () => {
    const userPath = getSettingsFilePathForSource('user', TEST_GIT_ROOT);
    const projectPath = getSettingsFilePathForSource('project', TEST_GIT_ROOT);

    await writeFile(userPath, JSON.stringify({ allowedTools: ['bash'] }), 'utf-8');
    await writeFile(projectPath, JSON.stringify({ allowedTools: ['read', 'write'] }), 'utf-8');

    const merged = await loadSettingsFromDisk(TEST_GIT_ROOT);
    expect(merged['allowedTools']).toEqual(['read', 'write']); // replaced, not merged
  });

  test('missing settings files return empty object (no error)', async () => {
    const merged = await loadSettingsFromDisk(TEST_GIT_ROOT);
    expect(merged).not.toBeNull();
  });

  test('local settings take priority over project settings', async () => {
    const projectPath = getSettingsFilePathForSource('project', TEST_GIT_ROOT);
    const localPath = getSettingsFilePathForSource('local', TEST_GIT_ROOT);

    await writeFile(projectPath, JSON.stringify({ model: 'from-project' }), 'utf-8');
    await writeFile(localPath, JSON.stringify({ model: 'from-local' }), 'utf-8');

    const merged = await loadSettingsFromDisk(TEST_GIT_ROOT);
    expect(merged['model']).toBe('from-local');
  });
});

describe('updateSettingsForSource', () => {
  test('writes and re-reads correctly', async () => {
    await updateSettingsForSource('user', { model: 'haiku' }, TEST_GIT_ROOT);
    const merged = await loadSettingsFromDisk(TEST_GIT_ROOT);
    expect(merged['model']).toBe('haiku');
  });

  test('AC3: internal write does not appear as external change', async () => {
    const tracker = new InternalWriteTracker();
    const userPath = getSettingsFilePathForSource('user', TEST_GIT_ROOT);

    let fired = false;
    const detector = new SettingsChangeDetector(tracker);
    detector.onConfigChange(() => { fired = true; });
    detector.watch(userPath);

    // Write through the tracker — should be suppressed
    tracker.markWrite(userPath);
    await updateSettingsForSource('user', { model: 'suppressed' }, TEST_GIT_ROOT, tracker);
    await pause(SETTINGS_STABILITY_THRESHOLD_MS + 200);

    expect(fired).toBe(false);
    detector.dispose();
  });
});

describe('validatePermissionRule', () => {
  test('AC4: Bash() → error (empty parens)', () => {
    expect(validatePermissionRule('Bash()')).not.toBeNull();
  });

  test('AC5: Bash(git *) → null (valid)', () => {
    expect(validatePermissionRule('Bash(git *)')).toBeNull();
  });

  test('AC6: mcp__server1(tool*) → error (MCP rules disallow wildcards)', () => {
    expect(validatePermissionRule('mcp__server1(tool*)')).not.toBeNull();
  });

  test('valid MCP rule without wildcards passes', () => {
    expect(validatePermissionRule('mcp__server1(exactTool)')).toBeNull();
  });

  test('unbalanced parentheses → error', () => {
    expect(validatePermissionRule('Bash(cmd')).not.toBeNull();
  });

  test('rule without parens → valid', () => {
    expect(validatePermissionRule('Bash')).toBeNull();
  });
});

describe('SettingsChangeDetector', () => {
  test('AC7: fires ConfigChange within 1.5s of external file change', async () => {
    const userPath = getSettingsFilePathForSource('user', TEST_GIT_ROOT);
    await writeFile(userPath, JSON.stringify({ model: 'initial' }), 'utf-8');

    let changed = false;
    const detector = new SettingsChangeDetector();
    detector.onConfigChange(() => { changed = true; });
    detector.watch(userPath);

    // Small delay to let watcher initialize
    await pause(100);

    // Modify the file externally
    await writeFile(userPath, JSON.stringify({ model: 'changed' }), 'utf-8');

    // Wait up to 1.5s for the event
    await pause(SETTINGS_STABILITY_THRESHOLD_MS + 400);

    expect(changed).toBe(true);
    detector.dispose();
  }, 5000);
});
