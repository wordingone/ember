// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// commands/compact.test.ts -- the /compact command (#2372).

import { afterEach, describe, expect, it } from "bun:test";
import { createCompactCommand } from "./compact.ts";
import { setSessionControl } from "../services/session-control.ts";
import { findCommand, getCommands } from "../command-registry.ts";
import { tryDispatchSlashCommand } from "../services/slash-dispatch.ts";

const ctx = { sessionId: "s", mode: "regular", cwd: process.cwd() };

afterEach(() => setSessionControl(null));

describe("/compact", () => {
  it("passes its argument to the session as summary instructions", async () => {
    const seen: string[] = [];
    setSessionControl({
      compact: async (instructions) => {
        seen.push(instructions);
        return { status: "compacted", trigger: "manual", tokensBefore: 9000, tokensAfter: 700, elapsedSecs: 2 };
      },
    });
    const result = await createCompactCommand().execute("  focus on open bugs  ", ctx);
    expect(seen).toEqual(["focus on open bugs"]);
    expect(result).toEqual({ type: "message", message: "Conversation compacted: ~9,000 → ~700 tokens." });
  });

  it("reports there is nothing to compact when no session is attached", async () => {
    const result = await createCompactCommand().execute("", ctx);
    expect(result).toEqual({ type: "message", message: "No active conversation to compact." });
  });

  it("relays a skipped outcome", async () => {
    setSessionControl({ compact: async () => ({ status: "skipped", reason: "too-short" }) });
    const result = await createCompactCommand().execute("", ctx);
    expect(result?.message).toContain("Nothing to compact");
  });

  it("is registered, so typing /compact reaches it", async () => {
    const cmds = await getCommands(process.cwd());
    expect(findCommand("compact", cmds)?.name).toBe("compact");
    setSessionControl({ compact: async () => ({ status: "skipped", reason: "below-threshold" }) });
    const out = await tryDispatchSlashCommand("/compact keep paths", ctx);
    expect(out?.message).toContain("below the compaction threshold");
  });
});
