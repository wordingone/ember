// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/mcp-config.ts
// MCP server configuration management: multi-scope registry, env-var expansion,
// allow/deny policy enforcement, tool-name normalization, and file I/O.

import { readFile, writeFile, mkdir } from 'fs/promises';
import { join } from 'path';

// ---- Types ----

/** Base shape shared by all MCP server configuration variants. */
export interface McpServerConfigBase {
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  url?: string;
  type?: string;
  headers?: Record<string, string>;
}

/** Full MCP server configuration (allows extra fields for future variants). */
export type McpServerConfig = McpServerConfigBase & Record<string, unknown>;

/**
 * Configuration scope hierarchy.
 * Priority for getEmberMcpConfigs(): local > user > managed; others pass through.
 */
export type ConfigScope =
  | 'local'
  | 'managed'
  | 'user'
  | 'project'
  | 'enterprise'
  | 'hosted'
  | 'dynamic';

/** A registered MCP server entry with its resolved scope. */
export interface McpServerEntry {
  name: string;
  config: McpServerConfig;
  scope: ConfigScope;
}

/**
 * Policy entry used to allow or deny MCP servers.
 * Match is attempted against name, command, or url.
 */
export interface McpPolicyEntry {
  name?: string;
  command?: string | string[];
  url?: string;
}

/** Reads a server configuration from an external source (e.g., user settings). */
export interface McpSettingsReader {
  read(): Promise<McpServerConfig | undefined>;
}

/** Shape of an .mcp.json file on disk. */
export interface McpJsonConfig {
  mcpServers?: Record<string, McpServerConfig>;
}

// ---- Env-var expansion ----

/**
 * Expands shell-style environment variable references in `str`.
 * Supports:
 *   ${VAR}          → process.env.VAR or '' when unset
 *   ${VAR:-default} → process.env.VAR or 'default' when unset/empty
 */
export function expandEnvVarsInString(str: string): string {
  // Handle ${VAR:-default} form first.
  let result = str.replace(/\$\{([^}:]+):-([^}]*)\}/g, (_match, varName: string, defaultVal: string) => {
    const value = process.env[varName.trim()];
    return value !== undefined && value !== '' ? value : defaultVal;
  });
  // Then handle plain ${VAR} form.
  result = result.replace(/\$\{([^}]+)\}/g, (_match, varName: string) => {
    return process.env[varName.trim()] ?? '';
  });
  return result;
}

/**
 * Returns a new McpServerConfig with environment variables expanded in
 * command, args array elements, and env record values.
 */
export function expandEnvVarsInConfig(config: McpServerConfig): McpServerConfig {
  const expanded: McpServerConfig = { ...config };

  if (typeof expanded.command === 'string') {
    expanded.command = expandEnvVarsInString(expanded.command);
  }
  if (Array.isArray(expanded.args)) {
    expanded.args = (expanded.args as string[]).map((a) =>
      typeof a === 'string' ? expandEnvVarsInString(a) : a,
    );
  }
  if (expanded.env !== undefined && typeof expanded.env === 'object') {
    const newEnv: Record<string, string> = {};
    for (const [k, v] of Object.entries(expanded.env as Record<string, string>)) {
      newEnv[k] = typeof v === 'string' ? expandEnvVarsInString(v) : v;
    }
    expanded.env = newEnv;
  }

  return expanded;
}

// ---- Name normalization ----

/**
 * Normalizes an MCP server name for use in tool identifiers.
 * Spaces → underscores; hyphens and other non-alphanumeric non-underscore
 * characters are removed.
 */
export function normalizeMcpServerName(name: string): string {
  // Replace spaces with underscores first (preserving count).
  let normalized = name.replace(/ /g, '_');
  // Remove all characters that are not alphanumeric or underscore.
  normalized = normalized.replace(/[^a-zA-Z0-9_]/g, '');
  return normalized;
}

/**
 * Formats an MCP tool name in the canonical form:
 *   mcp__{normalizedServerName}__{toolName}
 */
export function formatMcpToolName(serverName: string, toolName: string): string {
  return `mcp__${normalizeMcpServerName(serverName)}__${toolName}`;
}

// ---- Policy matching ----

function matchesPolicy(entry: McpServerEntry, policy: McpPolicyEntry): boolean {
  if (policy.name !== undefined && policy.name === entry.name) return true;

  if (policy.command !== undefined) {
    const serverCmd = entry.config.command;
    if (serverCmd !== undefined) {
      if (Array.isArray(policy.command)) {
        if ((policy.command as string[]).some((c) => c === serverCmd)) return true;
      } else if (policy.command === serverCmd) {
        return true;
      }
    }
  }

  if (policy.url !== undefined && policy.url === entry.config.url) return true;

  return false;
}

/**
 * Returns true when `entry` is permitted by the given allow/deny policy.
 *
 * Rules (in priority order):
 * 1. If `denied` is defined and the entry matches any deny entry → false.
 * 2. If `allowed` is undefined → true (no allowlist = allow all).
 * 3. If `allowed` is empty → false (empty allowlist = deny all).
 * 4. If the entry matches any allow entry → true.
 * 5. Otherwise → false.
 */
export function isServerPermitted(
  entry: McpServerEntry,
  allowed: McpPolicyEntry[] | undefined,
  denied: McpPolicyEntry[] | undefined,
): boolean {
  // Deny takes absolute precedence.
  if (denied !== undefined && denied.some((d) => matchesPolicy(entry, d))) {
    return false;
  }

  // No allowlist = allow all.
  if (allowed === undefined) return true;

  // Empty allowlist = deny all.
  if (allowed.length === 0) return false;

  // Must match at least one allow entry.
  return allowed.some((a) => matchesPolicy(entry, a));
}

// ---- No-op settings reader ----

/** Stub McpSettingsReader that never returns a configuration. */
export class NoOpMcpSettingsReader implements McpSettingsReader {
  read(): Promise<McpServerConfig | undefined> {
    return Promise.resolve(undefined);
  }
}

// ---- Scope priority for getEmberMcpConfigs ----

// Higher index = higher priority (local wins over managed).
const SCOPE_PRIORITY: Record<ConfigScope, number> = {
  local: 6,
  project: 5,
  user: 4,
  enterprise: 3,
  hosted: 2,
  managed: 1,
  dynamic: 0,
};

// ---- McpConfigService ----

/**
 * Manages MCP server configurations across multiple scopes.
 * Provides scope-aware merging, file I/O, env-var expansion, and cloud config fetching.
 */
export class McpConfigService {
  private readonly configDir: string;
  private readonly reader: McpSettingsReader;
  private readonly cloudFetcher?: () => Promise<Record<string, McpServerConfig>>;

  // Internal registry: scope → name → config
  private readonly registry = new Map<ConfigScope, Map<string, McpServerConfig>>();

  // Memoized cloud fetch result.
  private cloudFetchResult: Record<string, McpServerConfig> | null = null;

  constructor(
    configDir?: string,
    reader?: McpSettingsReader,
    fetcher?: () => Promise<Record<string, McpServerConfig>>,
  ) {
    this.configDir = configDir ?? process.cwd();
    this.reader = reader ?? new NoOpMcpSettingsReader();
    this.cloudFetcher = fetcher;
  }

  /** Registers a server configuration at the specified scope. */
  addMcpConfig(name: string, config: McpServerConfig, scope: ConfigScope): void {
    let scopeMap = this.registry.get(scope);
    if (scopeMap === undefined) {
      scopeMap = new Map();
      this.registry.set(scope, scopeMap);
    }
    scopeMap.set(name, config);
  }

  /**
   * Returns the merged list of ember MCP server entries with scope priority applied.
   * When two scopes define a server with the same name, the higher-priority scope wins.
   */
  async getEmberMcpConfigs(): Promise<McpServerEntry[]> {
    // Build a flat list of all entries across all scopes.
    const allEntries: McpServerEntry[] = [];
    for (const [scope, scopeMap] of this.registry) {
      for (const [name, config] of scopeMap) {
        allEntries.push({ name, config, scope });
      }
    }

    // For each name, keep only the highest-priority scope entry.
    const byName = new Map<string, McpServerEntry>();
    for (const entry of allEntries) {
      const existing = byName.get(entry.name);
      if (
        existing === undefined ||
        (SCOPE_PRIORITY[entry.scope] ?? 0) > (SCOPE_PRIORITY[existing.scope] ?? 0)
      ) {
        byName.set(entry.name, entry);
      }
    }

    return Array.from(byName.values());
  }

  /**
   * Returns all registered servers grouped by scope, without priority filtering.
   * Every known scope is present as a key (with an empty object when no entries).
   */
  getMcpConfigsByScope(): Record<ConfigScope, Record<string, McpServerConfig>> {
    const allScopes: ConfigScope[] = [
      'local', 'managed', 'user', 'project', 'enterprise', 'hosted', 'dynamic',
    ];
    const result = {} as Record<ConfigScope, Record<string, McpServerConfig>>;
    for (const scope of allScopes) {
      result[scope] = {};
    }
    for (const [scope, scopeMap] of this.registry) {
      const out: Record<string, McpServerConfig> = result[scope] ?? {};
      for (const [name, config] of scopeMap) {
        out[name] = config;
      }
      result[scope] = out;
    }
    return result;
  }

  /**
   * Reads and parses an .mcp.json file, registers its servers at local scope,
   * and returns the parsed config object.
   * Returns null when the file cannot be read or parsed.
   */
  async parseMcpConfigFromFilePath(filePath: string): Promise<McpJsonConfig> {
    try {
      const raw = await readFile(filePath, 'utf-8');
      const parsed = JSON.parse(raw) as McpJsonConfig;
      if (parsed.mcpServers !== undefined && typeof parsed.mcpServers === 'object') {
        for (const [name, config] of Object.entries(parsed.mcpServers)) {
          this.addMcpConfig(name, config as McpServerConfig, 'local');
        }
      }
      return parsed;
    } catch (err) {
      // A missing or malformed config file is an error the caller must handle,
      // not a silent null — surfacing it keeps the parsed result non-nullable.
      throw err instanceof Error ? err : new Error(String(err));
    }
  }

  /**
   * Writes local-scope configurations to {configDir}/.mcp.json.
   */
  async writeMcpjsonFile(): Promise<void> {
    const localMap = this.registry.get('local') ?? new Map<string, McpServerConfig>();
    const mcpServers: Record<string, McpServerConfig> = {};
    for (const [name, config] of localMap) {
      mcpServers[name] = config;
    }
    const content: McpJsonConfig = { mcpServers };
    const filePath = join(this.configDir, '.mcp.json');
    await mkdir(this.configDir, { recursive: true });
    await writeFile(filePath, JSON.stringify(content, null, 2), 'utf-8');
  }

  /**
   * Fetches cloud MCP configurations using the injected fetcher.
   * The fetch is memoized: subsequent calls return the same result without
   * calling the fetcher again.
   * Returns an empty object when no fetcher was provided.
   */
  async fetchCloudMcpConfigsIfEligible(): Promise<Record<string, McpServerConfig>> {
    if (this.cloudFetcher === undefined) return {};
    if (this.cloudFetchResult !== null) return this.cloudFetchResult;
    this.cloudFetchResult = await this.cloudFetcher();
    return this.cloudFetchResult;
  }
}
