// Integration test: verify R0 "SEE ITSELF" end-to-end
// Write a real registry event log (the exact JSONL shape scripts/ember_c11_reearn_runner.py
// writes), fetch the merged feed, verify it renders correctly.

import { describe, it, expect, beforeEach, afterEach } from 'bun:test';
import { fetchActivityFeed } from '../services/activity-feed.ts';
import { startReceiptWatch, resetReceiptWatchForTests } from '../services/receipt-watch.ts';
import { mkdir, writeFile, appendFile, rm } from 'fs/promises';
import { join } from 'path';
import { tmpdir } from 'os';

async function appendEvent(path: string, obj: Record<string, unknown>): Promise<void> {
  await appendFile(path, JSON.stringify(obj) + '\n', 'utf-8');
}

describe('R0 SEE ITSELF — end-to-end integration', () => {
  let tmpRegistry: string;
  let tmpDir: string;

  beforeEach(async () => {
    tmpDir = join(tmpdir(), `ember-r0-test-${Date.now()}`);
    tmpRegistry = join(tmpDir, 'state', 'runs', 'active-runs.jsonl');
    await mkdir(join(tmpDir, 'state', 'runs'), { recursive: true });
    resetReceiptWatchForTests();
  });

  afterEach(async () => {
    try {
      await rm(tmpDir, { recursive: true, force: true });
    } catch {
      // tolerate cleanup failure
    }
  });

  it('writes a real run event sequence and fetches it via the merged feed', async () => {
    const statePath = join(tmpDir, 'run-state.json');
    await writeFile(statePath, '{}', 'utf-8'); // create the file so provenance resolves (key R0 invariant)

    // Simulate what the real launcher (scripts/ember_c11_reearn_runner.py) appends: "started"
    // then "pid_assigned" -- using THIS test process's own pid, a genuinely live process, so
    // status derivation exercises a real OS liveness probe rather than a mocked one.
    await appendEvent(tmpRegistry, {
      ts: new Date().toISOString(), event: 'started', run_id: 'r0-integration-1', milestone: '1-hour',
      state_path: statePath,
    });
    await appendEvent(tmpRegistry, {
      ts: new Date().toISOString(), event: 'pid_assigned', run_id: 'r0-integration-1', milestone: '1-hour',
      pid: process.pid,
    });

    const summary = await fetchActivityFeed({ runsRegistry: { registryPaths: [tmpRegistry] } });

    // Verify the run appears in the feed
    expect(summary.recentCount).toBe(1);
    expect(summary.rows.length).toBe(1);
    expect(summary.liveCount).toBe(1);

    // Verify the key R0 invariant: provenance path resolves (never silently missing)
    const row = summary.rows[0]!;
    expect(row.kind).toBe('run');
    expect(row.provenanceResolves).toBe(true); // This is the hard requirement
    expect(row.label).toMatch(new RegExp(`running.*1-hour.*pid ${process.pid}`));
  });

  it('reports honest empty state when no runs exist', async () => {
    // Empty registry — no runs written
    startReceiptWatch({ dirs: [join(tmpDir, 'receipts')] });
    const summary = await fetchActivityFeed({ runsRegistry: { registryPaths: [tmpRegistry] } });

    expect(summary.liveCount).toBe(0);
    expect(summary.recentCount).toBe(0);
    expect(summary.rows.length).toBe(0);
  });

  it('marks unresolved provenance explicitly (never silently)', async () => {
    // A "started" event whose state_path points nowhere real -- e.g. a state-dir that was
    // since cleaned up. No pid_assigned event yet, so this also exercises the "running, pid
    // not yet known" branch of status derivation.
    const nonexistentStatePath = join(tmpDir, 'this-path-does-not-exist.json');
    await appendEvent(tmpRegistry, {
      ts: new Date().toISOString(), event: 'started', run_id: 'r0-integration-2', milestone: '1-hour',
      state_path: nonexistentStatePath,
    });

    const summary = await fetchActivityFeed({ runsRegistry: { registryPaths: [tmpRegistry] } });

    expect(summary.rows.length).toBe(1);
    const row = summary.rows[0]!;
    // The key R0 invariant: unresolved provenance is marked, never silently omitted
    expect(row.provenanceResolves).toBe(false);
    expect(row.provenancePath).toBe(nonexistentStatePath);
    // The render layer (activity-pane.ts) will add "[unresolved]" text when rendering
  });
});
