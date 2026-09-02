// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// cli-subcommands.ts — CLI subcommand implementations for the ember binary.

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface AgentDefinition {
  name: string;
  type: string;
  source: string;
  active: boolean;
}

interface AutoModeRules {
  allow?: string[];
  soft_deny?: string[];
  environment?: Record<string, unknown>;
}

interface DefaultAutoModeRules {
  allow: string[];
  soft_deny: string[];
  environment: Record<string, unknown>;
}

interface PackageManagerInfo {
  command: string;
  args: string[];
}

interface OAuthToken {
  access_token: string;
  token_type: string;
}

interface AuthStatusInfo {
  uuid: string;
  email: string;
  displayName: string;
  authMethod: string;
}

export interface SubcommandDeps {
  startBrowserOAuth?: (opts?: Record<string, unknown>) => Promise<OAuthToken>;
  installOAuthTokens?: (tokens: OAuthToken) => Promise<void>;
  exchangeRefreshToken?: (token: string, scopes: string[]) => Promise<OAuthToken>;
  getAuthStatus?: () => Promise<AuthStatusInfo | null>;
  detectInstallationType?: () => Promise<string>;
  detectPackageManager?: () => PackageManagerInfo;
  runNativeUpdate?: () => Promise<null>;
  loadAgents?: () => Promise<AgentDefinition[]>;
  getDefaultAutoModeRules?: () => DefaultAutoModeRules;
  getUserAutoModeRules?: () => AutoModeRules;
  critiquRules?: (rules: AutoModeRules) => Promise<string>;
  validatePluginManifest?: (path: string) => Promise<{ errors: string[]; warnings: string[] }>;
  runNativeInstaller?: (target?: string, force?: boolean) => Promise<void>;
}

// ---------------------------------------------------------------------------
// auth login
// ---------------------------------------------------------------------------

export async function authLogin(
  opts: { console?: boolean; cloudauth?: boolean },
  deps: SubcommandDeps = {},
): Promise<never> {
  if (opts.console && opts.cloudauth) {
    process.stderr.write('Error: --console and --cloudauth are mutually exclusive.\n');
    return process.exit(1);
  }

  // Fast path: exchange refresh token from env
  const refreshToken = process.env['EMBER_OAUTH_REFRESH_TOKEN'];
  if (refreshToken) {
    const scopesEnv = process.env['EMBER_OAUTH_SCOPES'] ?? '';
    const scopes = scopesEnv.split(',').map((s) => s.trim()).filter(Boolean);
    const tokens = await (deps.exchangeRefreshToken ?? (async () => { throw new Error('exchangeRefreshToken not provided'); }))(refreshToken, scopes);
    await (deps.installOAuthTokens ?? (async () => {}))(tokens);
    return process.exit(0);
  }

  // Browser OAuth flow
  const tokens = await (deps.startBrowserOAuth ?? (async () => { throw new Error('startBrowserOAuth not provided'); }))();
  await (deps.installOAuthTokens ?? (async () => {}))(tokens);
  return process.exit(0);
}

// ---------------------------------------------------------------------------
// auth status
// ---------------------------------------------------------------------------

export async function authStatus(
  opts: { json?: boolean },
  deps: SubcommandDeps = {},
): Promise<never> {
  if (opts.json) {
    const status = await (deps.getAuthStatus ?? (async () => null))();
    if (status === null) {
      process.stdout.write(JSON.stringify({ authMethod: 'none' }) + '\n');
    } else {
      process.stdout.write(JSON.stringify(status) + '\n');
    }
    return process.exit(0);
  }

  const status = await (deps.getAuthStatus ?? (async () => null))();
  if (status === null) {
    process.stdout.write('Not logged in.\n');
  } else {
    process.stdout.write(`Logged in as ${status.email} (${status.authMethod})\n`);
  }
  return process.exit(0);
}

// ---------------------------------------------------------------------------
// update
// ---------------------------------------------------------------------------

export async function update(deps: SubcommandDeps = {}): Promise<never> {
  const installType = await (deps.detectInstallationType ?? (async () => 'unknown'))();

  if (installType === 'package-manager') {
    const pm = (deps.detectPackageManager ?? (() => ({ command: 'npm', args: ['install', '-g', 'ember-cli'] })))();
    const cmd = [pm.command, ...pm.args].join(' ');
    process.stdout.write(`Run the following command to update ember:\n\n  ${cmd}\n`);
    return process.exit(0);
  }

  // For other install types, attempt native update
  try {
    await (deps.runNativeUpdate ?? (async () => null))();
    process.stdout.write('Ember updated successfully.\n');
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    process.stderr.write(`Update failed: ${msg}\n`);
    return process.exit(1);
  }
  return process.exit(0);
}

// ---------------------------------------------------------------------------
// agents
// ---------------------------------------------------------------------------

export async function agents(deps: SubcommandDeps = {}): Promise<never> {
  const all = await (deps.loadAgents ?? (async () => []))();
  const active = all.filter((a) => a.active);

  if (active.length === 0) {
    process.stdout.write('No agents found.\n');
    return process.exit(0);
  }

  // Group by source
  const bySource = new Map<string, AgentDefinition[]>();
  for (const agent of active) {
    const group = bySource.get(agent.source) ?? [];
    group.push(agent);
    bySource.set(agent.source, group);
  }

  for (const [source, group] of bySource) {
    process.stdout.write(`[${source}]\n`);
    for (const a of group) {
      process.stdout.write(`  ${a.name} (${a.type})\n`);
    }
  }
  process.stdout.write(`Total: ${active.length}\n`);
  return process.exit(0);
}

// ---------------------------------------------------------------------------
// auto-mode defaults
// ---------------------------------------------------------------------------

export async function autoModeDefaults(deps: SubcommandDeps = {}): Promise<never> {
  const defaults = (deps.getDefaultAutoModeRules ?? (() => ({ allow: [], soft_deny: [], environment: {} })))();
  process.stdout.write(JSON.stringify(defaults) + '\n');
  return process.exit(0);
}

// ---------------------------------------------------------------------------
// auto-mode config
// ---------------------------------------------------------------------------

export async function autoModeConfig(deps: SubcommandDeps = {}): Promise<never> {
  const defaults = (deps.getDefaultAutoModeRules ?? (() => ({ allow: [], soft_deny: [], environment: {} })))();
  const user = (deps.getUserAutoModeRules ?? (() => ({})))();
  // REPLACE semantics: user keys replace defaults entirely
  const result = { ...defaults, ...user };
  process.stdout.write(JSON.stringify(result) + '\n');
  return process.exit(0);
}

// ---------------------------------------------------------------------------
// auto-mode critique
// ---------------------------------------------------------------------------

export async function autoModeCritique(
  _opts: Record<string, unknown> = {},
  deps: SubcommandDeps = {},
): Promise<never> {
  const user = (deps.getUserAutoModeRules ?? (() => ({})))();
  const hasCustomRules = Object.keys(user).length > 0;

  if (!hasCustomRules) {
    process.stdout.write('No custom rules configured. Using built-in defaults.\n');
    return process.exit(0);
  }

  const critique = await (deps.critiquRules ?? (async () => ''))(user);
  process.stdout.write(critique + '\n');
  return process.exit(0);
}

// ---------------------------------------------------------------------------
// plugin validate
// ---------------------------------------------------------------------------

export async function pluginValidate(
  manifestPath: string,
  _opts: Record<string, unknown> = {},
  deps: SubcommandDeps = {},
): Promise<never> {
  const { errors, warnings } = await (deps.validatePluginManifest ?? (async () => ({ errors: [], warnings: [] })))(manifestPath);

  for (const w of warnings) {
    process.stderr.write(`Warning: ${w}\n`);
  }

  if (errors.length > 0) {
    for (const e of errors) {
      process.stderr.write(`Error: ${e}\n`);
    }
    return process.exit(1);
  }

  process.stdout.write('Plugin manifest is valid.\n');
  return process.exit(0);
}

// ---------------------------------------------------------------------------
// install
// ---------------------------------------------------------------------------

export async function install(
  target?: string,
  opts: { force?: boolean } = {},
  deps: SubcommandDeps = {},
): Promise<never> {
  try {
    await (deps.runNativeInstaller ?? (async () => {}))(target, opts.force ?? false);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    process.stderr.write(`Install failed: ${msg}\n`);
    return process.exit(1);
  }
  // Success path is intentionally OUTSIDE the try: process.exit unwinds via a
  // thrown signal under test harnesses, which the catch above must not capture.
  process.stdout.write('Ember installed successfully.\n');
  return process.exit(0);
}

// ---------------------------------------------------------------------------
// Background session stubs (not supported)
// ---------------------------------------------------------------------------

export async function ps(): Promise<never> {
  process.stderr.write('ps: background sessions are not supported in this version.\n');
  return process.exit(1);
}

export async function logsSession(_sessionId: string): Promise<never> {
  process.stderr.write('logs: background sessions are not supported in this version.\n');
  return process.exit(1);
}

export async function attachSession(_sessionId: string): Promise<never> {
  process.stderr.write('attach: background sessions are not supported in this version.\n');
  return process.exit(1);
}

export async function killSession(_sessionId: string): Promise<never> {
  process.stderr.write('kill: background sessions are not supported in this version.\n');
  return process.exit(1);
}

export async function antLog(_id: string): Promise<never> {
  process.stderr.write('ant-log: not supported in this version.\n');
  return process.exit(1);
}
