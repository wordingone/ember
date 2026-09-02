/**
 * test_gpu_lease_placeholder.ts — TDD tests for GPU lease placeholder renderer.
 *
 * Test cases:
 * 1. No lease file present → exit 0 with "no lease" output
 * 2. Valid lease with all fields → renders correct panel
 * 3. Valid lease without receipts_path → renders without receipts line
 * 4. Malformed JSON → fail-closed with error exit 1
 * 5. Missing required field → fail-closed with error exit 1
 * 6. Invalid timestamp → fail-closed with error exit 1
 */

import { describe, it, expect, beforeEach, afterEach } from 'bun:test';
import { mkdirSync, writeFileSync, rmSync, readFileSync } from 'fs';
import { execSync } from 'child_process';
import { join } from 'path';
import { tmpdir } from 'os';

// Test fixture helper
function createTestRepo(testName: string): string {
  const tmpRoot = join(tmpdir(), `gpu-lease-test-${testName}-${Date.now()}`);
  mkdirSync(tmpRoot, { recursive: true });
  mkdirSync(join(tmpRoot, 'state'), { recursive: true });
  return tmpRoot;
}

function cleanup(repoRoot: string) {
  try {
    rmSync(repoRoot, { recursive: true, force: true });
  } catch {
    // Ignore cleanup errors
  }
}

function runRenderer(repoRoot: string): { stdout: string; stderr: string; exitCode: number } {
  try {
    const stdout = execSync(`bun tools/gpu-lease-placeholder.ts "${repoRoot}"`, {
      cwd: process.cwd(),
      encoding: 'utf8',
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    return { stdout, stderr: '', exitCode: 0 };
  } catch (error) {
    const e = error as { status?: number; stdout?: Buffer; stderr?: Buffer };
    return {
      stdout: e.stdout?.toString() || '',
      stderr: e.stderr?.toString() || '',
      exitCode: e.status || 1,
    };
  }
}

describe('GPU Lease Placeholder', () => {
  describe('No lease file', () => {
    it('should output "no lease" and exit 0 when no lease file exists', () => {
      const repoRoot = createTestRepo('no-lease');

      try {
        const { stdout, exitCode } = runRenderer(repoRoot);
        expect(exitCode).toBe(0);
        expect(stdout.trim()).toBe('no lease');
      } finally {
        cleanup(repoRoot);
      }
    });
  });

  describe('Valid lease', () => {
    it('should render placeholder with all fields when lease is complete', () => {
      const repoRoot = createTestRepo('valid-complete');
      const lease = {
        purpose: 'training-run-W1b',
        holder: 'coordinator-1',
        since: '2026-07-07T00:00:00Z',
        expected_end: '2026-07-07T12:00:00Z',
        receipts_path: 'receipts/training-20260707T000000Z.json',
      };

      writeFileSync(join(repoRoot, 'state', 'gpu-lease.json'), JSON.stringify(lease));

      try {
        const { stdout, exitCode } = runRenderer(repoRoot);
        expect(exitCode).toBe(0);
        expect(stdout).toContain('EMBER — GPU LEASE ACTIVE');
        expect(stdout).toContain('coordinator-1');
        expect(stdout).toContain('training-run-W1b');
        expect(stdout).toContain('receipts/training-20260707T000000Z.json');
        expect(stdout).toContain('cockpit will return');
      } finally {
        cleanup(repoRoot);
      }
    });

    it('should render placeholder without receipts line when receipts_path is absent', () => {
      const repoRoot = createTestRepo('valid-no-receipts');
      const lease = {
        purpose: 'training-run-W1a',
        holder: 'coordinator-2',
        since: '2026-07-06T18:00:00Z',
        expected_end: '2026-07-07T06:00:00Z',
      };

      writeFileSync(join(repoRoot, 'state', 'gpu-lease.json'), JSON.stringify(lease));

      try {
        const { stdout, exitCode } = runRenderer(repoRoot);
        expect(exitCode).toBe(0);
        expect(stdout).toContain('EMBER — GPU LEASE ACTIVE');
        expect(stdout).toContain('coordinator-2');
        expect(stdout).toContain('training-run-W1a');
        // Should NOT contain the receipts section
        expect(stdout.indexOf('Receipts:') === -1).toBe(true);
      } finally {
        cleanup(repoRoot);
      }
    });

    it('should render in a well-formatted box', () => {
      const repoRoot = createTestRepo('valid-box-width');
      const lease = {
        purpose: 'short',
        holder: 'engine-1',
        since: '2026-07-07T00:00:00Z',
        expected_end: '2026-07-07T12:00:00Z',
      };

      writeFileSync(join(repoRoot, 'state', 'gpu-lease.json'), JSON.stringify(lease));

      try {
        const { stdout, exitCode } = runRenderer(repoRoot);
        expect(exitCode).toBe(0);
        const lines = stdout.trim().split('\n');
        // Should have multiple lines forming a box
        expect(lines.length).toBeGreaterThan(10);
        // First and last should be box corners
        expect(lines[0]).toContain('╔');
        expect(lines[lines.length - 1]).toContain('╚');
        // All content lines should start with ║
        for (const line of lines) {
          expect(line).toMatch(/^[╔╠╚╩║].*/);
        }
      } finally {
        cleanup(repoRoot);
      }
    });
  });

  describe('Malformed input', () => {
    it('should fail closed on malformed JSON and exit 1', () => {
      const repoRoot = createTestRepo('malformed-json');
      writeFileSync(join(repoRoot, 'state', 'gpu-lease.json'), '{ invalid json }');

      try {
        const { exitCode, stderr } = runRenderer(repoRoot);
        expect(exitCode).toBe(1);
        expect(stderr).toContain('Error loading GPU lease');
      } finally {
        cleanup(repoRoot);
      }
    });

    it('should fail closed when missing required field "purpose"', () => {
      const repoRoot = createTestRepo('missing-purpose');
      const lease = {
        holder: 'engine-1',
        since: '2026-07-07T00:00:00Z',
        expected_end: '2026-07-07T12:00:00Z',
      };

      writeFileSync(join(repoRoot, 'state', 'gpu-lease.json'), JSON.stringify(lease));

      try {
        const { exitCode, stderr } = runRenderer(repoRoot);
        expect(exitCode).toBe(1);
        expect(stderr).toContain('Error loading GPU lease');
      } finally {
        cleanup(repoRoot);
      }
    });

    it('should fail closed when missing required field "holder"', () => {
      const repoRoot = createTestRepo('missing-holder');
      const lease = {
        purpose: 'training-run',
        since: '2026-07-07T00:00:00Z',
        expected_end: '2026-07-07T12:00:00Z',
      };

      writeFileSync(join(repoRoot, 'state', 'gpu-lease.json'), JSON.stringify(lease));

      try {
        const { exitCode, stderr } = runRenderer(repoRoot);
        expect(exitCode).toBe(1);
        expect(stderr).toContain('Error');
      } finally {
        cleanup(repoRoot);
      }
    });

    it('should fail closed on invalid ISO 8601 timestamp', () => {
      const repoRoot = createTestRepo('invalid-timestamp');
      const lease = {
        purpose: 'training-run',
        holder: 'engine-1',
        since: 'not-a-date',
        expected_end: '2026-07-07T12:00:00Z',
      };

      writeFileSync(join(repoRoot, 'state', 'gpu-lease.json'), JSON.stringify(lease));

      try {
        const { exitCode, stderr } = runRenderer(repoRoot);
        expect(exitCode).toBe(1);
        expect(stderr).toContain('Error loading GPU lease');
      } finally {
        cleanup(repoRoot);
      }
    });

    it('should fail closed when lease is not a JSON object', () => {
      const repoRoot = createTestRepo('not-object');
      writeFileSync(join(repoRoot, 'state', 'gpu-lease.json'), '"just a string"');

      try {
        const { exitCode, stderr } = runRenderer(repoRoot);
        expect(exitCode).toBe(1);
        expect(stderr).toContain('Error loading GPU lease');
      } finally {
        cleanup(repoRoot);
      }
    });

    it('should fail closed when required field is not a string', () => {
      const repoRoot = createTestRepo('non-string-field');
      const lease = {
        purpose: 123, // Not a string!
        holder: 'engine-1',
        since: '2026-07-07T00:00:00Z',
        expected_end: '2026-07-07T12:00:00Z',
      };

      writeFileSync(join(repoRoot, 'state', 'gpu-lease.json'), JSON.stringify(lease));

      try {
        const { exitCode, stderr } = runRenderer(repoRoot);
        expect(exitCode).toBe(1);
        expect(stderr).toContain('Error loading GPU lease');
      } finally {
        cleanup(repoRoot);
      }
    });
  });

  describe('Timestamp formatting', () => {
    it('should format timestamps in human-readable UTC format', () => {
      const repoRoot = createTestRepo('timestamp-format');
      const lease = {
        purpose: 'test',
        holder: 'engine-3',
        since: '2026-07-07T03:45:30Z',
        expected_end: '2026-07-07T15:30:45Z',
      };

      writeFileSync(join(repoRoot, 'state', 'gpu-lease.json'), JSON.stringify(lease));

      try {
        const { stdout, exitCode } = runRenderer(repoRoot);
        expect(exitCode).toBe(0);
        expect(stdout).toContain('2026-07-07');
        expect(stdout).toContain('UTC');
      } finally {
        cleanup(repoRoot);
      }
    });
  });
});
