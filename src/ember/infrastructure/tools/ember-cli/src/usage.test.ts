import { describe, it, expect } from 'bun:test';
import { usageCommand } from './usage.ts';

describe('usage command', () => {
  // AC1: command has availability gate for cloud
  it('is restricted to cloud surface', () => {
    expect(usageCommand.availability).toContain('cloud');
  });

  it('has name "usage" and type "local-jsx"', () => {
    expect(usageCommand.name).toBe('usage');
    expect(usageCommand.type).toBe('local-jsx');
  });

  it('is enabled', () => {
    expect(usageCommand.isEnabled()).toBe(true);
  });

  // AC2, AC3: headless fallback (TUI renders Settings with defaultTab='Usage')
  it('execute returns none in headless context', async () => {
    const result = await usageCommand.execute('', {
      sessionId: 'test',
      mode: 'default',
      cwd: '/tmp',
    });
    expect(result).toEqual({ type: 'none' });
  });
});
