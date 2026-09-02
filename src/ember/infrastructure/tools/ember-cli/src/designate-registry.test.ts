// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, it } from "bun:test";
import fs from "node:fs";
import path from "node:path";


describe("/designate registry surface", () => {
  it("registers exactly one load-bearing owned-selection command", () => {
    const registry = fs.readFileSync(
      path.join(import.meta.dir, "command-registry.ts"),
      "utf8",
    );
    expect(registry.match(/import \{ createDesignateCommand \}/g)).toHaveLength(1);
    expect(registry.match(/createDesignateCommand\(\)/g)).toHaveLength(1);
  });
});
