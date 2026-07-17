// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { describe, expect, test } from "bun:test";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import {
  AGENT_EVENT_KINDS,
  formatAgentEventLine,
  getAgentEventFeedState,
  startAgentEventWatch,
  parseAgentJournal,
  readAgentJournal,
  selectAgentEventRun,
  type AgentJournalEvent,
} from "./agent-event-feed.ts";

const event = (runId: string, seq: number, kind: AgentJournalEvent["kind"], summary: string) => JSON.stringify({
  schema_version: "ember-agent-event-v1",
  ts: `2026-07-17T17:30:${String(seq).padStart(2, "0")}.000Z`,
  run_id: runId,
  seq,
  kind,
  payload: { summary },
});

describe("journal-bound agent event feed", () => {
  test("accepts only the closed schema and preserves ordered real event kinds", () => {
    expect(AGENT_EVENT_KINDS).toEqual(["choose", "act", "tool", "verify", "reply", "reasoning-status"]);
    const events = parseAgentJournal([
      event("run-a", 1, "choose", "inspect the failing test"),
      event("run-a", 2, "act", "open the source"),
      event("run-a", 3, "tool", "read_file"),
      event("run-a", 4, "verify", "focused tests green"),
      event("run-a", 5, "reply", "handoff ready"),
      event("run-a", 6, "reasoning-status", "checking evidence"),
    ].join("\n"));
    expect(events.map(({ seq, kind }) => ({ seq, kind }))).toEqual([
      { seq: 1, kind: "choose" },
      { seq: 2, kind: "act" },
      { seq: 3, kind: "tool" },
      { seq: 4, kind: "verify" },
      { seq: 5, kind: "reply" },
      { seq: 6, kind: "reasoning-status" },
    ]);
    expect(formatAgentEventLine(events[2]!)).toBe("[tool] run-a#3 read_file");
  });

  test("rejects stale/foreign/malformed rows and never invents an event", () => {
    const rows = [
      event("old-run", 1, "choose", "old"),
      event("new-run", 1, "choose", "new"),
      event("new-run", 2, "tool", "read_file"),
      JSON.stringify({ schema_version: "ember-agent-event-v0", ts: "2026-07-17T17:30:04.000Z", run_id: "new-run", seq: 3, kind: "act", payload: { summary: "wrong schema" } }),
      JSON.stringify({ schema_version: "ember-agent-event-v1", ts: "2026-07-17T17:30:05.000Z", run_id: "new-run", seq: 4, kind: "synthetic", payload: { summary: "fake" } }),
      "not-json",
    ];
    const events = parseAgentJournal(rows.join("\n"));
    expect(events.map((item) => item.payload.summary)).toEqual(["old", "new", "read_file"]);
    expect(selectAgentEventRun(events).map((item) => item.runId)).toEqual(["new-run", "new-run"]);
    expect(selectAgentEventRun(events).map((item) => item.seq)).toEqual([1, 2]);
  });

  test("watch state proves ONLINE for a journal and OFFLINE after disappearance", async () => {
    const root = await mkdtemp(join(tmpdir(), "ember-agent-watch-"));
    const path = join(root, "agent-events.jsonl");
    await writeFile(path, event("run-a", 1, "reply", "done") + "\n", "utf8");
    const handle = startAgentEventWatch({ journalPath: path, pollIntervalMs: 10 });
    try {
      await Bun.sleep(40);
      expect(getAgentEventFeedState().channelStatus).toBe("ONLINE");
      expect(getAgentEventFeedState().events).toHaveLength(1);
      await rm(path, { force: true });
      await Bun.sleep(40);
      expect(getAgentEventFeedState().channelStatus).toBe("OFFLINE");
      expect(getAgentEventFeedState().events).toHaveLength(1);
    } finally {
      handle.stop();
      await rm(root, { recursive: true, force: true });
    }
  });
  test("reads a real journal path and fails closed on missing custody", async () => {
    const root = await mkdtemp(join(tmpdir(), "ember-agent-journal-"));
    const path = join(root, "agent-events.jsonl");
    try {
      await writeFile(path, event("run-a", 1, "reply", "done") + "\n", "utf8");
      expect((await readAgentJournal(path)).map((item) => item.kind)).toEqual(["reply"]);
      expect(await readAgentJournal(join(root, "missing.jsonl"))).toEqual([]);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
});
