// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, it } from "bun:test";

import { parseSlashInput } from "../services/slash-dispatch.ts";
import { createClearCommand, createHelpCommand } from "./session-basics.ts";

describe("session basics", () => {
  it("/help lists enabled commands and the key bindings", async () => {
    const help = createHelpCommand(async () => [
      createClearCommand(),
      { name: "off", description: "hidden", isEnabled: () => false, execute: async () => undefined },
    ]);
    const r = await help.execute("", { cwd: "." } as never);
    expect(r && r.message).toContain("/clear");
    expect(r && r.message).not.toContain("/off");
    expect(r && r.message).toContain("PageUp");
  });

  it("a prompt that starts with a path is not a command", () => {
    expect(parseSlashInput("/etc/hosts looks wrong")).toBeNull();
    expect(parseSlashInput("/tmp/x.txt")).toBeNull();
    expect(parseSlashInput("/help")).toEqual({ name: "help", args: "" });
    expect(parseSlashInput("/plugin:cmd go")).toEqual({ name: "plugin:cmd", args: "go" });
  });
});
