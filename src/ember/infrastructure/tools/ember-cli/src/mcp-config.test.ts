// Tests for mcp-config.ts — each test maps to a spec Acceptance Criterion.

import { describe, it, expect, beforeEach } from 'bun:test';
import {
  McpConfigService,
  NoOpMcpSettingsReader,
  isServerPermitted,
  expandEnvVarsInString,
  expandEnvVarsInConfig,
  normalizeMcpServerName,
  formatMcpToolName,
  type McpServerEntry,
  type McpPolicyEntry,
  type McpSettingsReader,
  type McpServerConfig,
} from './mcp-config.ts';
import { tmpdir } from 'os';
import { join } from 'path';
import { writeFile, mkdir, readFile } from 'fs/promises';

// ---------------------------------------------------------------------------
// AC1: Denied server excluded even if on allowedMcpServers
// ---------------------------------------------------------------------------

describe('isServerPermitted — AC1', () => {
  const entry: McpServerEntry = {
    name: 'my-server',
    config: { command: 'run-cmd' },
    scope: 'local',
  };

  it('denies a server present on both allow and deny lists', () => {
    const allowed: McpPolicyEntry[] = [{ name: 'my-server' }];
    const denied: McpPolicyEntry[] = [{ name: 'my-server' }];
    expect(isServerPermitted(entry, allowed, denied)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// AC2: Empty allowedMcpServers = deny all
// ---------------------------------------------------------------------------

describe('isServerPermitted — AC2', () => {
  const entry: McpServerEntry = {
    name: 'any-server',
    config: {},
    scope: 'user',
  };

  it('blocks all servers when allowedMcpServers is an empty array', () => {
    expect(isServerPermitted(entry, [], undefined)).toBe(false);
  });

  it('permits all when both lists are absent/undefined', () => {
    expect(isServerPermitted(entry, undefined, undefined)).toBe(true);
  });

  it('permits all when both are null-equivalent (absent)', () => {
    // absent = undefined in practice
    expect(isServerPermitted(entry, undefined, undefined)).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// AC3: Scope priority — local > managed (same-name shadowing)
// ---------------------------------------------------------------------------

describe('McpConfigService — AC3 scope priority', () => {
  it('local scope entry shadows managed scope entry with the same name', async () => {
    const svc = new McpConfigService();
    svc.addMcpConfig('shared', { command: 'managed-cmd' }, 'managed');
    svc.addMcpConfig('shared', { command: 'local-cmd' }, 'local');

    const entries = await svc.getEmberMcpConfigs();
    const found = entries.find((e) => e.name === 'shared');
    expect(found?.scope).toBe('local');
    expect(found?.config.command).toBe('local-cmd');
  });

  it('returns managed scope entry when local is absent', async () => {
    const svc = new McpConfigService();
    svc.addMcpConfig('only-managed', { command: 'managed-cmd' }, 'managed');

    const entries = await svc.getEmberMcpConfigs();
    const found = entries.find((e) => e.name === 'only-managed');
    expect(found?.scope).toBe('managed');
  });
});

// ---------------------------------------------------------------------------
// AC4: ${VAR:-default} expansion
// ---------------------------------------------------------------------------

describe('expandEnvVarsInString — AC4', () => {
  it('uses the default when the var is not set', () => {
    const result = expandEnvVarsInString('${__UNSET_VAR_XYZ:-fallback}');
    expect(result).toBe('fallback');
  });

  it('uses the env value when the var is set', () => {
    process.env['__TEST_MCP_VAR'] = 'actual';
    const result = expandEnvVarsInString('${__TEST_MCP_VAR:-fallback}');
    delete process.env['__TEST_MCP_VAR'];
    expect(result).toBe('actual');
  });

  it('expands ${VAR} with empty string when var is absent', () => {
    const result = expandEnvVarsInString('prefix-${__UNSET_VAR_ABC}-suffix');
    expect(result).toBe('prefix--suffix');
  });

  it('expands env vars in config command, args, and env values', () => {
    process.env['__CMD_VAR'] = 'node';
    const config: McpServerConfig = {
      command: '${__CMD_VAR}',
      args: ['${__UNSET_ARG:-default-arg}'],
      env: { KEY: '${__CMD_VAR}-suffix' },
    };
    const expanded = expandEnvVarsInConfig(config);
    delete process.env['__CMD_VAR'];
    expect(expanded.command).toBe('node');
    expect(expanded.args?.[0]).toBe('default-arg');
    expect(expanded.env?.['KEY']).toBe('node-suffix');
  });
});

// ---------------------------------------------------------------------------
// AC5: fetchCloudMcpConfigsIfEligible fetches at most once
// ---------------------------------------------------------------------------

describe('McpConfigService — AC5 memoized cloud fetch', () => {
  it('calls the fetcher exactly once across multiple invocations', async () => {
    let callCount = 0;
    const fetcher = async () => {
      callCount++;
      return { 'ai-server': { command: 'ai-cmd' } } as Record<string, McpServerConfig>;
    };

    const svc = new McpConfigService(process.cwd(), new NoOpMcpSettingsReader(), fetcher);
    await svc.fetchCloudMcpConfigsIfEligible();
    await svc.fetchCloudMcpConfigsIfEligible();
    await svc.fetchCloudMcpConfigsIfEligible();

    expect(callCount).toBe(1);
  });

  it('returns empty when no fetcher is provided', async () => {
    const svc = new McpConfigService();
    const result = await svc.fetchCloudMcpConfigsIfEligible();
    expect(result).toEqual({});
  });
});

// ---------------------------------------------------------------------------
// AC6: Tool name format mcp__<serverName>__<toolName>
// ---------------------------------------------------------------------------

describe('formatMcpToolName — AC6', () => {
  it('formats a basic tool name correctly', () => {
    expect(formatMcpToolName('my-server', 'my_tool')).toBe('mcp__myserver__my_tool');
  });

  it('normalizes spaces to underscores in server name', () => {
    expect(formatMcpToolName('my server', 'tool')).toBe('mcp__my_server__tool');
  });

  it('removes special chars from server name', () => {
    expect(formatMcpToolName('my-server!', 'tool')).toBe('mcp__myserver__tool');
  });
});

describe('normalizeMcpServerName', () => {
  it('replaces spaces with underscores', () => {
    expect(normalizeMcpServerName('my server')).toBe('my_server');
  });

  it('removes hyphens and other special chars', () => {
    expect(normalizeMcpServerName('my-server')).toBe('myserver');
  });

  it('collapses multiple underscores', () => {
    expect(normalizeMcpServerName('my  server')).toBe('my__server');
  });
});

// ---------------------------------------------------------------------------
// AC7: parseMcpConfigFromFilePath and writeMcpjsonFile
// ---------------------------------------------------------------------------

describe('McpConfigService — AC7 file I/O', () => {
  it('parseMcpConfigFromFilePath reads and registers servers at local scope', async () => {
    const dir = join(tmpdir(), `mcp-test-${Date.now()}`);
    await mkdir(dir, { recursive: true });
    const filePath = join(dir, '.mcp.json');
    const content = JSON.stringify({
      mcpServers: {
        'test-server': { command: 'test-cmd', type: 'stdio' },
      },
    });
    await writeFile(filePath, content, 'utf-8');

    const svc = new McpConfigService();
    const parsed = await svc.parseMcpConfigFromFilePath(filePath);

    expect(parsed.mcpServers?.['test-server']?.command).toBe('test-cmd');
    const entries = await svc.getEmberMcpConfigs();
    const found = entries.find((e) => e.name === 'test-server');
    expect(found?.scope).toBe('local');
    expect(found?.config.command).toBe('test-cmd');
  });

  it('writeMcpjsonFile writes local-scope configs back to .mcp.json', async () => {
    const dir = join(tmpdir(), `mcp-write-test-${Date.now()}`);
    await mkdir(dir, { recursive: true });

    const svc = new McpConfigService(dir);
    svc.addMcpConfig('written-server', { command: 'written-cmd', type: 'stdio' }, 'local');
    await svc.writeMcpjsonFile();

    const written = await readFile(join(dir, '.mcp.json'), 'utf-8');
    const parsed = JSON.parse(written) as { mcpServers?: Record<string, McpServerConfig> };
    expect(parsed.mcpServers?.['written-server']?.command).toBe('written-cmd');
  });
});

// ---------------------------------------------------------------------------
// Additional: getMcpConfigsByScope grouping
// ---------------------------------------------------------------------------

describe('McpConfigService — getMcpConfigsByScope', () => {
  it('returns servers grouped by scope without policy filtering', () => {
    const svc = new McpConfigService();
    svc.addMcpConfig('srv-a', { command: 'cmd-a' }, 'local');
    svc.addMcpConfig('srv-b', { command: 'cmd-b' }, 'user');

    const byScope = svc.getMcpConfigsByScope();
    expect(byScope['local']?.['srv-a']?.command).toBe('cmd-a');
    expect(byScope['user']?.['srv-b']?.command).toBe('cmd-b');
    expect(byScope['managed']).toEqual({});
  });
});

// ---------------------------------------------------------------------------
// Additional: policy matching by command and url
// ---------------------------------------------------------------------------

describe('isServerPermitted — policy matching variants', () => {
  it('matches by command', () => {
    const entry: McpServerEntry = {
      name: 'srv',
      config: { command: 'specific-cmd' },
      scope: 'local',
    };
    expect(isServerPermitted(entry, [{ command: 'specific-cmd' }], undefined)).toBe(true);
    expect(isServerPermitted(entry, undefined, [{ command: 'specific-cmd' }])).toBe(false);
  });

  it('matches by url', () => {
    const entry: McpServerEntry = {
      name: 'srv',
      config: { url: 'https://example.com/mcp' },
      scope: 'local',
    };
    expect(isServerPermitted(entry, [{ url: 'https://example.com/mcp' }], undefined)).toBe(true);
    expect(isServerPermitted(entry, undefined, [{ url: 'https://example.com/mcp' }])).toBe(false);
  });
});
