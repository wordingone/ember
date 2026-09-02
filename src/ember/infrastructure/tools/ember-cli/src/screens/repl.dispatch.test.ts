// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// screens/repl.dispatch.test.ts — receipts for the LIVE renderMsgDispatch (the
// one wired into the mounted ReplScreen via core/frontend-shell.ts, distinct
// from the legacy duplicate in src/repl.ts which has no production importer).
//
// Focus: the "compaction" case. The live loop (query-engine) sets a one-shot
// post-compaction flag (markPostCompaction) when autocompact runs; the repl
// drain-loop consumes it (consumePostCompaction) into a {type:"compaction"}
// message that MUST mount CompactionProgressMessage. Before this case existed,
// such a message fell through to the bare-Text default and the user never saw
// that the conversation was compacted (dead-feature: flag set but never read,
// component built + unit-tested but never mounted).

import { describe, it, expect } from "bun:test";

import { renderMsgDispatch } from "../screens/repl.ts";
import {
  buildMessageLookups,
  CompactionProgressMessage,
  AssistantTextMessage,
  UserCommandMessage,
  type MessageLookups,
} from "../components/message-renderers.ts";
import type { SessionMessage } from "../components/app-shell.ts";

const emptyLookups: MessageLookups = buildMessageLookups([]);

describe("live renderMsgDispatch — compaction → CompactionProgressMessage", () => {
  it("mounts CompactionProgressMessage (not bare Text) for a compaction message", () => {
    const msg: SessionMessage = { id: "c1", type: "compaction", isComplete: true, elapsedSecs: 7 };
    const el = renderMsgDispatch(msg, emptyLookups, 80);
    expect(el.type).toBe(CompactionProgressMessage);
  });

  it("forwards isComplete=true and elapsedSecs to the component", () => {
    const msg: SessionMessage = { id: "c1", type: "compaction", isComplete: true, elapsedSecs: 7 };
    const props = renderMsgDispatch(msg, emptyLookups, 80).props as {
      isComplete: boolean; elapsedSecs?: number;
    };
    expect(props.isComplete).toBe(true);
    expect(props.elapsedSecs).toBe(7);
  });

  it("forwards isComplete=false (in-progress) and omits elapsedSecs when absent", () => {
    const msg: SessionMessage = { id: "c2", type: "compaction", isComplete: false };
    const props = renderMsgDispatch(msg, emptyLookups, 80).props as {
      isComplete: boolean; elapsedSecs?: number;
    };
    expect(props.isComplete).toBe(false);
    expect(props.elapsedSecs).toBeUndefined();
  });

  it("treats a non-boolean isComplete as not-complete (defensive)", () => {
    const msg: SessionMessage = { id: "c3", type: "compaction" }; // isComplete absent
    const props = renderMsgDispatch(msg, emptyLookups, 80).props as { isComplete: boolean };
    expect(props.isComplete).toBe(false);
  });

  it("does not echo a stray content field (compaction has no text body)", () => {
    const msg: SessionMessage = {
      id: "c4", type: "compaction", isComplete: true, content: "SHOULD_NOT_RENDER",
    };
    const props = renderMsgDispatch(msg, emptyLookups, 80).props as Record<string, unknown>;
    expect(props["content"]).toBeUndefined();
  });
});

// A slash command is echoed distinctly from chat: it must mount
// UserCommandMessage (the dimmed "/ cmd" line), not UserTextMessage (the "You"
// chat header). Before this case, slash commands rendered as ordinary user
// chat — UserCommandMessage was built + unit-tested but never mounted.
describe("live renderMsgDispatch — command → UserCommandMessage", () => {
  it("mounts UserCommandMessage for a command message", () => {
    const msg: SessionMessage = { id: "k1", type: "command", content: "help" };
    const el = renderMsgDispatch(msg, emptyLookups, 80);
    expect(el.type).toBe(UserCommandMessage);
  });

  it("forwards the (slash-stripped) command text to the component", () => {
    const msg: SessionMessage = { id: "k2", type: "command", content: "model load qwen" };
    const props = renderMsgDispatch(msg, emptyLookups, 80).props as { command: string };
    expect(props.command).toBe("model load qwen");
  });
});

// Smoke: prove this IS the live dispatch (routes other known types correctly),
// so the compaction case is verified sitting in the real production switch.
describe("live renderMsgDispatch — smoke for a known type", () => {
  it("routes assistant → AssistantTextMessage", () => {
    const msg: SessionMessage = { id: "a1", type: "assistant", content: "hi" };
    const el = renderMsgDispatch(msg, emptyLookups, 80);
    expect(el.type).toBe(AssistantTextMessage);
  });
});

// issue #197 (zombie "Retrying..." fix): an "error" message's retryCount used
// to default to 4 whenever the field was absent -- and applyResultEvent
// (below in this file's module) NEVER sets retryCount on the error messages
// it creates, so every terminal error unconditionally crossed
// SystemAPIErrorMessage's retryCount<=3 hidden-threshold and claimed an
// in-progress retry that had already ended (operator session #5: "all 4
// server slots idle, GPU 0%, yet Retrying... persists"). A terminal error
// message is by definition no longer retrying, so the only correct default
// is 0 -- live in-flight retries are shown separately via the status-bar
// effort callout (see ReplScreen's retryStatus state), which is wired to
// clear the moment the turn ends.
describe("live renderMsgDispatch — error retryCount default (issue #197)", () => {
  it("defaults retryCount to 0 (not 4) when the field is absent from the message", () => {
    const msg: SessionMessage = { id: "e1", type: "error", content: "boom" };
    const props = renderMsgDispatch(msg, emptyLookups, 80).props as { retryCount: number };
    expect(props.retryCount).toBe(0);
  });

  it("still honors an explicit retryCount when the message carries one", () => {
    const msg: SessionMessage = { id: "e2", type: "error", content: "boom", retryCount: 7 };
    const props = renderMsgDispatch(msg, emptyLookups, 80).props as { retryCount: number };
    expect(props.retryCount).toBe(7);
  });
});
