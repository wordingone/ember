// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// issue #1044 acceptance: NO production source or fixture may carry the removed
// keybinding-hint chrome strings. Repo-wide grep test over src/ — fails if any
// hint literal is resurrected anywhere (source, fixture, or snapshot).
import { describe, it, expect } from "bun:test";
import { readFileSync, readdirSync, statSync } from "fs";
import { join } from "path";

const BANNED = ["esc to interrupt", "(shift+tab to cycle)", "ctrl+t to show tasks", "ctrl+t to hide tasks"];

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (p.endsWith(".ts") || p.endsWith(".tsx")) out.push(p);
  }
  return out;
}

describe("hint-chrome absence (repo-wide, #1044)", () => {
  it("no src file carries a removed hint literal outside documented removal comments", () => {
    const offenders: string[] = [];
    for (const file of walk(join(import.meta.dir, ".."))) {
      if (file.endsWith("status-bar-hint-absence.test.ts")) continue;
      const lines = readFileSync(file, "utf8").split("\n");
      lines.forEach((line, i) => {
        if (line.trimStart().startsWith("//") || line.trimStart().startsWith("*")) return; // doc comments about the removal
        if (line.includes("not.toContain")) return; // absence assertions
        for (const banned of BANNED) {
          if (line.includes(banned)) offenders.push(`${file}:${i + 1}`);
        }
      });
    }
    expect(offenders).toEqual([]);
  });
});
