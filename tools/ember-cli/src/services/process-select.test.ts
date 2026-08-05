// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// services/process-select.test.ts — the pure half of #1475: the registry split that feeds the
// SELECT PROCESS dropdown, the START stage machine, and the activation START dispatches.
import { describe, expect, test } from "bun:test";
import type { RegistryCommand } from "../types/command-types.ts";
import { commandButtonActivation, buildCommandButtons } from "./command-buttons.ts";
import {
  buildProcessOptions,
  isProcessCommand,
  processCommands,
  processMenuLayout,
  processMenuRowBudget,
  selectProcessButtonLabel,
  startActivation,
  startControlLabel,
  startStage,
  subordinateCommands,
  START_NEEDS_SELECTION_REASON,
} from "./process-select.ts";

function cmd(name: string, overrides: Partial<RegistryCommand> = {}): RegistryCommand {
  return {
    name,
    description: `${name} description`,
    isEnabled: () => true,
    execute: async () => {},
    ...overrides,
  };
}

// The live registry order, as rendered by the pre-#1475 command bar the directive quotes.
const REGISTRY = [
  cmd("observatory"), cmd("watch"), cmd("finetune"), cmd("model"), cmd("train"),
  cmd("verify"), cmd("verify-training"), cmd("admit"), cmd("designate"), cmd("goal"),
  cmd("custody"), cmd("benchmark"), cmd("spine"), cmd("resume"),
];

describe("process/subordinate registry split", () => {
  test("processes are the launch group plus the more catch-all — the directive's exact list", () => {
    expect(processCommands(REGISTRY).map((command) => command.name)).toEqual([
      "finetune", "train", "verify", "verify-training", "benchmark", "resume",
    ]);
    expect(subordinateCommands(REGISTRY).map((command) => command.name)).toEqual([
      "observatory", "watch", "model", "admit", "designate", "goal", "custody", "spine",
    ]);
  });

  test("the two slices partition the registry exactly — no command loses its click surface", () => {
    const processes = processCommands(REGISTRY).map((command) => command.name);
    const subordinate = subordinateCommands(REGISTRY).map((command) => command.name);
    expect([...processes, ...subordinate].sort()).toEqual(REGISTRY.map((command) => command.name).sort());
    expect(processes.filter((name) => subordinate.includes(name))).toEqual([]);
  });

  test("a newly registered command lands in the dropdown with zero edits (catch-all, no second list)", () => {
    expect(isProcessCommand("some-future-skill")).toBe(true);
    const withNew = [...REGISTRY, cmd("some-future-skill")];
    expect(buildProcessOptions(withNew).map((option) => option.name)).toContain("some-future-skill");
  });

  test("options carry the SAME button model the command bar uses (enablement, needsArgument)", () => {
    const registry = [
      cmd("train"),
      cmd("verify", { argumentHint: "<target>" }),
      cmd("benchmark", { isEnabled: () => false }),
    ];
    const options = buildProcessOptions(registry);
    expect(options.map((option) => [option.name, option.enabled, option.needsArgument])).toEqual([
      ["train", true, false],
      ["verify", true, true],
      ["benchmark", false, false],
    ]);
  });
});

describe("START stage machine", () => {
  test("no selection -> unarmed; selection -> armed; selection with its own offer -> confirm", () => {
    expect(startStage(undefined, undefined)).toBe("unarmed");
    expect(startStage("train", undefined)).toBe("armed");
    expect(startStage("train", { process: "train", offerId: "train-1-x" })).toBe("confirm");
  });

  test("an offer for a DIFFERENT process never flips the selected one to confirm", () => {
    expect(startStage("verify", { process: "train", offerId: "train-1-x" })).toBe("armed");
    // ...and deselecting entirely disarms regardless of the outstanding offer.
    expect(startStage(undefined, { process: "train", offerId: "train-1-x" })).toBe("unarmed");
  });

  test("labels: confirm stage says so ON the button; the toggle names the selection", () => {
    expect(startControlLabel("unarmed")).toBe("[START]");
    expect(startControlLabel("armed")).toBe("[START]");
    expect(startControlLabel("confirm")).toBe("[CONFIRM START]");
    expect(selectProcessButtonLabel(undefined)).toBe("[SELECT PROCESS ▾]");
    expect(selectProcessButtonLabel("train")).toBe("[PROCESS: train ▾]");
  });
});

describe("startActivation — what a START click means", () => {
  const options = buildProcessOptions([
    cmd("train"),
    cmd("verify", { argumentHint: "<target>" }),
    cmd("benchmark", { isEnabled: () => false }),
  ]);
  const byName = (name: string) => options.find((option) => option.name === name)!;

  test("nothing selected -> rejected with the named reason, never a dispatch", () => {
    expect(startActivation(undefined, undefined)).toEqual({
      kind: "rejected",
      reason: START_NEEDS_SELECTION_REASON,
    });
  });

  test("armed process without a membrane offer -> byte-identical to the command button's own activation", () => {
    expect(startActivation(byName("train"), undefined)).toEqual(commandButtonActivation(byName("train")));
    expect(startActivation(byName("train"), undefined)).toEqual({ kind: "dispatch", text: "/train" });
    // Needs-argument processes compose instead of blind-dispatching, exactly like their button.
    expect(startActivation(byName("verify"), undefined)).toEqual(commandButtonActivation(byName("verify")));
    expect(startActivation(byName("verify"), undefined)).toMatchObject({ kind: "prefill", text: "/verify " });
    // Disabled processes reject with the button's own named reason.
    expect(startActivation(byName("benchmark"), undefined)).toMatchObject({ kind: "rejected" });
  });

  test("offered process -> the exact confirm text the membrane surfaced, membrane still decides", () => {
    expect(startActivation(byName("train"), { process: "train", offerId: "train-7-abc" })).toEqual({
      kind: "dispatch",
      text: "/train confirm train-7-abc",
    });
    // An offer for another process does not hijack the selected one's activation.
    expect(startActivation(byName("verify"), { process: "train", offerId: "train-7-abc" })).toMatchObject({
      kind: "prefill",
    });
  });
});

describe("processMenuLayout — every process mouse-reachable at every height", () => {
  const options = buildCommandButtons([
    cmd("a1"), cmd("b2"), cmd("c3"), cmd("d4"), cmd("e5"), cmd("f6"),
  ]);

  test("everything fits -> one page, no pager row", () => {
    expect(processMenuLayout(options, 6, 0)).toEqual({
      visible: options,
      hiddenCount: 0,
      page: 0,
      pageCount: 1,
    });
  });

  test("overflow -> pages of (rows - 1) options with a pager that wraps past the end", () => {
    const first = processMenuLayout(options, 4, 0);
    expect(first.visible.map((option) => option.name)).toEqual(["a1", "b2", "c3"]);
    expect(first.hiddenCount).toBe(3);
    expect(first.pageCount).toBe(2);
    const second = processMenuLayout(options, 4, 1);
    expect(second.visible.map((option) => option.name)).toEqual(["d4", "e5", "f6"]);
    // Wrapping: one past the last page is the first page again — no page strands the operator.
    expect(processMenuLayout(options, 4, 2).visible.map((option) => option.name)).toEqual(["a1", "b2", "c3"]);
  });

  test("union of all pages is every option exactly once", () => {
    const layout = processMenuLayout(options, 3, 0);
    const seen: string[] = [];
    for (let page = 0; page < layout.pageCount; page++) {
      seen.push(...processMenuLayout(options, 3, page).visible.map((option) => option.name));
    }
    expect(seen.sort()).toEqual(options.map((option) => option.name).sort());
  });

  test("row budget tiers follow pane height and never go below one option row", () => {
    expect(processMenuRowBudget(44)).toBe(10);
    expect(processMenuRowBudget(30)).toBe(8);
    expect(processMenuRowBudget(24)).toBe(6);
    expect(processMenuRowBudget(12)).toBe(4);
    expect(processMenuLayout(options, 0, 0).visible.length).toBeGreaterThanOrEqual(1);
  });
});
