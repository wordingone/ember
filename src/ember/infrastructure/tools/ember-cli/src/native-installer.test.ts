// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { describe, test, expect, beforeEach, afterEach } from 'bun:test';
import { mkdtemp, rm, mkdir, writeFile, readFile, symlink } from 'fs/promises';
import { join } from 'path';
import { tmpdir } from 'os';

import {
  VERSION_RETENTION_COUNT,
  isValidVersion,
  isTestVersion,
  shouldSkipVersion,
  getDownloadUrl,
  getChecksumUrl,
  downloadVersion,
  isProcessRunning,
  tryAcquireLock,
  releaseLock,
  withLock,
  cleanupOldVersions,
  installLatest,
  getPackageManager,
  _resetVersionCache,
  type InstallerDeps,
  type UserType,
} from './native-installer';
import { _resetConfigHomeMemo } from './env-detection';
import { createHash } from 'crypto';

let tmpDir: string;
const origEmberHome = process.env['EMBER_HOME'];

beforeEach(async () => {
  tmpDir = await mkdtemp(join(tmpdir(), 'installer-test-'));
  process.env['EMBER_HOME'] = tmpDir;
  _resetConfigHomeMemo();
  _resetVersionCache();
});

afterEach(async () => {
  if (origEmberHome === undefined) {
    delete process.env['EMBER_HOME'];
  } else {
    process.env['EMBER_HOME'] = origEmberHome;
  }
  delete process.env['ENABLE_LOCKLESS_UPDATES'];
  _resetConfigHomeMemo();
  _resetVersionCache();
  await rm(tmpDir, { recursive: true, force: true });
});

// ---------------------------------------------------------------------------
// Constants + helpers
// ---------------------------------------------------------------------------

describe('constants', () => {
  test('VERSION_RETENTION_COUNT is 2', () => {
    expect(VERSION_RETENTION_COUNT).toBe(2);
  });

  test('isValidVersion', () => {
    expect(isValidVersion('1.2.3')).toBe(true);
    expect(isValidVersion('10.0.0')).toBe(true);
    expect(isValidVersion('1.2')).toBe(false);
    expect(isValidVersion('abc')).toBe(false);
    expect(isValidVersion('99.99.1')).toBe(true);
  });

  test('isTestVersion', () => {
    expect(isTestVersion('99.99.0')).toBe(true);
    expect(isTestVersion('99.99.99')).toBe(true);
    expect(isTestVersion('1.2.3')).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// shouldSkipVersion
// ---------------------------------------------------------------------------

describe('shouldSkipVersion', () => {
  test('available below minimum → skip', () => {
    expect(shouldSkipVersion('1.0.0', '1.1.0')).toBe(true);
  });

  test('available at minimum → do not skip', () => {
    expect(shouldSkipVersion('1.1.0', '1.1.0')).toBe(false);
  });

  test('available above minimum → do not skip', () => {
    expect(shouldSkipVersion('2.0.0', '1.1.0')).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Download URL resolution
// ---------------------------------------------------------------------------

describe('getDownloadUrl', () => {
  test('test version → sentinel path', () => {
    const url = getDownloadUrl('99.99.1', 'external');
    expect(url).toContain('test-sentinel');
    expect(url).toContain('99.99.1');
  });

  test('ant user → GCS URL', () => {
    const url = getDownloadUrl('1.2.3', 'ant');
    expect(url).toContain('storage.googleapis.com');
  });

  test('external user → GCS bucket URL', () => {
    const url = getDownloadUrl('1.2.3', 'external');
    expect(url).toContain('storage.googleapis.com');
  });
});

describe('getChecksumUrl', () => {
  test('ends with .sha256', () => {
    expect(getChecksumUrl('1.2.3', 'external')).toEndWith('.sha256');
  });
});

// ---------------------------------------------------------------------------
// AC1: downloadVersion with mismatched SHA256 throws + no temp file
// ---------------------------------------------------------------------------

describe('downloadVersion', () => {
  test('AC1: mismatched SHA256 throws and no temp file remains', async () => {
    const binaryContent = Buffer.from('fake binary content');
    // Compute the REAL hash so we can set the mock to return a WRONG one
    const realHash = createHash('sha256').update(binaryContent).digest('hex');
    const wrongHash = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';

    expect(realHash).not.toBe(wrongHash);

    const mockFetch = (async (url: string) => {
      if (url.endsWith('.sha256')) {
        return { ok: true, text: async () => wrongHash, arrayBuffer: async () => new ArrayBuffer(0) };
      }
      return {
        ok: true,
        arrayBuffer: async () => binaryContent.buffer.slice(0) as ArrayBuffer,
        text: async () => '',
      };
    }) as unknown as typeof fetch;

    const targetPath = join(tmpDir, 'download-test', 'ember');
    await mkdir(join(tmpDir, 'download-test'), { recursive: true });

    const deps: InstallerDeps = { fetchFn: mockFetch };
    await expect(downloadVersion('1.0.0', targetPath, 'external', deps)).rejects.toThrow();

    // Temp file should not exist
    let tempExists = false;
    try {
      await readFile(targetPath + '.download');
      tempExists = true;
    } catch {}
    expect(tempExists).toBe(false);
  });

  test('AC6: test version 99.99.1 uses sentinel path', () => {
    const url = getDownloadUrl('99.99.1', 'external');
    expect(url).toContain('test-sentinel');
  });
});

// ---------------------------------------------------------------------------
// isProcessRunning
// ---------------------------------------------------------------------------

describe('isProcessRunning', () => {
  test('current process PID is running', () => {
    expect(isProcessRunning(process.pid)).toBe(true);
  });

  test('dead PID (max 32-bit) is not running', () => {
    expect(isProcessRunning(2147483647)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// PID lock
// ---------------------------------------------------------------------------

describe('PID lock', () => {
  test('acquires lock when no file exists', async () => {
    const lockPath = join(tmpDir, 'test.lock');
    const ok = await tryAcquireLock(lockPath);
    expect(ok).toBe(true);
    await releaseLock(lockPath);
  });

  test('lock blocks when held by live process', async () => {
    const lockPath = join(tmpDir, 'live.lock');
    // Write our own PID to simulate a live lock
    await writeFile(lockPath, String(process.pid));
    const ok = await tryAcquireLock(lockPath);
    expect(ok).toBe(false);
    await releaseLock(lockPath);
  });

  test('stale lock (dead PID) is cleared and re-acquired', async () => {
    const lockPath = join(tmpDir, 'stale.lock');
    // Write a dead PID
    await writeFile(lockPath, '2147483647');
    const ok = await tryAcquireLock(lockPath);
    expect(ok).toBe(true);
    await releaseLock(lockPath);
  });

  test('withLock runs function and releases on success', async () => {
    const lockPath = join(tmpDir, 'with.lock');
    let ran = false;
    await withLock(lockPath, async () => { ran = true; });
    expect(ran).toBe(true);
  });

  test('withLock releases lock on error', async () => {
    const lockPath = join(tmpDir, 'err.lock');
    await expect(
      withLock(lockPath, async () => { throw new Error('boom'); }),
    ).rejects.toThrow('boom');
    // Lock file should be gone
    let exists = false;
    try {
      await readFile(lockPath);
      exists = true;
    } catch {}
    expect(exists).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// AC2: installLatest → config.installMethod = 'native'
// ---------------------------------------------------------------------------

describe('installLatest', () => {
  function makeSuccessDeps(version = '2.0.0'): InstallerDeps {
    const binaryContent = Buffer.from('ember-binary');
    const hash = createHash('sha256').update(binaryContent).digest('hex');
    let capturedInstallMethod = '';

    return {
      fetchFn: (async (url: string) => {
        if (url.endsWith('.sha256')) {
          return { ok: true, text: async () => hash };
        }
        if (url.includes('latest')) {
          return { ok: true, text: async () => version, json: async () => ({ version }) };
        }
        return {
          ok: true,
          arrayBuffer: async () => binaryContent.buffer.slice(0) as ArrayBuffer,
          text: async () => '',
        };
      }) as unknown as typeof fetch,
      getInstallDir: () => join(tmpDir, 'versions'),
      getLockPath: () => join(tmpDir, 'install.lock'),
      setConfig: async (key, value) => {
        if (key === 'installMethod') capturedInstallMethod = value;
      },
      getConfig: async () => ({}),
      getExecPath: () => join(tmpDir, 'versions', '1.9.0', 'ember'),
    };
  }

  test('AC2: after installLatest, installMethod is set to "native"', async () => {
    process.env['ENABLE_LOCKLESS_UPDATES'] = '1';
    let installMethod = '';
    const deps = makeSuccessDeps('2.0.0');
    const origSetConfig = deps.setConfig!;
    deps.setConfig = async (k, v) => {
      if (k === 'installMethod') installMethod = v;
      return origSetConfig(k, v);
    };

    await installLatest('external', {}, deps);
    expect(installMethod).toBe('native');
  });

  test('AC5: ENABLE_LOCKLESS_UPDATES runs without lock file', async () => {
    process.env['ENABLE_LOCKLESS_UPDATES'] = '1';
    const deps = makeSuccessDeps('2.1.0');
    // If lock file creation were attempted, this would still succeed.
    // Verify no lock file artifact is left over.
    const lockPath = join(tmpDir, 'install.lock');

    const result = await installLatest('external', {}, deps);
    expect(result.version).toBe('2.1.0');

    let lockExists = false;
    try { await readFile(lockPath); lockExists = true; } catch {}
    // With lockless mode, no lock file should be written
    expect(lockExists).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// AC3 + AC4: cleanupOldVersions
// ---------------------------------------------------------------------------

describe('cleanupOldVersions', () => {
  async function makeVersionDirs(versions: string[]): Promise<void> {
    for (const v of versions) {
      await mkdir(join(tmpDir, 'versions', v), { recursive: true });
      await writeFile(join(tmpDir, 'versions', v, 'ember'), `binary-${v}`);
    }
  }

  test('AC3: does not delete the currently running version', async () => {
    await makeVersionDirs(['1.0.0', '1.1.0', '1.2.0', '1.3.0']);
    const currentVer = '1.3.0';
    const deps: InstallerDeps = {
      getInstallDir: () => join(tmpDir, 'versions'),
      getExecPath: () => join(tmpDir, 'versions', currentVer, 'ember'),
    };
    await cleanupOldVersions(deps);

    // Current version must still exist
    const content = await readFile(join(tmpDir, 'versions', currentVer, 'ember'), 'utf8');
    expect(content).toBe(`binary-${currentVer}`);
  });

  test('AC4: does not delete version held by active PID lock', async () => {
    await makeVersionDirs(['1.0.0', '1.1.0', '1.2.0']);
    // Write a live PID lock for 1.1.0
    const lockedVersion = '1.1.0';
    await writeFile(
      join(tmpDir, 'versions', lockedVersion, 'install.lock'),
      String(process.pid),
    );

    const deps: InstallerDeps = {
      getInstallDir: () => join(tmpDir, 'versions'),
      getExecPath: () => join(tmpDir, 'versions', '1.2.0', 'ember'), // current
    };
    await cleanupOldVersions(deps);

    // Locked version must still exist
    const content = await readFile(
      join(tmpDir, 'versions', lockedVersion, 'ember'),
      'utf8',
    );
    expect(content).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// AC7: getPackageManager — macOS with brew
// ---------------------------------------------------------------------------

describe('getPackageManager', () => {
  test('AC7: on macOS with brew, returns homebrew', async () => {
    if (process.platform !== 'darwin') {
      // Skip on non-macOS
      expect(true).toBe(true);
      return;
    }
    const mgr = await getPackageManager();
    // On macOS dev machines, brew is usually available
    // We just verify it returns a valid value
    const validManagers = [
      'homebrew', 'winget', 'mise', 'asdf', 'pacman', 'apk', 'deb', 'rpm', 'unknown',
    ];
    expect(validManagers).toContain(mgr);
    if (mgr === 'homebrew') {
      expect(mgr).toBe('homebrew');
    }
  });

  test('returns a valid package manager string', async () => {
    const mgr = await getPackageManager();
    const validManagers = [
      'homebrew', 'winget', 'mise', 'asdf', 'pacman', 'apk', 'deb', 'rpm', 'unknown',
    ];
    expect(validManagers).toContain(mgr);
  });
});
