// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// terminal-setup.ts — /terminal-setup command (Shift+Enter / Option+Enter keybinding setup).

import type { CommandContext } from './types/command-types.ts';
import { readFile, writeFile, copyFile } from 'fs/promises';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const NATIVE_CSI_U_TERMINALS: string[] = [
  'Ghostty',
  'Kitty',
  'iTerm2',
  'WezTerm',
  'Warp',
];

export const SUPPORTED_TERMINALS: string[] = [
  'Apple Terminal',
  'VS Code',
  'Alacritty',
  'Zed',
  'Hyper',
];

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface TerminalSetupDeps {
  getNativeCSIuTerminalDisplayName: () => string | null;
  shouldOfferTerminalSetup: () => boolean;
  isVSCodeRemoteSSH: () => boolean;
  isAntUser: () => boolean;
  setupTerminal: () => Promise<string>;
  maybeMarkProjectOnboardingComplete: () => void;
  setupShellCompletion: () => Promise<void>;
  updateGlobalConfig: () => Promise<void>;
}

// ---------------------------------------------------------------------------
// Module-level mutable deps (partial override allowed)
// ---------------------------------------------------------------------------

const DEFAULT_DEPS: TerminalSetupDeps = {
  getNativeCSIuTerminalDisplayName: () => null,
  shouldOfferTerminalSetup: () => true,
  isVSCodeRemoteSSH: () => false,
  isAntUser: () => false,
  setupTerminal: async () => 'Terminal configured.',
  maybeMarkProjectOnboardingComplete: () => {},
  setupShellCompletion: async () => {},
  updateGlobalConfig: async () => {},
};

let moduleDeps: TerminalSetupDeps = { ...DEFAULT_DEPS };

export function setTerminalSetupDeps(overrides: Partial<TerminalSetupDeps>): void {
  moduleDeps = { ...DEFAULT_DEPS, ...overrides };
}

export function _resetTerminalSetupDeps(): void {
  moduleDeps = { ...DEFAULT_DEPS };
}

// ---------------------------------------------------------------------------
// File utilities
// ---------------------------------------------------------------------------

export async function backupFile(filePath: string): Promise<string> {
  const suffix = Math.floor(Math.random() * 0xffffff)
    .toString(16)
    .padStart(6, '0');
  const backupPath = `${filePath}.${suffix}`;
  await copyFile(filePath, backupPath);
  return backupPath;
}

// ---------------------------------------------------------------------------
// installBindingsForVSCode
// ---------------------------------------------------------------------------

export async function installBindingsForVSCode(kbPath: string): Promise<string> {
  let existing: unknown[] = [];
  try {
    const raw = await readFile(kbPath, 'utf-8');
    existing = JSON.parse(raw) as unknown[];
  } catch {
    existing = [];
  }

  const hasBinding = existing.some(
    (b) =>
      typeof b === 'object' &&
      b !== null &&
      'key' in b &&
      typeof (b as Record<string, unknown>)['key'] === 'string' &&
      ((b as Record<string, unknown>)['key'] as string).toLowerCase() === 'shift+enter',
  );

  if (hasBinding) {
    return 'Shift+Enter binding already exists in VS Code keybindings.';
  }

  await backupFile(kbPath);
  const newBindings = [
    ...existing,
    { key: 'shift+enter', command: 'workbench.action.terminal.sendSequence', args: { text: '[13;2u' } },
  ];
  await writeFile(kbPath, JSON.stringify(newBindings, null, 2), 'utf-8');
  return 'Shift+Enter binding installed for VS Code.';
}

// ---------------------------------------------------------------------------
// installBindingsForAlacritty
// ---------------------------------------------------------------------------

export async function installBindingsForAlacritty(cfgPath: string): Promise<string> {
  let content = '';
  try {
    content = await readFile(cfgPath, 'utf-8');
  } catch {
    content = '';
  }

  if (content.includes('Shift+Return') || content.includes('shift+return')) {
    return 'Shift+Enter binding already exists in Alacritty config.';
  }

  if (content.length > 0) {
    await backupFile(cfgPath);
  }

  const binding =
    '\n[[keyboard.bindings]]\nkey = "Return"\nmods = "Shift"\nchars = "\\x1b[13;2u"\n';
  await writeFile(cfgPath, content + binding, 'utf-8');
  return 'Shift+Enter binding installed for Alacritty.';
}

// ---------------------------------------------------------------------------
// installBindingsForZed
// ---------------------------------------------------------------------------

export async function installBindingsForZed(keymapPath: string): Promise<string> {
  let existing: unknown[] = [];
  try {
    const raw = await readFile(keymapPath, 'utf-8');
    existing = JSON.parse(raw) as unknown[];
  } catch {
    existing = [];
  }

  const hasBinding = existing.some((entry) => {
    if (typeof entry !== 'object' || entry === null) return false;
    const e = entry as Record<string, unknown>;
    if (e['context'] !== 'Terminal') return false;
    const bindings = e['bindings'];
    return (
      typeof bindings === 'object' &&
      bindings !== null &&
      'shift-enter' in (bindings as Record<string, unknown>)
    );
  });

  if (hasBinding) {
    return 'shift-enter binding already exists in Zed keymap.';
  }

  await backupFile(keymapPath);
  const newEntry = { context: 'Terminal', bindings: { 'shift-enter': 'terminal::SendText', args: '\x1b[13;2u' } };
  await writeFile(keymapPath, JSON.stringify([...existing, newEntry], null, 2), 'utf-8');
  return 'shift-enter binding installed for Zed.';
}

// ---------------------------------------------------------------------------
// getTerminalSetupDescription
// ---------------------------------------------------------------------------

export function getTerminalSetupDescription(_deps: TerminalSetupDeps): string {
  const termProgram = process.env['TERM_PROGRAM'] ?? '';
  if (termProgram === 'Apple_Terminal') {
    return 'Set up Option+Enter as a newline shortcut in Apple Terminal.';
  }
  return 'Set up Shift+Enter as a newline shortcut in your terminal.';
}

// ---------------------------------------------------------------------------
// runTerminalSetup
// ---------------------------------------------------------------------------

type SetupResult = { type: 'message'; message?: string };

export async function runTerminalSetup(d: TerminalSetupDeps): Promise<SetupResult> {
  const nativeName = d.getNativeCSIuTerminalDisplayName();
  if (nativeName !== null) {
    return {
      type: 'message',
      message: `${nativeName} supports Shift+Enter natively — no setup required.`,
    };
  }

  if (d.isVSCodeRemoteSSH()) {
    return {
      type: 'message',
      message:
        'You are connected via VS Code Remote SSH. Run terminal setup on your local machine to configure keybindings.',
    };
  }

  if (!d.shouldOfferTerminalSetup()) {
    return {
      type: 'message',
      message:
        'Your terminal does not appear to be supported. You can still use Shift+Enter if your terminal forwards the key sequence.',
    };
  }

  const msg = await d.setupTerminal();

  if (d.isAntUser()) {
    await d.setupShellCompletion();
  }

  d.maybeMarkProjectOnboardingComplete();

  return { type: 'message', message: msg };
}

// ---------------------------------------------------------------------------
// terminalSetupCommand
// ---------------------------------------------------------------------------

export const terminalSetupCommand = {
  name: 'terminal-setup',
  type: 'local-jsx',
  description: getTerminalSetupDescription(DEFAULT_DEPS),

  isEnabled(): boolean {
    return moduleDeps.getNativeCSIuTerminalDisplayName() === null;
  },

  async execute(_args: string, _ctx: CommandContext): Promise<SetupResult> {
    return runTerminalSetup(moduleDeps);
  },
};
