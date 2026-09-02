// core/query-engine.error-event.test.ts — issue #49: a transport-level generate failure
// (callModel throws, e.g. ECONNREFUSED against an unreachable model server) must surface real
// error information on the yielded result event, not be silently swallowed.
//
// Before this fix, query()'s catch block used a bare `catch {}` (no bound error) and yielded
// `{ type: "result", subtype: "error", durationMs }` with nothing describing what failed --
// the caller (screens/repl.ts) had no error text to show the user, which is the root half of
// issue #49 (the other half is prompt-suggestion.ts's console.debug leak; see its own test file).

import { describe, it, expect } from "bun:test";
import { QueryEngine } from "./query-engine.ts";
import type { LoopDepsOverrides } from "../query/query-loop-support.ts";
import type { ResultEvent } from "./query-engine.ts";

describe("query loop — transport failure surfaces real error info (issue #49)", () => {
  it("a thrown callModel error yields a result/error event carrying that error's message", async () => {
    const testDeps: LoopDepsOverrides = {
      callModel: async () => {
        throw new Error("fetch failed: connect ECONNREFUSED 127.0.0.1:1");
      },
      generateUuid: () => "u",
    };
    const engine = new QueryEngine(
      { getAppState: () => ({}), setAppState: () => {} },
      testDeps,
    );

    let resultEvent: ResultEvent | null = null;
    for await (const ev of engine.submitMessage("hello")) {
      if (ev.type === "result") resultEvent = ev;
    }

    expect(resultEvent).not.toBeNull();
    expect(resultEvent!.subtype).toBe("error");
    // The real failure text must ride along on the event -- not discarded.
    const msg = (resultEvent as unknown as { errorMessage?: string }).errorMessage;
    expect(typeof msg).toBe("string");
    expect(msg).toContain("ECONNREFUSED");
  });

  it("a non-Error throw still yields a usable string on errorMessage (never undefined)", async () => {
    const testDeps: LoopDepsOverrides = {
      callModel: async () => {
        // eslint-disable-next-line @typescript-eslint/no-throw-literal
        throw "raw string rejection";
      },
      generateUuid: () => "u",
    };
    const engine = new QueryEngine(
      { getAppState: () => ({}), setAppState: () => {} },
      testDeps,
    );

    let resultEvent: ResultEvent | null = null;
    for await (const ev of engine.submitMessage("hello")) {
      if (ev.type === "result") resultEvent = ev;
    }

    expect(resultEvent).not.toBeNull();
    const msg = (resultEvent as unknown as { errorMessage?: string }).errorMessage;
    expect(msg).toBe("raw string rejection");
  });
});
