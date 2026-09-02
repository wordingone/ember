// shell-provider.ts
// Shell resolution, read-only command validation, and bash/powershell provider classes.
// L1 leaf: no intra-ember dependencies.

// ---- Output size limits ----

/** Default maximum output size per command (200 KB). */
export const BASH_MAX_OUTPUT_DEFAULT = 200_000;

/** Hard upper cap regardless of per-instance configuration (1 MB). */
export const BASH_MAX_OUTPUT_UPPER_LIMIT = 1_000_000;

// ---- Shell resolution ----

/**
 * Resolves the default shell to use for command execution.
 * Priority: EMBER_DEFAULT_SHELL env var → settings override → 'bash'.
 */
export function resolveDefaultShell(settingsOverride?: () => string): string {
  const envShell = process.env['EMBER_DEFAULT_SHELL'];
  if (envShell) return envShell;
  if (settingsOverride) return settingsOverride();
  return 'bash';
}

// ---- Read-only command validation ----

// Whitelisted git subcommands (no arguments required).
const GIT_READ_ONLY_SUBCMDS = new Set(['log', 'status', 'diff', 'show']);

/**
 * Returns true when `command` is on the read-only allowlist.
 * Allowlist: git {log,status,diff,show,stash list,branch -v} and
 * gh {pr list, pr view, issue list}.
 * Fails closed: any command not on the list returns false.
 */
export function readOnlyCommandValidation(command: string): boolean {
  const trimmed = command.trim();
  if (!trimmed) return false;

  const parts = trimmed.split(/\s+/);
  const tool = parts[0];

  if (tool === 'git') {
    const subcmd = parts[1]?.toLowerCase();
    if (!subcmd) return false;

    if (GIT_READ_ONLY_SUBCMDS.has(subcmd)) return true;

    // git stash list only (not pop, push, etc.)
    if (subcmd === 'stash') {
      const action = parts[2]?.toLowerCase();
      return action === 'list';
    }

    // git branch -v only
    if (subcmd === 'branch') {
      const flag = parts[2];
      return flag === '-v';
    }

    return false;
  }

  if (tool === 'gh') {
    const resource = parts[1]?.toLowerCase();
    const action = parts[2]?.toLowerCase();
    if (!resource || !action) return false;

    if (resource === 'pr') {
      return action === 'list' || action === 'view';
    }
    if (resource === 'issue') {
      return action === 'list';
    }
    return false;
  }

  return false;
}

// ---- PowerShell enablement ----

/**
 * Returns true when the PowerShell tool should be offered to the model.
 * Requires Windows. On Windows: always enabled for internal sessions,
 * otherwise only when the user explicitly opts in.
 */
export function isPowerShellToolEnabled(
  isWindows: boolean,
  isInternalSession: boolean,
  userOptIn: boolean,
): boolean {
  if (!isWindows) return false;
  return isInternalSession || userOptIn;
}

// ---- Truncation helper ----

function truncateAtLimit(output: string, limit: number): string {
  if (output.length <= limit) return output;
  const truncated = output.slice(0, limit);
  const omitted = output.length - limit;
  return `${truncated}\n[Output truncated: ${omitted} bytes omitted]`;
}

// ---- BashProvider ----

export interface BashProviderOptions {
  maxOutputBytes?: number;
  tmuxSocket?: string;
}

/** Wraps bash command execution with output truncation and env overrides. */
export class BashProvider {
  private readonly maxOutputBytes: number;
  private readonly tmuxSocket: string | undefined;

  constructor(options?: BashProviderOptions) {
    const requested = options?.maxOutputBytes ?? BASH_MAX_OUTPUT_DEFAULT;
    this.maxOutputBytes = Math.min(requested, BASH_MAX_OUTPUT_UPPER_LIMIT);
    this.tmuxSocket = options?.tmuxSocket;
  }

  /** Returns the shell command and arguments to run via bash -c. */
  buildExecCommand(command: string): { command: string; args: string[] } {
    return { command: 'bash', args: ['-c', command] };
  }

  /**
   * Truncates `output` to the configured limit (capped at UPPER_LIMIT).
   * Appends a truncation marker so callers know output was cut.
   */
  truncateOutput(output: string): string {
    return truncateAtLimit(output, this.maxOutputBytes);
  }

  /**
   * Returns environment variable overrides to inject into the child process.
   * Includes TMUX_SOCKET when a tmux socket path was configured.
   */
  getEnvironmentOverrides(): Record<string, string> {
    if (this.tmuxSocket) {
      return { TMUX_SOCKET: this.tmuxSocket };
    }
    return {};
  }
}

// ---- PowerShellProvider ----

export interface PowerShellProviderOptions {
  maxOutputBytes?: number;
}

/** Wraps PowerShell command execution with UTF-16LE base64 encoding and output truncation. */
export class PowerShellProvider {
  private readonly maxOutputBytes: number;

  constructor(options?: PowerShellProviderOptions) {
    const requested = options?.maxOutputBytes ?? BASH_MAX_OUTPUT_DEFAULT;
    this.maxOutputBytes = Math.min(requested, BASH_MAX_OUTPUT_UPPER_LIMIT);
  }

  /**
   * Encodes `command` as UTF-16LE base64 suitable for powershell -EncodedCommand.
   */
  static encodeCommand(command: string): string {
    return Buffer.from(command, 'utf16le').toString('base64');
  }

  /** Returns the powershell command and -EncodedCommand arguments. */
  buildExecCommand(command: string): { command: string; args: string[] } {
    const encoded = PowerShellProvider.encodeCommand(command);
    return { command: 'powershell', args: ['-EncodedCommand', encoded] };
  }

  /**
   * Truncates `output` to the configured limit (capped at UPPER_LIMIT).
   * Appends a truncation marker so callers know output was cut.
   */
  truncateOutput(output: string): string {
    return truncateAtLimit(output, this.maxOutputBytes);
  }
}
