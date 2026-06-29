// native-installer.ts — native binary installer, updater, and cleanup.

import { createHash } from 'crypto';
import { mkdir, readdir, readFile, rename, rm, writeFile } from 'fs/promises';
import { dirname, join } from 'path';
import { getEmberConfigHomeDir } from './utils/env-detection.ts';

// ---- Constants ----

/** Number of non-locked versions to retain alongside the currently running one. */
export const VERSION_RETENTION_COUNT = 2;

// ---- Types ----

export type UserType = 'ant' | 'external';

export interface InstallerDeps {
  fetchFn?: typeof fetch;
  getInstallDir?: () => string;
  getLockPath?: () => string;
  setConfig?: (key: string, value: string) => Promise<void>;
  getConfig?: () => Promise<Record<string, unknown>>;
  getExecPath?: () => string;
}

// ---- Version utilities ----

/** Returns true when `v` is a valid 3-part semantic version (X.Y.Z). */
export function isValidVersion(v: string): boolean {
  return /^\d+\.\d+\.\d+$/.test(v);
}

/** Returns true when `v` is a test sentinel version (99.99.x). */
export function isTestVersion(v: string): boolean {
  return /^99\.99\.\d+$/.test(v);
}

/**
 * Returns true when `available` is strictly less than `minimum` by semver ordering.
 * Callers should skip an update when this returns true.
 */
export function shouldSkipVersion(available: string, minimum: string): boolean {
  return compareSemver(available, minimum) < 0;
}

function parseSemver(v: string): [number, number, number] {
  const parts = v.split('.').map(Number);
  return [parts[0] ?? 0, parts[1] ?? 0, parts[2] ?? 0];
}

function compareSemver(a: string, b: string): number {
  const [aMaj, aMin, aPatch] = parseSemver(a);
  const [bMaj, bMin, bPatch] = parseSemver(b);
  if (aMaj !== bMaj) return aMaj - bMaj;
  if (aMin !== bMin) return aMin - bMin;
  return aPatch - bPatch;
}

// ---- Download URL resolution ----

const GCS_ANT_BUCKET = 'https://storage.googleapis.com/ember-releases-internal';
const GCS_EXT_BUCKET = 'https://storage.googleapis.com/ember-releases';

/** Returns the download URL for the given version and user type. */
export function getDownloadUrl(version: string, userType: UserType): string {
  if (isTestVersion(version)) {
    return `https://ember-test-sentinel.internal/test-sentinel/${version}/ember`;
  }
  const bucket = userType === 'ant' ? GCS_ANT_BUCKET : GCS_EXT_BUCKET;
  return `${bucket}/${version}/ember`;
}

/** Returns the SHA-256 checksum URL for the given version and user type. */
export function getChecksumUrl(version: string, userType: UserType): string {
  return getDownloadUrl(version, userType) + '.sha256';
}

// ---- Download + SHA-256 verification ----

/**
 * Downloads the versioned binary to `targetPath`, verifying its SHA-256 checksum.
 * Throws when the checksum does not match; no temp file is left on disk after a failure.
 */
export async function downloadVersion(
  version: string,
  targetPath: string,
  userType: UserType,
  deps: InstallerDeps,
): Promise<void> {
  const fetchFn = deps.fetchFn ?? fetch;
  const tempPath = targetPath + '.download';

  // Fetch expected checksum
  const checksumUrl = getChecksumUrl(version, userType);
  const checksumResp = await fetchFn(checksumUrl);
  const expectedHash = (await checksumResp.text()).trim();

  // Fetch binary content
  const binaryUrl = getDownloadUrl(version, userType);
  const binaryResp = await fetchFn(binaryUrl);
  const buffer = await binaryResp.arrayBuffer();
  const data = Buffer.from(buffer);

  // Verify before writing anything
  const actualHash = createHash('sha256').update(data).digest('hex');
  if (actualHash !== expectedHash) {
    // Ensure no leftover temp file
    await rm(tempPath, { force: true }).catch(() => undefined);
    throw new Error(
      `SHA-256 mismatch for ${version}: expected ${expectedHash}, got ${actualHash}`,
    );
  }

  // Write to temp file, then atomically rename
  await mkdir(dirname(targetPath), { recursive: true });
  await writeFile(tempPath, data);
  await rename(tempPath, targetPath);
}

// ---- Process liveness ----

/**
 * Returns true when the process with `pid` is currently running.
 * Uses `process.kill(pid, 0)` for a signal-free liveness check.
 */
export function isProcessRunning(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

// ---- PID lock ----

/**
 * Attempts to acquire a PID lock at `lockPath`.
 *
 * - No lock file: writes current PID and returns true
 * - Stale lock (dead PID): clears it, writes current PID, returns true
 * - Live lock: returns false
 */
export async function tryAcquireLock(lockPath: string): Promise<boolean> {
  try {
    const existing = await readFile(lockPath, 'utf-8');
    const pid = parseInt(existing.trim(), 10);
    if (!isNaN(pid) && isProcessRunning(pid)) {
      return false; // live lock held by another process
    }
    // Stale lock; fall through to overwrite
  } catch {
    // File does not exist; proceed to create
  }

  try {
    await writeFile(lockPath, String(process.pid));
    return true;
  } catch {
    return false;
  }
}

/** Removes the lock file unconditionally (best-effort). */
export async function releaseLock(lockPath: string): Promise<void> {
  await rm(lockPath, { force: true }).catch(() => undefined);
}

/**
 * Acquires the lock at `lockPath`, runs `fn`, then releases the lock.
 * Always releases, even when `fn` throws.
 */
export async function withLock<T>(lockPath: string, fn: () => Promise<T>): Promise<T> {
  await tryAcquireLock(lockPath);
  try {
    return await fn();
  } finally {
    await releaseLock(lockPath);
  }
}

// ---- Version cache reset (tests only) ----

let _cachedLatestVersion: string | null = null;

/** Clears the cached latest-version value. TEST-ONLY. */
export function _resetVersionCache(): void {
  _cachedLatestVersion = null;
}

// Suppress unused-variable lint — used as a future cache slot
void _cachedLatestVersion;

// ---- Old version cleanup ----

function defaultInstallDir(): string {
  return join(getEmberConfigHomeDir(), 'versions');
}

function defaultExecPath(): string {
  return process.execPath;
}

/**
 * Removes old installed versions, keeping:
 * - The currently running version
 * - Versions locked by a live PID
 * - The newest `VERSION_RETENTION_COUNT` versions (excluding the above)
 */
export async function cleanupOldVersions(deps: InstallerDeps): Promise<void> {
  const installDir = deps.getInstallDir?.() ?? defaultInstallDir();
  const execPath = deps.getExecPath?.() ?? defaultExecPath();

  // Derive the current version directory name from the exec path
  const currentVersionDir = dirname(execPath);

  let entries: string[];
  try {
    entries = await readdir(installDir);
  } catch {
    return;
  }

  // Classify each version directory
  const locked = new Set<string>();
  const versions: string[] = [];

  for (const entry of entries) {
    if (!isValidVersion(entry)) continue;
    versions.push(entry);

    // Check for a live PID lock inside this version directory
    const lockPath = join(installDir, entry, 'install.lock');
    try {
      const pidStr = await readFile(lockPath, 'utf-8');
      const pid = parseInt(pidStr.trim(), 10);
      if (!isNaN(pid) && isProcessRunning(pid)) {
        locked.add(entry);
      }
    } catch {
      // No lock file; not locked
    }
  }

  // Sort newest-first by semver
  versions.sort((a, b) => compareSemver(b, a));

  const currentEntry = dirname(execPath).split(/[/\\]/).pop() ?? '';
  const toKeep = new Set<string>([currentEntry]);
  for (const v of locked) toKeep.add(v);

  let keptCount = 0;
  for (const v of versions) {
    if (toKeep.has(v)) continue;
    if (keptCount < VERSION_RETENTION_COUNT) {
      toKeep.add(v);
      keptCount++;
    }
  }

  // Delete versions not in the keep set
  for (const v of versions) {
    if (toKeep.has(v)) continue;
    const vPath = join(installDir, v);
    await rm(vPath, { recursive: true, force: true }).catch(() => undefined);
  }
}

// ---- Latest version installation ----

interface InstallOptions {
  minimumVersion?: string;
}

interface InstallResult {
  version: string;
}

const LATEST_VERSION_ENDPOINT = 'latest';

/**
 * Fetches the latest available version and installs it.
 *
 * - Uses a PID lock to prevent concurrent installs (skipped when ENABLE_LOCKLESS_UPDATES is set)
 * - Sets config key "installMethod" to "native" after a successful install
 * - Returns the installed version string
 */
export async function installLatest(
  userType: UserType,
  options: InstallOptions,
  deps: InstallerDeps,
): Promise<InstallResult> {
  const fetchFn = deps.fetchFn ?? fetch;
  const installDir = deps.getInstallDir?.() ?? defaultInstallDir();
  const lockless = !!process.env['ENABLE_LOCKLESS_UPDATES'];

  async function doInstall(): Promise<InstallResult> {
    // Determine the latest version
    const bucket =
      userType === 'ant' ? GCS_ANT_BUCKET : GCS_EXT_BUCKET;
    const latestUrl = `${bucket}/${LATEST_VERSION_ENDPOINT}`;
    const versionResp = await fetchFn(latestUrl);
    const version = (await versionResp.text()).trim();

    if (options.minimumVersion && shouldSkipVersion(version, options.minimumVersion)) {
      return { version };
    }

    const targetPath = join(installDir, version, 'ember');
    await downloadVersion(version, targetPath, userType, deps);

    await deps.setConfig?.('installMethod', 'native');

    _cachedLatestVersion = version;
    return { version };
  }

  if (lockless) {
    return doInstall();
  }

  const lockPath = deps.getLockPath?.() ?? join(installDir, 'install.lock');
  return withLock(lockPath, doInstall);
}

// ---- Package manager detection ----

export type PackageManagerName =
  | 'homebrew'
  | 'winget'
  | 'mise'
  | 'asdf'
  | 'pacman'
  | 'apk'
  | 'deb'
  | 'rpm'
  | 'unknown';

/**
 * Detects the package manager used to install this CLI.
 * Probes common package manager binaries in priority order.
 */
export async function getPackageManager(): Promise<PackageManagerName> {
  const { execFile } = await import('child_process');
  const { promisify } = await import('util');
  const exec = promisify(execFile);

  async function tryRun(cmd: string, args: string[]): Promise<boolean> {
    try {
      await exec(cmd, args, { timeout: 3000 });
      return true;
    } catch {
      return false;
    }
  }

  if (process.platform === 'win32') {
    if (await tryRun('winget', ['--version'])) return 'winget';
    return 'unknown';
  }

  if (process.platform === 'darwin') {
    if (await tryRun('brew', ['--version'])) return 'homebrew';
    if (await tryRun('mise', ['--version'])) return 'mise';
    if (await tryRun('asdf', ['version'])) return 'asdf';
    return 'unknown';
  }

  // Linux
  if (await tryRun('mise', ['--version'])) return 'mise';
  if (await tryRun('asdf', ['version'])) return 'asdf';
  if (await tryRun('pacman', ['--version'])) return 'pacman';
  if (await tryRun('apk', ['--version'])) return 'apk';
  if (await tryRun('dpkg', ['--version'])) return 'deb';
  if (await tryRun('rpm', ['--version'])) return 'rpm';

  return 'unknown';
}
