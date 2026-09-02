import { describe, it, expect, beforeEach, afterEach } from 'bun:test';
import {
  versionCommand,
  buildVersionOutput,
  _setVersionGettersForTests,
  _resetVersionGetters,
} from './version.ts';

describe('version command', () => {
  const origUserType = process.env['USER_TYPE'];

  beforeEach(() => {
    _resetVersionGetters();
    delete process.env['USER_TYPE'];
  });

  afterEach(() => {
    if (origUserType !== undefined) {
      process.env['USER_TYPE'] = origUserType;
    } else {
      delete process.env['USER_TYPE'];
    }
    _resetVersionGetters();
  });

  // AC1: absent for non-ant users
  it('AC1: not enabled for non-ant users', () => {
    delete process.env['USER_TYPE'];
    expect(versionCommand.isEnabled()).toBe(false);
  });

  it('AC1: enabled for ant users', () => {
    process.env['USER_TYPE'] = 'ant';
    expect(versionCommand.isEnabled()).toBe(true);
  });

  // AC2: output includes the version
  it('AC2: buildVersionOutput includes version string', () => {
    _setVersionGettersForTests(
      () => '1.2.3',
      () => '2024-01-01T00:00:00.000Z',
    );
    const out = buildVersionOutput();
    expect(out).toContain('Version: 1.2.3');
  });

  // AC3: output includes build time
  it('AC3: buildVersionOutput includes build time', () => {
    _setVersionGettersForTests(
      () => '1.0.0',
      () => '2024-06-15T12:00:00.000Z',
    );
    const out = buildVersionOutput();
    expect(out).toContain('Build time: 2024-06-15T12:00:00.000Z');
  });

  // AC4: works in non-interactive sessions (execute returns message)
  it('AC4: execute returns a message', async () => {
    process.env['USER_TYPE'] = 'ant';
    _setVersionGettersForTests(() => '2.0.0', () => 'ts');
    const result = await versionCommand.execute('', {
      sessionId: 'test',
      mode: 'default',
      cwd: '/tmp',
    });
    expect(result?.type).toBe('message');
    const msg = (result as { message?: string }).message ?? '';
    expect(msg).toContain('Version: 2.0.0');
    expect(msg).toContain('Build time: ts');
  });
});
