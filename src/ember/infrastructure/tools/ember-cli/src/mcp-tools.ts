// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// mcp-tools.ts
// Tool builders for Model Context Protocol integration:
//   buildMCPTool, buildListMcpResourcesTool, buildReadMcpResourceTool, buildMcpAuthTool.
// Contract: src/mcp-tools.test.ts (AC1-AC6).

import { buildTool } from './core/tool-interface.ts';
import type { Tool, ToolUseContext, ToolResult } from './core/tool-interface.ts';
import { normalizeMcpServerName, formatMcpToolName } from './mcp-config.ts';
import type { McpServerConfig } from './mcp-config.ts';

// ---------------------------------------------------------------------------
// Exported types (test imports via 'from ./mcp-tools.ts')
// ---------------------------------------------------------------------------

export interface McpResourceDescriptor {
  uri: string;
  name?: string;
  description?: string;
  mimeType?: string;
}

export interface McpResourceContent {
  uri: string;
  text?: string;
  mimeType?: string;
  blob?: string;
}

export interface McpClientInterface {
  serverName: string;
  status: string;
  transportType?: string;
  transportUrl?: string;
  capabilities?: Record<string, unknown>;
  listResources(): Promise<McpResourceDescriptor[]>;
  readResource(uri: string): Promise<McpResourceContent[]>;
  callTool(name: string, input: unknown): Promise<string>;
  hasCapability(cap: string): boolean;
}

export interface McpOAuthFlowInterface {
  startFlow(): Promise<{ url?: string } | void>;
}

export interface McpToolsContext {
  getClients(): McpClientInterface[];
  getClient(name: string): McpClientInterface | undefined;
  startOAuthFlow(serverName: string, config: McpServerConfig): McpOAuthFlowInterface | null;
  replaceAuthToolWithRealTools(serverName: string, prefix: string): void;
  persistBlob(data: Buffer, ext: string, id: string): Promise<string>;
  resourceCache: Map<string, McpResourceDescriptor[]>;
}

// Re-export McpServerConfig for convenience (tests import it from services/mcp-config.ts shim)
export type { McpServerConfig };

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Mime-type → file extension mapping for blob persistence. */
function mimeToExt(mimeType: string | undefined): string {
  if (!mimeType) return '.bin';
  const map: Record<string, string> = {
    'image/png': '.png',
    'image/jpeg': '.jpg',
    'image/gif': '.gif',
    'image/webp': '.webp',
    'application/pdf': '.pdf',
    'text/plain': '.txt',
    'application/json': '.json',
  };
  return map[mimeType] ?? '.bin';
}

function defaultMapResult(content: unknown, toolUseId: string) {
  return {
    type: 'tool_result' as const,
    tool_use_id: toolUseId,
    content: typeof content === 'string' ? content : JSON.stringify(content),
  };
}

// ---------------------------------------------------------------------------
// buildMCPTool — AC1-AC3 + isMcp flag
// ---------------------------------------------------------------------------

interface BuildMCPToolOptions {
  serverName: string;
  toolName: string;
  toolSchema?: Record<string, unknown>;
  description?: string;
  mcpContext: McpToolsContext;
}

type MCPTool = Tool<Record<string, unknown>, string> & { isMcp: boolean };

export function buildMCPTool(opts: BuildMCPToolOptions): MCPTool {
  const { serverName, toolName, toolSchema, mcpContext } = opts;
  const toolId = formatMcpToolName(serverName, toolName);

  const base = buildTool<Record<string, unknown>, string>({
    name: toolId,
    description: () => opts.description ?? `Call ${toolName} on MCP server ${serverName}`,
    inputJSONSchema: toolSchema,
    mapToolResultToToolResultBlockParam: defaultMapResult,
    async call(
      args: Record<string, unknown>,
      _context: ToolUseContext,
    ): Promise<ToolResult<string>> {
      const client = mcpContext.getClient(serverName);
      if (!client || client.status !== 'connected') {
        throw new Error(`MCP server "${serverName}" is not connected`);
      }
      const result = await client.callTool(toolName, args);
      return { data: result };
    },
  });

  return Object.assign(base, { isMcp: true }) as MCPTool;
}

// ---------------------------------------------------------------------------
// buildListMcpResourcesTool — AC1-AC4
// ---------------------------------------------------------------------------

interface ListResourcesInput {
  server?: string;
}

interface ListResourcesEntry extends McpResourceDescriptor {
  server: string;
}

export function buildListMcpResourcesTool(
  mcpContext: McpToolsContext,
): Tool<ListResourcesInput, ListResourcesEntry[]> {
  return buildTool<ListResourcesInput, ListResourcesEntry[]>({
    name: 'mcp__list_resources',
    description: () => 'List available MCP resources across all connected servers',
    mapToolResultToToolResultBlockParam: defaultMapResult,
    async call(
      args: ListResourcesInput,
      _context: ToolUseContext,
    ): Promise<ToolResult<ListResourcesEntry[]>> {
      const clients = mcpContext.getClients();
      const filtered = args.server
        ? clients.filter((c) => c.serverName === args.server)
        : clients;

      const results: ListResourcesEntry[] = [];

      for (const client of filtered) {
        const cacheKey = client.serverName;
        if (mcpContext.resourceCache.has(cacheKey)) {
          const cached = mcpContext.resourceCache.get(cacheKey)!;
          results.push(...cached.map((r) => ({ ...r, server: client.serverName })));
          continue;
        }

        try {
          const resources = await client.listResources();
          mcpContext.resourceCache.set(cacheKey, resources);
          results.push(...resources.map((r) => ({ ...r, server: client.serverName })));
        } catch {
          // Per-server failure is isolated — skip this server
        }
      }

      return { data: results };
    },
  });
}

// ---------------------------------------------------------------------------
// buildReadMcpResourceTool — AC1-AC5
// ---------------------------------------------------------------------------

interface ReadResourceInput {
  server: string;
  uri: string;
}

type ReadResourceEntry =
  | { uri: string; text: string }
  | { uri: string; blobSavedTo: string }
  | { uri: string; text: string; mimeType: string };

export function buildReadMcpResourceTool(
  mcpContext: McpToolsContext,
): Tool<ReadResourceInput, ReadResourceEntry[]> {
  return buildTool<ReadResourceInput, ReadResourceEntry[]>({
    name: 'mcp__read_resource',
    description: () => 'Read an MCP resource by URI',
    mapToolResultToToolResultBlockParam: defaultMapResult,
    async call(
      args: ReadResourceInput,
      _context: ToolUseContext,
    ): Promise<ToolResult<ReadResourceEntry[]>> {
      const client = mcpContext.getClient(args.server);

      if (!client || client.status !== 'connected') {
        throw new Error(`MCP server "${args.server}" is not connected`);
      }
      if (!client.hasCapability('resources')) {
        throw new Error(`MCP server "${args.server}" does not support the resources capability`);
      }

      const contents = await client.readResource(args.uri);
      const entries: ReadResourceEntry[] = [];

      for (const content of contents) {
        if (content.blob !== undefined) {
          // Binary blob — persist to disk
          try {
            const data = Buffer.from(content.blob, 'base64');
            const ext = mimeToExt(content.mimeType);
            const id = `${args.server}-${Date.now()}`;
            const savedPath = await mcpContext.persistBlob(data, ext, id);
            entries.push({ uri: content.uri, blobSavedTo: savedPath });
          } catch (err) {
            const msg = err instanceof Error ? err.message : String(err);
            entries.push({ uri: content.uri, text: `Failed to persist blob: ${msg}` });
          }
        } else {
          entries.push({ uri: content.uri, text: content.text ?? '' });
        }
      }

      return { data: entries };
    },
  });
}

// ---------------------------------------------------------------------------
// buildMcpAuthTool — AC1-AC6
// ---------------------------------------------------------------------------

interface AuthResult {
  status: 'auth_url' | 'unsupported' | 'error';
  authUrl?: string;
  message?: string;
}

export function buildMcpAuthTool(
  serverName: string,
  config: McpServerConfig,
  mcpContext: McpToolsContext,
): Tool<Record<string, unknown>, AuthResult> {
  const toolName = `mcp__${normalizeMcpServerName(serverName)}__authenticate`;

  return buildTool<Record<string, unknown>, AuthResult>({
    name: toolName,
    description: () => `Authenticate with MCP server ${serverName}`,
    mapToolResultToToolResultBlockParam: defaultMapResult,
    async call(
      _args: Record<string, unknown>,
      _context: ToolUseContext,
    ): Promise<ToolResult<AuthResult>> {
      const type = (config as { type?: string }).type;

      // stdio and cloud-proxy do not support OAuth
      if (type === 'stdio') {
        return { data: { status: 'unsupported' } };
      }
      if (type === 'cloud-proxy') {
        return {
          data: {
            status: 'unsupported',
            message: 'Cloud-proxy servers authenticate via the /mcp endpoint. No OAuth flow required.',
          },
        };
      }

      // HTTP / SSE servers — start OAuth flow
      const flow = mcpContext.startOAuthFlow(serverName, config);
      if (!flow) {
        return {
          data: {
            status: 'error',
            message: `No OAuth flow available for server ${serverName}`,
          },
        };
      }

      try {
        const result = await flow.startFlow();
        const url = result && typeof result === 'object' && 'url' in result
          ? (result as { url?: string }).url
          : undefined;

        if (url) {
          return { data: { status: 'auth_url', authUrl: url } };
        }

        // Headless auth completed — swap auth tool for real tools
        mcpContext.replaceAuthToolWithRealTools(serverName, `mcp__${normalizeMcpServerName(serverName)}__`);
        return { data: { status: 'auth_url' } };
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        return { data: { status: 'error', message: msg } };
      }
    },
  });
}
