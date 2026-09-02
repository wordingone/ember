// deep-link.ts — deep-link URI validation and terminal detection.

// ---- ShellRunner interface ----

/** Abstracts shell execution for testability in terminal detection. */
export type ShellRunner = {
  run(): Promise<{ code: number; stdout: string; stderr: string }>;
  existsOnPath(binary: string): boolean;
};

// ---- Deep-link validation ----

type DeepLinkParams = {
  cwd?: string;
  repo?: string;
  prefill?: string;
  lastFetch?: string;
};

type DeepLinkSuccess = { ok: true; params: DeepLinkParams };
type DeepLinkFailure = { ok: false; reason: string };
type DeepLinkResult = DeepLinkSuccess | DeepLinkFailure;

const CONTROL_CHAR_RE = /[\x00-\x1F\x7F]/;
const REPO_PATTERN_RE = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;
const WINDOWS_ABS_RE = /^[A-Za-z]:[\\\/]/;
const MAX_QUERY_LENGTH = 5000;
const MAX_CWD_LENGTH = 4096;

/**
 * Validates an ember:// deep-link URI.
 * Returns `{ ok: true, params }` on success or `{ ok: false, reason }` on failure.
 *
 * Rules:
 * - Host must be "open"
 * - cwd must be an absolute path (Unix or Windows); ≤ 4096 chars; no control chars
 * - repo must match owner/name pattern
 * - prefill must contain no control characters
 * - Total query string must be ≤ 5000 characters
 */
export function validateDeepLink(uri: string): DeepLinkResult {
  let url: URL;
  try {
    url = new URL(uri);
  } catch {
    return { ok: false, reason: 'Invalid URI: unable to parse deep-link' };
  }

  if (url.host !== 'open') {
    return {
      ok: false,
      reason: `Invalid deep-link action: host must be "open", got "${url.host}"`,
    };
  }

  // Raw query string length (without leading '?')
  const rawQuery = url.search.length > 0 ? url.search.slice(1) : '';
  if (rawQuery.length > MAX_QUERY_LENGTH) {
    return {
      ok: false,
      reason: `Query string exceeds the ${MAX_QUERY_LENGTH} character limit`,
    };
  }

  const params = url.searchParams;

  // ---- cwd ----
  const cwd = params.get('cwd') ?? undefined;
  if (cwd !== undefined) {
    if (cwd.length > MAX_CWD_LENGTH) {
      return { ok: false, reason: `cwd exceeds the ${MAX_CWD_LENGTH} character limit` };
    }
    const isUnixAbsolute = cwd.startsWith('/');
    const isWindowsAbsolute = WINDOWS_ABS_RE.test(cwd);
    if (!isUnixAbsolute && !isWindowsAbsolute) {
      return { ok: false, reason: 'cwd must be an absolute path' };
    }
    if (CONTROL_CHAR_RE.test(cwd)) {
      return { ok: false, reason: 'cwd contains control characters' };
    }
  }

  // ---- repo ----
  const repo = params.get('repo') ?? undefined;
  if (repo !== undefined && !REPO_PATTERN_RE.test(repo)) {
    return { ok: false, reason: 'invalid repo format: must match owner/repo-name pattern' };
  }

  // ---- prefill ----
  const prefill = params.get('prefill') ?? undefined;
  if (prefill !== undefined && CONTROL_CHAR_RE.test(prefill)) {
    return { ok: false, reason: 'prefill contains control characters' };
  }

  const lastFetch = params.get('lastFetch') ?? undefined;

  return { ok: true, params: { cwd, repo, prefill, lastFetch } };
}

// ---- Terminal detection ----

const MAC_TERMINALS = ['iterm2', 'ghostty', 'kitty', 'warp', 'alacritty', 'terminal'];
const LINUX_TERMINALS = ['ghostty', 'kitty', 'alacritty', 'gnome-terminal', 'xterm', 'bash'];
const WIN_TERMINALS = ['wt.exe', 'pwsh', 'powershell', 'cmd'];

/**
 * Detects the best available terminal emulator on the current platform.
 *
 * - Windows: checks wt.exe → pwsh → powershell → cmd
 * - macOS: checks the standard macOS terminal priority list
 * - Linux/other: honours $TERMINAL env var, then checks the standard list
 *
 * Always returns a non-empty string; falls back to 'cmd' (Windows) or 'bash'
 * (Linux/macOS) if nothing is found.
 */
export function detectTerminal(runner: ShellRunner): string {
  const platform = process.platform;

  if (platform === 'win32') {
    for (const term of WIN_TERMINALS) {
      if (runner.existsOnPath(term)) return term;
    }
    return 'cmd';
  }

  if (platform === 'darwin') {
    for (const term of MAC_TERMINALS) {
      if (runner.existsOnPath(term)) return term;
    }
    return 'terminal';
  }

  // Linux / other: honour $TERMINAL first
  const envTerminal = process.env['TERMINAL'];
  if (envTerminal && runner.existsOnPath(envTerminal)) {
    return envTerminal;
  }

  for (const term of LINUX_TERMINALS) {
    if (runner.existsOnPath(term)) return term;
  }
  return 'bash';
}
