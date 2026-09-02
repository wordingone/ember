// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { describe, expect, test } from 'bun:test';
import {
  readOnlyCommandValidation,
  resolveDefaultShell,
  isPowerShellToolEnabled,
  BashProvider,
  PowerShellProvider,
  BASH_MAX_OUTPUT_DEFAULT,
  BASH_MAX_OUTPUT_UPPER_LIMIT,
} from './shell-provider';

describe('resolveDefaultShell', () => {
  test('AC1: returns bash even on Windows when no override exists', () => {
    // Clear env override to test default
    const savedEnv = process.env['EMBER_DEFAULT_SHELL'];
    delete process.env['EMBER_DEFAULT_SHELL'];
    try {
      expect(resolveDefaultShell()).toBe('bash');
    } finally {
      if (savedEnv !== undefined) process.env['EMBER_DEFAULT_SHELL'] = savedEnv;
    }
  });

  test('EMBER_DEFAULT_SHELL override is used', () => {
    process.env['EMBER_DEFAULT_SHELL'] = 'zsh';
    try {
      expect(resolveDefaultShell()).toBe('zsh');
    } finally {
      delete process.env['EMBER_DEFAULT_SHELL'];
    }
  });

  test('settings defaultShell is used when env is absent', () => {
    const savedEnv = process.env['EMBER_DEFAULT_SHELL'];
    delete process.env['EMBER_DEFAULT_SHELL'];
    try {
      expect(resolveDefaultShell(() => 'fish')).toBe('fish');
    } finally {
      if (savedEnv !== undefined) process.env['EMBER_DEFAULT_SHELL'] = savedEnv;
    }
  });
});

describe('readOnlyCommandValidation', () => {
  test('AC3: git status → true', () => {
    expect(readOnlyCommandValidation('git status')).toBe(true);
  });

  test('AC4: git push → false', () => {
    expect(readOnlyCommandValidation('git push')).toBe(false);
  });

  test('AC5: gh pr merge 42 → false', () => {
    expect(readOnlyCommandValidation('gh pr merge 42')).toBe(false);
  });

  test('git log → true', () => {
    expect(readOnlyCommandValidation('git log --oneline')).toBe(true);
  });

  test('git diff → true', () => {
    expect(readOnlyCommandValidation('git diff HEAD~1')).toBe(true);
  });

  test('git commit → false', () => {
    expect(readOnlyCommandValidation('git commit -m "msg"')).toBe(false);
  });

  test('git stash list → true', () => {
    expect(readOnlyCommandValidation('git stash list')).toBe(true);
  });

  test('git stash pop → false', () => {
    expect(readOnlyCommandValidation('git stash pop')).toBe(false);
  });

  test('gh pr list → true', () => {
    expect(readOnlyCommandValidation('gh pr list')).toBe(true);
  });

  test('gh pr view 1 → true', () => {
    expect(readOnlyCommandValidation('gh pr view 1')).toBe(true);
  });

  test('gh issue list → true', () => {
    expect(readOnlyCommandValidation('gh issue list')).toBe(true);
  });

  test('gh pr create → false', () => {
    expect(readOnlyCommandValidation('gh pr create')).toBe(false);
  });

  test('ls -la → false (not in allowlist)', () => {
    expect(readOnlyCommandValidation('ls -la')).toBe(false);
  });

  test('empty string → false', () => {
    expect(readOnlyCommandValidation('')).toBe(false);
  });
});

describe('isPowerShellToolEnabled', () => {
  test('AC8: Linux → false', () => {
    expect(isPowerShellToolEnabled(false, false, false)).toBe(false);
  });

  test('Windows + privileged internal → true', () => {
    expect(isPowerShellToolEnabled(true, true, false)).toBe(true);
  });

  test('Windows + non-internal + no opt-in → false', () => {
    expect(isPowerShellToolEnabled(true, false, false)).toBe(false);
  });

  test('Windows + non-internal + opt-in → true', () => {
    expect(isPowerShellToolEnabled(true, false, true)).toBe(true);
  });
});

describe('output size limits', () => {
  test('AC6: output exceeding DEFAULT is truncated', () => {
    const provider = new BashProvider();
    const big = 'x'.repeat(BASH_MAX_OUTPUT_DEFAULT + 100);
    const result = provider.truncateOutput(big);
    expect(result.length).toBeLessThan(big.length);
    expect(result).toContain('[Output truncated');
  });

  test('AC7: output exceeding UPPER_LIMIT is capped to upper limit', () => {
    const provider = new BashProvider({ maxOutputBytes: BASH_MAX_OUTPUT_UPPER_LIMIT + 99_999 });
    const veryBig = 'y'.repeat(BASH_MAX_OUTPUT_UPPER_LIMIT + 1000);
    const result = provider.truncateOutput(veryBig);
    expect(result.length).toBeLessThanOrEqual(BASH_MAX_OUTPUT_UPPER_LIMIT + 200);
    expect(result).toContain('[Output truncated');
  });

  test('output within limit is returned unchanged', () => {
    const provider = new BashProvider();
    const small = 'hello world';
    expect(provider.truncateOutput(small)).toBe(small);
  });
});

describe('BashProvider', () => {
  test('buildExecCommand returns bash -c', () => {
    const p = new BashProvider();
    const result = p.buildExecCommand('ls -la');
    expect(result.command).toBe('bash');
    expect(result.args).toContain('-c');
    expect(result.args).toContain('ls -la');
  });

  test('TMUX_SOCKET forwarded in env overrides', () => {
    const p = new BashProvider({ tmuxSocket: '/tmp/tmux.sock' });
    expect(p.getEnvironmentOverrides()['TMUX_SOCKET']).toBe('/tmp/tmux.sock');
  });
});

describe('PowerShellProvider', () => {
  test('buildExecCommand uses -EncodedCommand', () => {
    const p = new PowerShellProvider();
    const result = p.buildExecCommand('Get-Date');
    expect(result.args).toContain('-EncodedCommand');
    expect(result.args.some((a) => a.length > 10)).toBe(true); // has base64 arg
  });

  test('encodeCommand produces base64 decodable as UTF-16LE', () => {
    const encoded = PowerShellProvider.encodeCommand('hello');
    const decoded = Buffer.from(encoded, 'base64').toString('utf16le');
    expect(decoded).toBe('hello');
  });
});
