// Tests for mcp-tools.ts
// Covers: buildMCPTool (AC1-AC3), buildListMcpResourcesTool (AC1-AC4),
// buildReadMcpResourceTool (AC1-AC5), buildMcpAuthTool (AC1-AC6).

import { test, expect, describe } from 'bun:test';
import {
  buildMCPTool,
  buildListMcpResourcesTool,
  buildReadMcpResourceTool,
  buildMcpAuthTool,
} from './mcp-tools.ts';
import type {
  McpClientInterface,
  McpToolsContext,
  McpOAuthFlowInterface,
  McpResourceDescriptor,
  McpResourceContent,
} from './mcp-tools.ts';
import type { McpServerConfig } from '../services/mcp-config.ts';

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

function makeCtx(): Parameters<ReturnType<typeof buildMCPTool>['call']>[1] {
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
    toolUseId: 'test-tool-use-id',
  } as unknown as Parameters<ReturnType<typeof buildMCPTool>['call']>[1];
}

function makeClient(
  name: string,
  overrides: Partial<McpClientInterface> = {},
): McpClientInterface {
  return {
    serverName: name,
    status: 'connected',
    transportType: 'http',
    transportUrl: 'https://example.com/mcp',
    capabilities: { resources: true },
    async listResources(): Promise<McpResourceDescriptor[]> {
      return [{ uri: 'res://foo', name: 'Foo' }];
    },
    async readResource(uri: string): Promise<McpResourceContent[]> {
      return [{ uri, text: `content of ${uri}` }];
    },
    async callTool(_name: string, _input: unknown): Promise<string> {
      return 'tool result';
    },
    hasCapability(cap: string): boolean {
      return cap === 'resources';
    },
    ...overrides,
  };
}

function makeContext(clients: McpClientInterface[] = []): McpToolsContext {
  const cache = new Map();
  return {
    getClients: () => clients,
    getClient: (name: string) => clients.find((c) => c.serverName === name),
    startOAuthFlow: (_name: string, _config: McpServerConfig) => null,
    replaceAuthToolWithRealTools: (_name: string, _prefix: string) => {},
    persistBlob: async (_data: Buffer, ext: string, id: string) => `/tmp/blob-${id}${ext}`,
    resourceCache: cache,
  };
}

// ---------------------------------------------------------------------------
// buildMCPTool
// ---------------------------------------------------------------------------

describe('buildMCPTool', () => {
  test('AC1: tool name is mcp__<server>__<tool>, not "mcp"', () => {
    const ctx = makeContext([makeClient('github')]);
    const tool = buildMCPTool({
      serverName: 'github',
      toolName: 'search_issues',
      mcpContext: ctx,
    });
    expect(tool.name).toBe('mcp__github__search_issues');
    expect(tool.name).not.toBe('mcp');
  });

  test('AC1: special characters in server name are removed', () => {
    const ctx = makeContext([makeClient('my-server')]);
    const tool = buildMCPTool({
      serverName: 'my-server',
      toolName: 'do_thing',
      mcpContext: ctx,
    });
    // normalizeMcpServerName removes hyphens
    expect(tool.name).toBe('mcp__myserver__do_thing');
  });

  test('AC2: accepts arbitrary input keys', () => {
    const ctx = makeContext([makeClient('github')]);
    const tool = buildMCPTool({
      serverName: 'github',
      toolName: 'search_issues',
      toolSchema: {
        type: 'object',
        properties: {
          q: { type: 'string' },
          limit: { type: 'number' },
        },
      },
      mcpContext: ctx,
    });
    expect(tool.inputJSONSchema).toBeDefined();
    expect(tool.inputJSONSchema?.properties).toHaveProperty('q');
  });

  test('AC3: permission check is always passthrough (allow)', async () => {
    const ctx = makeContext([makeClient('github')]);
    const tool = buildMCPTool({
      serverName: 'github',
      toolName: 'search_issues',
      mcpContext: ctx,
    });
    const result = await tool.checkPermissions({ q: 'bug' }, makeCtx());
    expect(result.behavior).toBe('allow');
  });

  test('isMcp flag is set', () => {
    const ctx = makeContext([makeClient('github')]);
    const tool = buildMCPTool({
      serverName: 'github',
      toolName: 'search',
      mcpContext: ctx,
    });
    expect(tool.isMcp).toBe(true);
  });

  test('call proxies to client.callTool', async () => {
    let capturedToolName: string | null = null;
    let capturedInput: Record<string, unknown> = {};
    const client = makeClient('github', {
      async callTool(name, input) {
        capturedToolName = name;
        capturedInput = input as Record<string, unknown>;
        return 'proxy result';
      },
    });
    const ctx = makeContext([client]);
    const tool = buildMCPTool({ serverName: 'github', toolName: 'search', mcpContext: ctx });
    const result = await tool.call({ q: 'hello' }, makeCtx(), async () => true, undefined);
    expect(result.data).toBe('proxy result');
    expect(capturedToolName!).toBe('search');
    expect(capturedInput).toEqual({ q: 'hello' });
  });

  test('call throws when client not connected', async () => {
    const client = makeClient('github', { status: 'failed' });
    const ctx = makeContext([client]);
    const tool = buildMCPTool({ serverName: 'github', toolName: 'search', mcpContext: ctx });
    await expect(
      tool.call({}, makeCtx(), async () => true, undefined),
    ).rejects.toThrow("not connected");
  });
});

// ---------------------------------------------------------------------------
// buildListMcpResourcesTool
// ---------------------------------------------------------------------------

describe('buildListMcpResourcesTool', () => {
  test('AC1: returns empty array when no servers connected', async () => {
    const ctx = makeContext([]);
    const tool = buildListMcpResourcesTool(ctx);
    const result = await tool.call({}, makeCtx(), async () => true, undefined);
    expect(result.data).toEqual([]);
  });

  test('AC1: connected but listResources returns empty', async () => {
    const client = makeClient('srv', {
      async listResources() { return []; },
    });
    const ctx = makeContext([client]);
    const tool = buildListMcpResourcesTool(ctx);
    const result = await tool.call({}, makeCtx(), async () => true, undefined);
    expect(result.data).toEqual([]);
  });

  test('AC2: per-server connection failure returns empty for that server', async () => {
    const failClient = makeClient('bad', {
      async listResources() { throw new Error('connection error'); },
    });
    const goodClient = makeClient('good', {
      async listResources() { return [{ uri: 'res://ok', name: 'OK' }]; },
    });
    const ctx = makeContext([failClient, goodClient]);
    const tool = buildListMcpResourcesTool(ctx);
    const result = await tool.call({}, makeCtx(), async () => true, undefined);
    // bad server returns nothing, good server's resource is included
    expect(result.data).toHaveLength(1);
    expect((result.data as Array<{ server: string }>)[0]?.server).toBe('good');
  });

  test('AC3: server filter restricts to named server', async () => {
    const a = makeClient('a', {
      async listResources() { return [{ uri: 'res://a', name: 'A' }]; },
    });
    const b = makeClient('b', {
      async listResources() { return [{ uri: 'res://b', name: 'B' }]; },
    });
    const ctx = makeContext([a, b]);
    const tool = buildListMcpResourcesTool(ctx);
    const result = await tool.call({ server: 'a' }, makeCtx(), async () => true, undefined);
    expect(result.data).toHaveLength(1);
    expect((result.data as Array<{ uri: string }>)[0]?.uri).toBe('res://a');
  });

  test('AC4: second call returns cached result (listResources not called again)', async () => {
    let callCount = 0;
    const client = makeClient('cached', {
      async listResources() {
        callCount++;
        return [{ uri: 'res://cached', name: 'Cached' }];
      },
    });
    const ctx = makeContext([client]);
    const tool = buildListMcpResourcesTool(ctx);
    await tool.call({}, makeCtx(), async () => true, undefined);
    await tool.call({}, makeCtx(), async () => true, undefined);
    expect(callCount).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// buildReadMcpResourceTool
// ---------------------------------------------------------------------------

describe('buildReadMcpResourceTool', () => {
  test('AC1: text resource returns { uri, text }', async () => {
    const client = makeClient('srv', {
      async readResource(uri) {
        return [{ uri, text: 'hello world' }];
      },
    });
    const ctx = makeContext([client]);
    const tool = buildReadMcpResourceTool(ctx);
    const result = await tool.call(
      { server: 'srv', uri: 'res://doc' },
      makeCtx(),
      async () => true,
      undefined,
    );
    const entries = result.data as Array<{ uri: string; text?: string }>;
    expect(entries[0]?.text).toBe('hello world');
    expect(entries[0]?.uri).toBe('res://doc');
  });

  test('AC2: binary resource is persisted to disk', async () => {
    const client = makeClient('srv', {
      async readResource(uri) {
        return [{ uri, mimeType: 'image/png', blob: btoa('fake-png-data') }];
      },
    });
    let persistedPath: string | undefined;
    const ctx = makeContext([client]);
    ctx.persistBlob = async (_data, ext, id) => {
      const p = `/blobs/blob-${id}${ext}`;
      persistedPath = p;
      return p;
    };
    const tool = buildReadMcpResourceTool(ctx);
    const result = await tool.call(
      { server: 'srv', uri: 'res://img' },
      makeCtx(),
      async () => true,
      undefined,
    );
    const entries = result.data as Array<{ blobSavedTo?: string }>;
    expect(entries[0]?.blobSavedTo).toBeTruthy();
    expect(entries[0]?.blobSavedTo).toBe(persistedPath);
  });

  test('AC3: no resources capability → error', async () => {
    const client = makeClient('srv', {
      hasCapability: (_cap: string) => false,
    });
    const ctx = makeContext([client]);
    const tool = buildReadMcpResourceTool(ctx);
    await expect(
      tool.call({ server: 'srv', uri: 'res://x' }, makeCtx(), async () => true, undefined),
    ).rejects.toThrow('resources capability');
  });

  test('AC4: not connected → error', async () => {
    const client = makeClient('srv', { status: 'pending' });
    const ctx = makeContext([client]);
    const tool = buildReadMcpResourceTool(ctx);
    await expect(
      tool.call({ server: 'srv', uri: 'res://x' }, makeCtx(), async () => true, undefined),
    ).rejects.toThrow('not connected');
  });

  test('AC5: blob persistence error → text error message, not tool error', async () => {
    const client = makeClient('srv', {
      async readResource(uri) {
        return [{ uri, mimeType: 'image/png', blob: btoa('data') }];
      },
    });
    const ctx = makeContext([client]);
    ctx.persistBlob = async () => { throw new Error('disk full'); };
    const tool = buildReadMcpResourceTool(ctx);
    const result = await tool.call(
      { server: 'srv', uri: 'res://img' },
      makeCtx(),
      async () => true,
      undefined,
    );
    const entries = result.data as Array<{ text?: string }>;
    expect(entries[0]?.text).toContain('disk full');
  });
});

// ---------------------------------------------------------------------------
// buildMcpAuthTool
// ---------------------------------------------------------------------------

describe('buildMcpAuthTool', () => {
  const httpConfig: McpServerConfig = { type: 'http', url: 'https://api.example.com/mcp' };
  const stdioConfig: McpServerConfig = { type: 'stdio', command: 'my-lsp' };
  const proxyConfig: McpServerConfig = { type: 'cloud-proxy' };

  test('AC1: HTTP server returns status=auth_url with authUrl', async () => {
    const flow: McpOAuthFlowInterface = {
      async startFlow() { return { url: 'https://auth.example.com/oauth' }; },
    };
    const ctx = makeContext([]);
    ctx.startOAuthFlow = (_name, _config) => flow;
    const tool = buildMcpAuthTool('myserver', httpConfig, ctx);
    const result = await tool.call({}, makeCtx(), async () => true, undefined);
    const data = result.data as { status: string; authUrl?: string };
    expect(data.status).toBe('auth_url');
    expect(data.authUrl).toBe('https://auth.example.com/oauth');
  });

  test('AC2: stdio server returns status=unsupported', async () => {
    const ctx = makeContext([]);
    const tool = buildMcpAuthTool('myserver', stdioConfig, ctx);
    const result = await tool.call({}, makeCtx(), async () => true, undefined);
    const data = result.data as { status: string };
    expect(data.status).toBe('unsupported');
  });

  test('AC3: claudeai-proxy returns unsupported with /mcp guidance', async () => {
    const ctx = makeContext([]);
    const tool = buildMcpAuthTool('myserver', proxyConfig, ctx);
    const result = await tool.call({}, makeCtx(), async () => true, undefined);
    const data = result.data as { status: string; message: string };
    expect(data.status).toBe('unsupported');
    expect(data.message).toContain('/mcp');
  });

  test('AC4: headless auth calls replaceAuthToolWithRealTools', async () => {
    let replaceCalled = false;
    const flow: McpOAuthFlowInterface = {
      async startFlow() { return {}; }, // no url = headless
    };
    const ctx = makeContext([]);
    ctx.startOAuthFlow = (_name, _config) => flow;
    ctx.replaceAuthToolWithRealTools = (_name, _prefix) => { replaceCalled = true; };
    const tool = buildMcpAuthTool('myserver', httpConfig, ctx);
    await tool.call({}, makeCtx(), async () => true, undefined);
    expect(replaceCalled).toBe(true);
  });

  test('AC5: OAuth failure returns status=error with guidance', async () => {
    const flow: McpOAuthFlowInterface = {
      async startFlow() { throw new Error('server unreachable'); },
    };
    const ctx = makeContext([]);
    ctx.startOAuthFlow = (_name, _config) => flow;
    const tool = buildMcpAuthTool('myserver', httpConfig, ctx);
    const result = await tool.call({}, makeCtx(), async () => true, undefined);
    const data = result.data as { status: string; message: string };
    expect(data.status).toBe('error');
    expect(data.message).toContain('server unreachable');
  });

  test('AC6: headless auth does not return an authUrl', async () => {
    const flow: McpOAuthFlowInterface = {
      async startFlow() { return {}; },
    };
    const ctx = makeContext([]);
    ctx.startOAuthFlow = () => flow;
    const tool = buildMcpAuthTool('myserver', httpConfig, ctx);
    const result = await tool.call({}, makeCtx(), async () => true, undefined);
    const data = result.data as { status: string; authUrl?: string };
    expect(data.status).toBe('auth_url');
    expect(data.authUrl).toBeUndefined();
  });

  test('tool name is mcp__<serverName>__authenticate', () => {
    const ctx = makeContext([]);
    const tool = buildMcpAuthTool('myserver', httpConfig, ctx);
    expect(tool.name).toBe('mcp__myserver__authenticate');
  });
});
