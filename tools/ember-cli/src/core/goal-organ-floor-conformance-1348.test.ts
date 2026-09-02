// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Issue #1348 bounded-exception audit contract. This test checks the durable
// audit record; it does not claim full goal-organ conformance or close #663.

import { describe, expect, it } from "bun:test";

const auditPath = new URL(
  "../../../../docs/domains/governance/archive/goal/goal-organ-floor-conformance-20260710.md",
  import.meta.url,
);
const audit = await Bun.file(auditPath).text();

describe("issue #1348 bounded-exception audit record", () => {
  it("records route (a) and names the permanent timer-subordination guards", () => {
    expect(audit).toContain("ISSUE-1348-ROUTE-A-ACCEPTED");
    expect(audit).toContain("injectable scheduler");
    expect(audit).toContain("shouldPoke");
    expect(audit).toContain("kill switch");
    expect(audit).toContain("cleanup");
    expect(audit).toContain("finite positive interval");
    expect(audit).toContain("#663 remains OPEN");
  });

  it("binds citations to the current unnumbered mechanism sections", () => {
    expect(audit).toContain("docs/contracts/goal-mode-mechanism.md");
    expect(audit).toContain("Selection and persistence");
    expect(audit).toContain("Continuation loop");
    expect(audit).toContain("Artifact binding");
    expect(audit).toContain("Operator relationship");
    expect(audit).not.toContain("docs/contracts/goal-mode-mechanism.md §");
  });
});
