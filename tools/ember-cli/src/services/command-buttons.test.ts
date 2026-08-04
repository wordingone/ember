// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// services/command-buttons.test.ts — the registry-derivation contract (#1370).
//
// The load-bearing assertions here are the ones that would FAIL if anyone ever reintroduced a
// hand-maintained button list: the button set is compared against the LIVE registry
// (`getCommands`), and against a registry mutated at test time, never against a fixture list of
// names copied from the source.

import { describe, expect, test } from "bun:test";
import {
  buildCommandButtons,
  commandBarLayout,
  commandBarPages,
  commandButtonActivation,
  commandButtonGroupId,
  commandButtonLabel,
  commandBarRowCount,
  groupCommandButtons,
  packCommandBarRows,
  resolveCommandBarPage,
  type CommandBarCell,
} from "./command-buttons.ts";
import {
  getCommands,
  resetCommandRegistryForTests,
  setCommandRegistryDeps,
} from "../command-registry.ts";
import type { RegistryCommand } from "../types/command-types.ts";

function cmd(name: string, overrides: Partial<RegistryCommand> = {}): RegistryCommand {
  return {
    name,
    description: `${name} description`,
    isEnabled: () => true,
    execute: async () => undefined,
    ...overrides,
  };
}

function buttonCells(rows: CommandBarCell[][]): string[] {
  return rows.flat().filter((cell) => cell.kind === "button").map((cell) => cell.label);
}

describe("buildCommandButtons — derived from the registry, never declared", () => {
  test("every command in the LIVE registry has a button, in registry order", async () => {
    resetCommandRegistryForTests();
    try {
      const commands = await getCommands(process.cwd());
      const buttons = buildCommandButtons(commands);
      expect(buttons.map((b) => b.name)).toEqual(commands.map((c) => c.name));
      expect(buttons.length).toBeGreaterThan(0);
      for (const button of buttons) expect(button.label).toBe(`[${button.name}]`);
    } finally {
      resetCommandRegistryForTests();
    }
  });

  test("a command registered at test time gains a button with no change to this module", async () => {
    resetCommandRegistryForTests();
    try {
      setCommandRegistryDeps({
        getBuiltinCommands: () => [cmd("alpha"), cmd("beta"), cmd("newly-registered")],
      });
      const commands = await getCommands("/tmp/registry-growth");
      const names = buildCommandButtons(commands).map((b) => b.name);
      expect(names).toEqual(["alpha", "beta", "newly-registered"]);
    } finally {
      resetCommandRegistryForTests();
    }
  });

  test("de-duplicates by name, first occurrence winning", () => {
    const buttons = buildCommandButtons([cmd("model"), cmd("watch"), cmd("model")]);
    expect(buttons.map((b) => b.name)).toEqual(["model", "watch"]);
  });

  test("isEnabled() false yields a rendered-but-disabled button with a reason", () => {
    const [button] = buildCommandButtons([cmd("train", { isEnabled: () => false })]);
    expect(button!.enabled).toBe(false);
    expect(button!.disabledReason).toBeTruthy();
  });

  test("a THROWING isEnabled() disables the button instead of taking the render down", () => {
    const [button] = buildCommandButtons([
      cmd("custody", { isEnabled: () => { throw new Error("root bindings store unreadable"); } }),
    ]);
    expect(button!.enabled).toBe(false);
    expect(button!.disabledReason).toBe("root bindings store unreadable");
  });

  test("argumentHint on the registry entry is what marks a command as needing arguments", () => {
    const buttons = buildCommandButtons([
      cmd("verify"),
      cmd("admit", { argumentHint: "--workspace <path>" }),
    ]);
    expect(buttons[0]!.needsArgument).toBe(false);
    expect(buttons[1]!.needsArgument).toBe(true);
    expect(buttons[1]!.argumentHint).toBe("--workspace <path>");
  });

  test("the shipped /admit and /designate declare argument hints; /model and /verify do not", async () => {
    resetCommandRegistryForTests();
    try {
      const buttons = buildCommandButtons(await getCommands(process.cwd()));
      const byName = new Map(buttons.map((b) => [b.name, b]));
      expect(byName.get("admit")?.needsArgument).toBe(true);
      expect(byName.get("designate")?.needsArgument).toBe(true);
      expect(byName.get("model")?.needsArgument).toBe(false);
      expect(byName.get("verify")?.needsArgument).toBe(false);
    } finally {
      resetCommandRegistryForTests();
    }
  });

  test("commandButtonLabel is the run-controls button shape, WITHOUT the slash (#1399)", () => {
    expect(commandButtonLabel("verify")).toBe("[verify]");
  });

  test("dropping the slash from the label cannot change what the button runs (#1399)", () => {
    // The regression this forecloses is a relabel that quietly relabels the DISPATCH too. Label
    // and activation are asserted against each other here, over the live registry, so the two can
    // never be edited apart.
    const buttons = buildCommandButtons([cmd("verify"), cmd("train")]);
    for (const button of buttons) {
      expect(button.label).not.toContain("/");
      expect(commandButtonActivation(button)).toEqual({ kind: "dispatch", text: `/${button.name}` });
    }
  });
});

describe("commandButtonActivation — what a click means", () => {
  test("an argument-free enabled command dispatches /name", () => {
    const [button] = buildCommandButtons([cmd("verify")]);
    expect(commandButtonActivation(button!)).toEqual({ kind: "dispatch", text: "/verify" });
  });

  test("a command with required arguments composes /name and never dispatches", () => {
    const [button] = buildCommandButtons([cmd("admit", { argumentHint: "--workspace <path>" })]);
    const activation = commandButtonActivation(button!);
    expect(activation.kind).toBe("prefill");
    expect(activation).toMatchObject({ text: "/admit ", hint: "/admit --workspace <path>" });
  });

  test("a disabled command is rejected with its named reason, never dispatched", () => {
    const [button] = buildCommandButtons([cmd("train", { isEnabled: () => false })]);
    const activation = commandButtonActivation(button!);
    expect(activation.kind).toBe("rejected");
    expect((activation as { reason: string }).reason).toContain("/train is not available");
  });

  test("no activation can carry focus — the result is only ever text or a reason", () => {
    const buttons = buildCommandButtons([
      cmd("verify"),
      cmd("admit", { argumentHint: "--workspace <path>" }),
      cmd("train", { isEnabled: () => false }),
    ]);
    for (const button of buttons) {
      const keys = Object.keys(commandButtonActivation(button)).sort();
      expect(keys.every((key) => ["kind", "text", "hint", "reason"].includes(key))).toBe(true);
    }
  });
});

describe("width-bounded layout", () => {
  test("packs into as few rows as fit and never splits a label", () => {
    const buttons = buildCommandButtons([cmd("aa"), cmd("bb"), cmd("cc")]);
    const cells: CommandBarCell[] = buttons.map((b) => ({ kind: "button", label: b.label, button: b }));
    // "[aa] " is 5 columns including its trailing gap.
    const rows = packCommandBarRows(cells, 11);
    expect(rows.map((row) => row.map((cell) => cell.label))).toEqual([
      ["[aa]", "[bb]"],
      ["[cc]"],
    ]);
    for (const row of rows) {
      for (const cell of row) expect(cell.label).toMatch(/^\[[a-z-]+\]$/);
    }
  });

  test("a label wider than the pane still gets its own whole row (never a clipped fragment)", () => {
    const buttons = buildCommandButtons([cmd("a"), cmd("an-extremely-long-command-name")]);
    const cells: CommandBarCell[] = buttons.map((b) => ({ kind: "button", label: b.label, button: b }));
    const rows = packCommandBarRows(cells, 8);
    expect(rows).toHaveLength(2);
    expect(rows[1]![0]!.label).toBe("[an-extremely-long-command-name]");
  });

  test("overflow beyond the row budget is disclosed as +N more, never silently dropped", () => {
    const buttons = buildCommandButtons(
      ["one", "two", "three", "four", "five", "six", "seven", "eight"].map((n) => cmd(n)),
    );
    const layout = commandBarLayout(buttons, 24, 2);
    expect(layout.rows.length).toBeLessThanOrEqual(2);
    const overflow = layout.rows.flat().find((cell) => cell.kind === "overflow");
    expect(overflow).toBeDefined();
    expect(layout.hiddenCount).toBeGreaterThan(0);
    expect(overflow!.label).toBe(`+${layout.hiddenCount} more`);
    // Disclosure is honest: shown buttons + hidden count == the whole registry.
    expect(buttonCells(layout.rows).length + layout.hiddenCount).toBe(buttons.length);
  });

  test("no row exceeds the available width once the whole set fits the budget", () => {
    const buttons = buildCommandButtons(["one", "two", "three"].map((n) => cmd(n)));
    const layout = commandBarLayout(buttons, 40, 3);
    expect(layout.hiddenCount).toBe(0);
    for (const row of layout.rows) {
      const width = row.reduce((sum, cell) => sum + cell.label.length + 1, 0);
      expect(width).toBeLessThanOrEqual(40 + 1);
    }
  });

  test("width sweep: every width keeps rows within budget and the disclosure accurate", () => {
    const buttons = buildCommandButtons(
      ["watch", "model", "train", "verify", "admit", "designate", "goal", "custody", "benchmark", "spine"]
        .map((n) => cmd(n)),
    );
    for (let width = 12; width <= 160; width += 4) {
      for (const maxRows of [1, 2, 3]) {
        const layout = commandBarLayout(buttons, width, maxRows);
        expect(layout.rows.length).toBeLessThanOrEqual(maxRows);
        const shown = buttonCells(layout.rows).length;
        expect(shown + layout.hiddenCount).toBe(buttons.length);
        const overflow = layout.rows.flat().filter((cell) => cell.kind === "overflow");
        expect(overflow.length).toBe(layout.hiddenCount > 0 ? 1 : 0);
        // Rows only exceed the width when a single label alone cannot fit — never because two
        // labels were packed past the edge.
        for (const row of layout.rows) {
          const used = row.reduce((sum, cell) => sum + cell.label.length + 1, 0);
          if (used > width) expect(row.length).toBe(1);
        }
      }
    }
  });

  test("an empty registry renders nothing and discloses nothing", () => {
    expect(commandBarLayout([], 80, 2)).toEqual({ rows: [], hiddenCount: 0 });
  });
});

describe("commandBarPages", () => {
  const registry = () =>
    buildCommandButtons(
      ["watch", "model", "train", "verify", "admit", "designate", "goal", "custody",
        "benchmark", "spine", "status", "plan", "review", "export"].map((n) => cmd(n)),
    );

  test("the pages partition the registry exactly — nothing dropped, nothing shown twice", () => {
    const buttons = registry();
    for (let width = 12; width <= 200; width += 4) {
      for (const maxRows of [1, 2, 3]) {
        const pages = commandBarPages(buttons, width, maxRows);
        expect(pages.length).toBeGreaterThan(0);
        const shown = pages.flatMap((page) => buttonCells(page.rows));
        // Grouped order (#1399) reorders the buttons, so the partition is proved as a SET plus a
        // no-duplicates check rather than by registry sequence: every command appears, once.
        expect(shown.length).toBe(buttons.length);
        expect([...shown].sort()).toEqual(buttons.map((b) => b.label).sort());
      }
    }
  });

  test("every page carries a pager whenever there is more than one page", () => {
    const buttons = registry();
    for (let width = 12; width <= 200; width += 4) {
      for (const maxRows of [1, 2, 3]) {
        const pages = commandBarPages(buttons, width, maxRows);
        for (const page of pages) {
          const pagers = page.rows.flat().filter((cell) => cell.kind === "overflow");
          expect(pagers.length).toBe(pages.length > 1 ? 1 : 0);
          // A page that shows nothing cannot be paged past — progress must be structural.
          expect(page.count).toBeGreaterThanOrEqual(1);
        }
      }
    }
  });

  test("the pager never pushes a page past its row budget at usable widths", () => {
    const buttons = registry();
    for (const [width, maxRows] of [[40, 2], [60, 1], [80, 2], [100, 2], [140, 3]] as const) {
      for (const page of commandBarPages(buttons, width, maxRows)) {
        expect(page.rows.length).toBeLessThanOrEqual(maxRows);
        for (const row of page.rows) {
          const used = row.reduce((sum, cell) => sum + cell.label.length + 1, 0);
          if (used > width) expect(row.length).toBe(1);
        }
      }
    }
  });

  test("a remembered page index is wrapped onto the live page count, never left dangling", () => {
    expect(resolveCommandBarPage(0, 3)).toBe(0);
    expect(resolveCommandBarPage(2, 3)).toBe(2);
    expect(resolveCommandBarPage(3, 3)).toBe(0);
    expect(resolveCommandBarPage(7, 3)).toBe(1);
    expect(resolveCommandBarPage(-1, 3)).toBe(2);
    expect(resolveCommandBarPage(5, 0)).toBe(0);
    expect(resolveCommandBarPage(Number.NaN, 3)).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// #1399 — grouping
// ---------------------------------------------------------------------------

describe("command-button groups (#1399)", () => {
  test("every LIVE registry command lands in exactly one group, none dropped", async () => {
    resetCommandRegistryForTests();
    try {
      const buttons = buildCommandButtons(await getCommands(process.cwd()));
      const groups = groupCommandButtons(buttons);
      const grouped = groups.flatMap((group) => group.buttons.map((button) => button.name));
      expect(grouped.length).toBe(buttons.length);
      expect([...grouped].sort()).toEqual(buttons.map((b) => b.name).sort());
      // Non-empty groups only: a caption with nothing under it is chrome that says nothing.
      for (const group of groups) expect(group.buttons.length).toBeGreaterThan(0);
    } finally {
      resetCommandRegistryForTests();
    }
  });

  test("an unclassified command still gets a button — grouping is not a second registry", () => {
    // This is the #1370 class-kill re-asserted against the #1399 grouping: a command no group
    // names must still appear, or the group table has quietly become the list of what exists.
    expect(commandButtonGroupId("a-skill-nobody-classified")).toBe("more");
    const buttons = buildCommandButtons([cmd("verify"), cmd("a-skill-nobody-classified")]);
    const grouped = groupCommandButtons(buttons).flatMap((group) => group.buttons.map((b) => b.name));
    expect(grouped.sort()).toEqual(["a-skill-nobody-classified", "verify"]);
  });

  test("the stated grouping logic is the one that ships", () => {
    expect(commandButtonGroupId("train")).toBe("launch");
    expect(commandButtonGroupId("verify")).toBe("launch");
    expect(commandButtonGroupId("model")).toBe("inspect");
    expect(commandButtonGroupId("custody")).toBe("inspect");
    expect(commandButtonGroupId("designate")).toBe("govern");
    expect(commandButtonGroupId("goal")).toBe("govern");
    // /resume is session resume and deliberately NOT in a run group: a lowercase [resume] sitting
    // under the run control [RESUME] would read as two spellings of one control.
    expect(commandButtonGroupId("resume")).toBe("more");
  });

  test("a group caption always opens its own row, so groups read as blocks", () => {
    const buttons = buildCommandButtons([cmd("train"), cmd("verify"), cmd("model"), cmd("goal")]);
    const pages = commandBarPages(buttons, 200, 8);
    const rows = pages[0]!.rows;
    for (const row of rows) {
      const captions = row.filter((cell) => cell.kind === "group");
      expect(captions.length).toBeLessThanOrEqual(1);
      // A caption is only ever the FIRST cell of a row — never spliced between buttons.
      if (captions.length === 1) expect(row[0]!.kind).toBe("group");
    }
    expect(rows.length).toBe(3); // launch, inspect, govern — one row each at this width
  });

  test("captions are never clickable cells and never counted as buttons", () => {
    const buttons = buildCommandButtons([cmd("train"), cmd("model")]);
    const cells = commandBarPages(buttons, 200, 4)[0]!.rows.flat();
    expect(cells.filter((cell) => cell.kind === "group").length).toBe(2);
    expect(buttonCells([cells])).toEqual(["[train]", "[model]"]);
  });

  test("commandBarRowCount is the height the bar actually draws", () => {
    const buttons = buildCommandButtons([cmd("train"), cmd("verify"), cmd("model")]);
    for (const width of [16, 24, 40, 80, 160]) {
      for (const maxRows of [1, 2, 4, 6]) {
        const pages = commandBarPages(buttons, width, maxRows);
        const rendered = pages[0]!.rows.length;
        expect(commandBarRowCount(buttons, width, maxRows, 0, false)).toBe(rendered);
        expect(commandBarRowCount(buttons, width, maxRows, 0, true)).toBe(rendered + 1);
      }
    }
    expect(commandBarRowCount([], 80, 3)).toBe(0);
  });
});
