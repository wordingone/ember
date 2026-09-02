// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// spine-first-screen.test.ts — acceptance for the six-row spine block on the home screen.
// Frozen spec: the spine-on-first-screen spec, acceptance rows A1, A2, A4, A4b, A5.
//
// A5 IS WRITTEN FIRST AND DELIBERATELY. Every acceptance failure this month came from a happy-path
// render blessing a fail-open branch: a test that only renders the good case cannot tell a real
// status from a default. So the degraded input comes before the working one, here and below.

import { describe, it, expect } from "bun:test";
import type { RegistryCommand } from "../types/command-types.ts";
import {
  SPINE_FUNCTIONS,
  buildSpineRows,
  renderSpineRow,
  renderSpineBlock,
} from "./spine-first-screen.ts";

function cmd(name: string, enabled: boolean | (() => boolean) = true): RegistryCommand {
  return {
    name,
    description: `${name} description`,
    isEnabled: typeof enabled === "function" ? enabled : () => enabled,
    execute: async () => undefined,
  } as RegistryCommand;
}

/** Every command the six functions name, all enabled. The healthy case. */
function fullRegistry(): RegistryCommand[] {
  const names = [...new Set(SPINE_FUNCTIONS.map((f) => f.command))];
  return names.map((n) => cmd(n));
}

// ---------------------------------------------------------------------------
// A5 — fail closed. Written first, on purpose.
// ---------------------------------------------------------------------------

describe("A5 fail-closed: a degraded registry never produces a flattering block", () => {
  it("undefined commands yields six BLOCKED rows, not zero rows", () => {
    const rows = buildSpineRows(undefined);
    expect(rows).toHaveLength(SPINE_FUNCTIONS.length);
    expect(rows.every((r) => r.status === "BLOCKED")).toBe(true);
  });

  it("null and an empty list behave identically to undefined", () => {
    for (const input of [null, []] as const) {
      const rows = buildSpineRows(input);
      expect(rows).toHaveLength(SPINE_FUNCTIONS.length);
      expect(rows.every((r) => r.status === "BLOCKED")).toBe(true);
    }
  });

  it("a BLOCKED row prints NO command text — it never teaches an untypeable name", () => {
    // The failure this forbids: rendering the literal from SPINE_FUNCTIONS when nothing resolved,
    // which reads to an operator as "type this" and then does nothing.
    const rows = buildSpineRows([]);
    for (const r of rows) {
      expect(r.command).toBe("");
      expect(r.reason).not.toBe("");
    }
  });

  it("a command present but disabled reads OFFLINE, never BOUND", () => {
    const rows = buildSpineRows(fullRegistry().map((c) => cmd(c.name, false)));
    expect(rows.every((r) => r.status === "OFFLINE")).toBe(true);
    // It still shows the command text: the function IS reachable, just not right now.
    expect(rows.every((r) => r.command !== "")).toBe(true);
  });

  it("a command whose isEnabled() THROWS is not advertised as ready", () => {
    // The fail-open shape being closed: an exception treated as falsy-but-fine, or worse, as BOUND.
    const throwing = fullRegistry().map((c) =>
      cmd(c.name, () => {
        throw new Error("enablement check exploded");
      }),
    );
    const rows = buildSpineRows(throwing);
    expect(rows.every((r) => r.status === "OFFLINE")).toBe(true);
    expect(rows.every((r) => r.reason === "availability check failed")).toBe(true);
  });

  it("a partially-populated registry degrades per row, not wholesale", () => {
    // Only `custody` registered. That row is BOUND; the rest are BLOCKED. A block that went all
    // BLOCKED or all BOUND here would be reporting a summary, not six independent facts.
    const rows = buildSpineRows([cmd("custody")]);
    const custodyRows = rows.filter((r) => r.command.startsWith("/custody"));
    expect(custodyRows.length).toBeGreaterThan(0);
    expect(custodyRows.every((r) => r.status === "BOUND")).toBe(true);
    expect(rows.some((r) => r.status === "BLOCKED")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// A1 — the six functions are named
// ---------------------------------------------------------------------------

describe("A1: every spine function the gate names appears", () => {
  it("there are exactly six functions, and the count is the claim", () => {
    // A seventh row means someone widened the gate's sentence without saying so.
    expect(SPINE_FUNCTIONS).toHaveLength(6);
  });

  it("each gate-named function has a row whose label is operator language", () => {
    const rows = buildSpineRows(fullRegistry());
    const labels = rows.map((r) => r.label.toLowerCase());
    for (const needle of [
      "custody",
      "identity manifest",
      "tokenizer lineage",
      "checkpoint save",
      "owned serving path",
      "benchmarking",
      "3b training launch",
    ]) {
      expect(labels.some((l) => l.includes(needle))).toBe(true);
    }
  });

  it("no label leaks an internal noun", () => {
    // The tips box already spends the first screen teaching someone else's product; the fix is not
    // to replace that with our own jargon.
    const rows = buildSpineRows(fullRegistry());
    for (const r of rows) {
      expect(r.label).not.toMatch(/EMBER-0|B5\.5|workstream|manifest\.json|assemble/i);
    }
  });
});

// ---------------------------------------------------------------------------
// A2 — six rows, structurally, at every width
// ---------------------------------------------------------------------------

describe("A2: the block is six rows by construction, not by measurement", () => {
  const WIDTHS = [20, 32, 40, 60, 80, 100, 200];

  it("renders exactly six lines at every supported width", () => {
    const rows = buildSpineRows(fullRegistry());
    for (const w of WIDTHS) {
      expect(renderSpineBlock(rows, w)).toHaveLength(6);
    }
  });

  it("no single row ever exceeds its width — a row that wraps is two rows in production", () => {
    // This is the assertion that the palette-budget incident earns: a compact bar is one row
    // everywhere the test looked and two rows at the narrowest real terminal.
    const rows = buildSpineRows(fullRegistry());
    for (const w of WIDTHS) {
      for (const line of renderSpineBlock(rows, w)) {
        expect(line.length).toBeLessThanOrEqual(w);
      }
    }
  });

  it("holds at the narrowest width for DEGRADED rows too", () => {
    // Reason text is longer than command text for several rows; the truncation must not care.
    for (const input of [undefined, [], [cmd("custody")]] as const) {
      const rows = buildSpineRows(input);
      for (const w of WIDTHS) {
        const lines = renderSpineBlock(rows, w);
        expect(lines).toHaveLength(6);
        for (const line of lines) expect(line.length).toBeLessThanOrEqual(w);
      }
    }
  });

  it("a row containing no newline cannot become two rows", () => {
    const rows = buildSpineRows(fullRegistry());
    for (const w of WIDTHS) {
      for (const line of renderSpineBlock(rows, w)) {
        expect(line).not.toContain("\n");
      }
    }
  });
});

// ---------------------------------------------------------------------------
// A4 / A4b — the command column is derived, never hand-typed
// ---------------------------------------------------------------------------

describe("A4: command text comes from the registry, not from a literal", () => {
  it("resolves through aliases, and prints the REGISTRY's name", () => {
    // The drift being guarded: a command renamed upstream while SPINE_FUNCTIONS keeps the old
    // string. Here the registry knows `custody-v2` with `custody` as an alias; the row must print
    // the real name, because that is what the operator has to type.
    const renamed: RegistryCommand[] = [
      { ...cmd("custody-v2"), aliases: ["custody"] } as RegistryCommand,
      cmd("model"),
      cmd("benchmark"),
      cmd("train"),
    ];
    const rows = buildSpineRows(renamed);
    const row = rows.find((r) => r.label.includes("custody"))!;
    expect(row.status).toBe("BOUND");
    expect(row.command).toContain("/custody-v2");
    expect(row.command).not.toContain("/custody ");
  });

  it("every BOUND row's command resolves against the list it was built from", () => {
    // Derived-and-checked, rather than two hand-written strings agreeing with each other.
    const registry = fullRegistry();
    const names = new Set(registry.map((c) => c.name));
    for (const r of buildSpineRows(registry)) {
      if (r.status !== "BOUND") continue;
      const first = r.command.split(/\s+/)[0]!.replace(/^\//, "");
      expect(names.has(first)).toBe(true);
    }
  });
});

describe("A4b: a function whose command vanishes degrades, and says so", () => {
  it("removing `train` blocks exactly the training row and nothing else", () => {
    const withoutTrain = fullRegistry().filter((c) => c.name !== "train");
    const rows = buildSpineRows(withoutTrain);
    const trainRow = rows.find((r) => r.label.includes("training launch"))!;
    expect(trainRow.status).toBe("BLOCKED");
    expect(trainRow.command).toBe("");
    // Every other row is unaffected — the degradation is per-function.
    const others = rows.filter((r) => r !== trainRow);
    expect(others.every((r) => r.status === "BOUND")).toBe(true);
  });

  it("removing `model` blocks all three functions that `model` drives", () => {
    // Three of the six ride one command. If that is ever not true, this test says so loudly, which
    // is the point: the mapping is a claim about the product, not a formatting detail.
    const withoutModel = fullRegistry().filter((c) => c.name !== "model");
    const rows = buildSpineRows(withoutModel);
    const blocked = rows.filter((r) => r.status === "BLOCKED");
    expect(blocked).toHaveLength(
      SPINE_FUNCTIONS.filter((f) => f.command === "model").length,
    );
  });
});

// ---------------------------------------------------------------------------
// Truncation is honest
// ---------------------------------------------------------------------------

describe("truncation marks itself", () => {
  it("a truncated line ends with an ellipsis so the operator knows text was cut", () => {
    const rows = buildSpineRows(fullRegistry());
    const line = renderSpineRow(rows[0]!, 18);
    expect(line.length).toBeLessThanOrEqual(18);
    expect(line.endsWith("…")).toBe(true);
  });

  it("an absurd width still yields one line, never a crash or an empty string", () => {
    const rows = buildSpineRows(fullRegistry());
    for (const w of [1, 2, 3]) {
      const line = renderSpineRow(rows[0]!, w);
      expect(line.length).toBeGreaterThan(0);
      expect(line.length).toBeLessThanOrEqual(w);
    }
  });
});

// ---------------------------------------------------------------------------
// PRODUCTION ENTRY — the test that would have caught "wired but nothing feeds it"
// ---------------------------------------------------------------------------

import { getCommands, resetCommandRegistryForTests, clearCommandsCache } from "../command-registry.ts";
import { Homescreen, FeedComponent, rootDisclosure, samePathForDisplay } from "./logo-homescreen.ts";

function findText(el: any, pred: (s: string) => boolean): string | null {
  if (el == null || typeof el !== "object") {
    return typeof el === "string" && pred(el) ? el : null;
  }
  const kids = el.props?.children;
  for (const k of Array.isArray(kids) ? kids : [kids]) {
    if (typeof k === "string") { if (pred(k)) return k; continue; }
    const hit = findText(k, pred);
    if (hit) return hit;
  }
  return null;
}

describe("production entry: the REAL registry resolves every spine function", () => {
  it("getCommands() — the same call the REPL makes — leaves no row BLOCKED", async () => {
    // Every assertion above this point used a registry I constructed, which can only prove the
    // resolver works on the shape I already believed in. This drives the real one. It is the
    // difference between verifying the component and verifying the product: a block wired into a
    // screen that nobody feeds renders six BLOCKED rows and looks like a broken spine.
    resetCommandRegistryForTests();
    clearCommandsCache();
    const real = await getCommands(process.cwd());
    const rows = buildSpineRows(real);
    const blocked = rows.filter((r) => r.status === "BLOCKED");
    expect(blocked.map((r) => r.label)).toEqual([]);
    expect(rows).toHaveLength(6);
  });

  it("the rendered home screen shows those commands, through the real Homescreen", async () => {
    resetCommandRegistryForTests();
    clearCommandsCache();
    const real = await getCommands(process.cwd());
    const el = Homescreen({ state: {}, viewportWidth: 120, spineCommands: real });
    // Walk to the onboarding feed and actually render it, exactly as the screen does.
    const panel: any = findPanelLike(el);
    const rightCol = (Array.isArray(panel.props.children) ? panel.props.children : [panel.props.children])[1];
    const feedEl = (Array.isArray(rightCol.props.children) ? rightCol.props.children : [rightCol.props.children])
      .find((c: any) => c && c.key === "onboarding");
    expect(feedEl).toBeTruthy();
    const rendered = FeedComponent(feedEl.props);
    for (const needle of ["/custody", "/model", "/benchmark", "/train"]) {
      expect(findText(rendered, (s) => s.includes(needle))).not.toBeNull();
    }
    // and the failure state must NOT be on screen
    expect(findText(rendered, (s) => s.includes("no command registered"))).toBeNull();
  });
});

/** Homescreen wraps its columns in one outer panel; find it without depending on nesting depth. */
function findPanelLike(el: any): any {
  const kids = Array.isArray(el.props?.children) ? el.props.children : [el.props?.children];
  if (kids.some((k: any) => k && k.key === "panel")) {
    return kids.find((k: any) => k && k.key === "panel");
  }
  for (const k of kids) {
    if (k && typeof k === "object" && k.props) {
      const found = findPanelLike(k);
      if (found) return found;
    }
  }
  return el.key === "panel" ? el : null;
}

// ---------------------------------------------------------------------------
// A6 — the launch-root disclosure, asserted in BOTH directions
// ---------------------------------------------------------------------------

describe("A6: the canonical-root disclosure appears exactly when it should", () => {
  it("appears when the launch directory differs from the bound root", () => {
    const el = rootDisclosure("R:/repo", "R:/some-worktree");
    expect(el).not.toBeNull();
    expect(findText(el, (s) => s.includes("R:/repo"))).not.toBeNull();
  });

  it("does NOT appear when they are the same directory", () => {
    expect(rootDisclosure("R:/repo", "R:/repo")).toBeNull();
  });

  it("does NOT appear for two spellings of one path — a warning that cries wolf is worse than none", () => {
    // Windows hands us backslashes from one source and forward slashes from another, and trailing
    // separators vary. All three of these name the same directory.
    expect(rootDisclosure("R:/repo", "R:\\repo")).toBeNull();
    expect(rootDisclosure("R:/repo", "R:/repo/")).toBeNull();
    expect(rootDisclosure("R:/repo", "r:/REPO")).toBeNull();
    expect(samePathForDisplay("R:/repo", "R:\\repo\\")).toBe(true);
  });

  it("stays silent when the caller supplies no launch directory — silence means no discrepancy", () => {
    expect(rootDisclosure("R:/repo", undefined)).toBeNull();
    expect(rootDisclosure(undefined, "R:/somewhere")).toBeNull();
  });

  it("still fires for two genuinely different directories that share a prefix", () => {
    // The normalisation must not over-collapse: these are different trees.
    expect(rootDisclosure("R:/repo", "R:/repo-elsewhere")).not.toBeNull();
  });
});

// A7 — a BOUND row's command is fully typeable at every supported width (added 2026-07-25 from an
// independent review). Putting the command before the label stopped the LABEL from eating it; it
// did not stop the WIDTH from eating it. At width 20 the longest row rendered `BOUND   /model mani…`
// — a name that resolves to nothing, which is the exact harm the whole block exists to remove.
// The cure drops the sub-verb before it clips the command name, so what is shown is always a
// command the operator can actually type.
describe("A7: a shown command is always a typeable command", () => {
  const rows = buildSpineRows(fullRegistry());
  for (const width of [20, 24, 28, 31, 32, 38, 60, 80]) {
    it(`every BOUND row shows a complete command at width ${width}`, () => {
      for (const row of rows.filter((r) => r.status === "BOUND")) {
        const line = renderSpineRow(row, width);
        const shown = line.slice(8).split("  ")[0]!.replace(/…$/, "");
        // Whatever survived truncation must be a real prefix-complete command: either the full
        // command text or its base. A partial word is the defect.
        expect([row.command, row.commandBase]).toContain(shown.trim());
      }
    });
  }

  it("drops the verb rather than the command name when the full text will not fit", () => {
    const row = rows.find((r) => r.command === "/model manifest inspect")!;
    expect(renderSpineRow(row, 20)).toContain("/model");
    expect(renderSpineRow(row, 20)).not.toContain("/model mani…");
    expect(renderSpineRow(row, 80)).toContain("/model manifest inspect");
  });
});
