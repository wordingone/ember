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
  commandButtonActivation,
  commandButtonLabel,
  packCommandBarRows,
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
      for (const button of buttons) expect(button.label).toBe(`[/${button.name}]`);
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

  test("commandButtonLabel is the run-controls button shape", () => {
    expect(commandButtonLabel("verify")).toBe("[/verify]");
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
    // "[/aa] " is 7 columns including its trailing gap.
    const rows = packCommandBarRows(cells, 14);
    expect(rows.map((row) => row.map((cell) => cell.label))).toEqual([
      ["[/aa]", "[/bb]"],
      ["[/cc]"],
    ]);
    for (const row of rows) {
      for (const cell of row) expect(cell.label).toMatch(/^\[\/[a-z-]+\]$/);
    }
  });

  test("a label wider than the pane still gets its own whole row (never a clipped fragment)", () => {
    const buttons = buildCommandButtons([cmd("a"), cmd("an-extremely-long-command-name")]);
    const cells: CommandBarCell[] = buttons.map((b) => ({ kind: "button", label: b.label, button: b }));
    const rows = packCommandBarRows(cells, 8);
    expect(rows).toHaveLength(2);
    expect(rows[1]![0]!.label).toBe("[/an-extremely-long-command-name]");
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
