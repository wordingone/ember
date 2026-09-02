// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Tests for terminal-setup command.

import { describe, it, expect, beforeEach } from 'bun:test';
import {
  terminalSetupCommand,
  runTerminalSetup,
  backupFile,
  installBindingsForVSCode,
  installBindingsForAlacritty,
  installBindingsForZed,
  getTerminalSetupDescription,
  setTerminalSetupDeps,
  _resetTerminalSetupDeps,
  NATIVE_CSI_U_TERMINALS,
  SUPPORTED_TERMINALS,
  type TerminalSetupDeps,
} from './terminal-setup.ts';
import { writeFile, mkdtemp, rm, readFile } from 'fs/promises';
import { join } from 'path';
import { tmpdir } from 'os';

const makeCtx = () => ({
  sessionId: 'test',
  mode: 'default' as const,
  cwd: '/tmp',
});

const makeNopDeps = (): TerminalSetupDeps => ({
  getNativeCSIuTerminalDisplayName: () => null,
  shouldOfferTerminalSetup: () => true,
  isVSCodeRemoteSSH: () => false,
  isAntUser: () => false,
  setupTerminal: async () => 'Terminal configured.',
  maybeMarkProjectOnboardingComplete: () => {},
  setupShellCompletion: async () => {},
  updateGlobalConfig: async () => {},
});

beforeEach(() => {
  _resetTerminalSetupDeps();
  delete process.env['TERM_PROGRAM'];
  delete process.env['TERMINAL_EMULATOR'];
});

// ---------------------------------------------------------------------------
// AC1: Hidden (isEnabled=false) for native CSI u terminals.
// ---------------------------------------------------------------------------

describe('AC1 — hidden for native CSI u terminals', () => {
  it('isEnabled returns false when getNativeCSIuTerminalDisplayName returns non-null', () => {
    setTerminalSetupDeps({
      getNativeCSIuTerminalDisplayName: () => 'Ghostty',
    });
    expect(terminalSetupCommand.isEnabled()).toBe(false);
  });

  it('isEnabled returns true when getNativeCSIuTerminalDisplayName returns null', () => {
    setTerminalSetupDeps({
      getNativeCSIuTerminalDisplayName: () => null,
    });
    expect(terminalSetupCommand.isEnabled()).toBe(true);
  });

  it('runTerminalSetup returns early message for native CSI u terminals', async () => {
    const deps: TerminalSetupDeps = {
      ...makeNopDeps(),
      getNativeCSIuTerminalDisplayName: () => 'Kitty',
    };
    const result = await runTerminalSetup(deps);
    expect(result.type).toBe('message');
    expect(result.message ?? '').toContain('Kitty');
    expect(result.message ?? '').toContain('natively');
  });

  it('NATIVE_CSI_U_TERMINALS includes Ghostty, Kitty, iTerm2, WezTerm, Warp', () => {
    expect(NATIVE_CSI_U_TERMINALS).toContain('Ghostty');
    expect(NATIVE_CSI_U_TERMINALS).toContain('Kitty');
    expect(NATIVE_CSI_U_TERMINALS).toContain('iTerm2');
    expect(NATIVE_CSI_U_TERMINALS).toContain('WezTerm');
    expect(NATIVE_CSI_U_TERMINALS).toContain('Warp');
  });
});

// ---------------------------------------------------------------------------
// AC2: Unsupported terminal — guidance, no config change.
// ---------------------------------------------------------------------------

describe('AC2 — unsupported terminal shows guidance', () => {
  it('returns a guidance message for unsupported terminals', async () => {
    const deps: TerminalSetupDeps = {
      ...makeNopDeps(),
      getNativeCSIuTerminalDisplayName: () => null,
      shouldOfferTerminalSetup: () => false,
    };
    const result = await runTerminalSetup(deps);
    expect(result.type).toBe('message');
    expect(result.message).toContain('Shift+Enter');
  });
});

// ---------------------------------------------------------------------------
// AC3: VS Code Remote SSH — must install on local machine.
// ---------------------------------------------------------------------------

describe('AC3 — VS Code Remote SSH requires local install', () => {
  it('returns remote-SSH message when isVSCodeRemoteSSH is true', async () => {
    const deps: TerminalSetupDeps = {
      ...makeNopDeps(),
      isVSCodeRemoteSSH: () => true,
    };
    const result = await runTerminalSetup(deps);
    expect(result.type).toBe('message');
    expect((result.message ?? '').toLowerCase()).toContain('local');
  });
});

// ---------------------------------------------------------------------------
// AC4: Existing binding check — warn instead of overwrite.
// ---------------------------------------------------------------------------

describe('AC4 — existing binding check', () => {
  it('installBindingsForVSCode returns warning when binding already exists', async () => {
    const tmpDir = await mkdtemp(join(tmpdir(), 'ts-test-'));
    const kbPath = join(tmpDir, 'keybindings.json');
    await writeFile(kbPath, JSON.stringify([{ key: 'shift+enter', command: 'test' }]), 'utf-8');
    const result = await installBindingsForVSCode(kbPath);
    expect(result.toLowerCase()).toContain('already');
    await rm(tmpDir, { recursive: true });
  });

  it('installBindingsForAlacritty returns warning when binding already exists', async () => {
    const tmpDir = await mkdtemp(join(tmpdir(), 'ts-test-'));
    const cfgPath = join(tmpDir, 'alacritty.toml');
    await writeFile(cfgPath, '[[keyboard.bindings]]\nkey = "Return"\nmods = "Shift+Return"\n', 'utf-8');
    const result = await installBindingsForAlacritty(cfgPath);
    expect(result.toLowerCase()).toContain('already');
    await rm(tmpDir, { recursive: true });
  });

  it('installBindingsForZed returns warning when shift-enter binding already exists in Terminal context', async () => {
    const tmpDir = await mkdtemp(join(tmpdir(), 'ts-test-'));
    const keymapPath = join(tmpDir, 'keymap.json');
    await writeFile(
      keymapPath,
      JSON.stringify([{ context: 'Terminal', bindings: { 'shift-enter': 'test' } }]),
      'utf-8',
    );
    const result = await installBindingsForZed(keymapPath);
    expect(result.toLowerCase()).toContain('already');
    await rm(tmpDir, { recursive: true });
  });
});

// ---------------------------------------------------------------------------
// AC5: Backup created before writing.
// ---------------------------------------------------------------------------

describe('AC5 — backup before write', () => {
  it('backupFile creates a copy with a hex suffix', async () => {
    const tmpDir = await mkdtemp(join(tmpdir(), 'ts-test-'));
    const filePath = join(tmpDir, 'config');
    await writeFile(filePath, 'original content', 'utf-8');
    const backupPath = await backupFile(filePath);
    expect(backupPath).not.toBe(filePath);
    expect(backupPath.startsWith(filePath)).toBe(true);
    const content = await readFile(backupPath, 'utf-8');
    expect(content).toBe('original content');
    await rm(tmpDir, { recursive: true });
  });

  it('installBindingsForVSCode creates a backup when file exists', async () => {
    const tmpDir = await mkdtemp(join(tmpdir(), 'ts-test-'));
    const kbPath = join(tmpDir, 'keybindings.json');
    await writeFile(kbPath, '[]', 'utf-8');
    await installBindingsForVSCode(kbPath);
    // The original directory should now contain a backup file
    const { readdir } = await import('fs/promises');
    const files = await readdir(tmpDir);
    expect(files.length).toBeGreaterThan(1);
    await rm(tmpDir, { recursive: true });
  });
});

// ---------------------------------------------------------------------------
// getTerminalSetupDescription — Apple Terminal vs others.
// ---------------------------------------------------------------------------

describe('getTerminalSetupDescription', () => {
  it('returns Option+Enter description for Apple_Terminal', () => {
    process.env['TERM_PROGRAM'] = 'Apple_Terminal';
    const desc = getTerminalSetupDescription(makeNopDeps());
    expect(desc.toLowerCase()).toContain('option');
    delete process.env['TERM_PROGRAM'];
  });

  it('returns Shift+Enter description for other terminals', () => {
    process.env['TERM_PROGRAM'] = 'iTerm.app';
    const desc = getTerminalSetupDescription(makeNopDeps());
    expect(desc.toLowerCase()).toContain('shift');
    delete process.env['TERM_PROGRAM'];
  });
});

// ---------------------------------------------------------------------------
// Ant users — shell completion is set up.
// ---------------------------------------------------------------------------

describe('ant user shell completion', () => {
  it('calls setupShellCompletion for ant users', async () => {
    let completionCalled = false;
    const deps: TerminalSetupDeps = {
      ...makeNopDeps(),
      isAntUser: () => true,
      setupShellCompletion: async () => { completionCalled = true; },
    };
    await runTerminalSetup(deps);
    expect(completionCalled).toBe(true);
  });

  it('does NOT call setupShellCompletion for non-ant users', async () => {
    let completionCalled = false;
    const deps: TerminalSetupDeps = {
      ...makeNopDeps(),
      isAntUser: () => false,
      setupShellCompletion: async () => { completionCalled = true; },
    };
    await runTerminalSetup(deps);
    expect(completionCalled).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Onboarding marker fires on successful setup.
// ---------------------------------------------------------------------------

describe('onboarding marker', () => {
  it('calls maybeMarkProjectOnboardingComplete on success', async () => {
    let called = false;
    const deps: TerminalSetupDeps = {
      ...makeNopDeps(),
      maybeMarkProjectOnboardingComplete: () => { called = true; },
    };
    await runTerminalSetup(deps);
    expect(called).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// SUPPORTED_TERMINALS list.
// ---------------------------------------------------------------------------

describe('SUPPORTED_TERMINALS', () => {
  it('includes Apple Terminal, VS Code, Alacritty, Zed', () => {
    expect(SUPPORTED_TERMINALS).toContain('Apple Terminal');
    expect(SUPPORTED_TERMINALS).toContain('VS Code');
    expect(SUPPORTED_TERMINALS).toContain('Alacritty');
    expect(SUPPORTED_TERMINALS).toContain('Zed');
  });
});
