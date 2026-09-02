// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// components/operator-surface-pane-process-select.test.ts — the rendered half of #1475: the
// SELECT PROCESS button replaces the gray "run control" caption, its dropdown dialog toggles
// and selects, START renders its stage machine (unarmed / armed-highlight / confirm), and the
// command bar keeps only the subordinate inspect/govern groups. Element-tree tests drive the
// exact onClick/onMouseEnter props the SGR pipeline dispatches into (the full byte path is
// covered by screens/repl-operator-control-wiring.test.ts); the width sweep mounts the real
// Ink viewport per the legible-at-any-size bar.
import { describe, expect, test } from "bun:test";
import React from "react";
import { mountInk } from "../ink/reconciler.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../ink/rendering-pipeline.ts";
import { OperatorSurfacePane, SELECT_PROCESS_TOGGLE_HOVER } from "./operator-surface-pane.ts";
import type { TelemetryState } from "../services/telemetry-watch.ts";
import type { RegistryCommand } from "../types/command-types.ts";

function telemetry(overrides: Partial<TelemetryState> = {}): TelemetryState {
  return { recentEvents: [], ...overrides };
}

function cmd(name: string, overrides: Partial<RegistryCommand> = {}): RegistryCommand {
  return {
    name,
    description: `${name} description`,
    isEnabled: () => true,
    execute: async () => {},
    ...overrides,
  };
}

const REGISTRY = [
  cmd("observatory"), cmd("watch"), cmd("finetune"), cmd("model"), cmd("train"),
  cmd("verify"), cmd("verify-training"), cmd("admit"), cmd("designate"), cmd("goal"),
  cmd("custody"), cmd("benchmark"), cmd("spine"), cmd("resume"),
];

interface PaneOverrides {
  [key: string]: unknown;
}

function pane(overrides: PaneOverrides = {}): React.ReactElement {
  return OperatorSurfacePane({
    telemetry: telemetry(),
    activityLines: [],
    commands: REGISTRY,
    width: 60, height: 30, terminalColumns: 60, terminalRows: 30,
    nowMs: Date.parse("2026-08-05T00:00:02.000Z"),
    ...overrides,
  } as never);
}

function collectText(node: unknown): string[] {
  if (typeof node === "string") return [node];
  if (Array.isArray(node)) return node.flatMap(collectText);
  if (node && typeof node === "object" && "props" in node) {
    return collectText((node as { props?: { children?: unknown } }).props?.children);
  }
  return [];
}

function collectElements(node: any, predicate: (element: any) => boolean, found: any[] = []): any[] {
  if (!node || typeof node !== "object") return found;
  if (predicate(node)) found.push(node);
  const children = node.props?.children;
  for (const child of Array.isArray(children) ? children : [children]) collectElements(child, predicate, found);
  return found;
}

/** The element whose own subtree renders exactly `text` as its Text content. */
function elementWithText(root: any, text: string): any {
  return collectElements(root, (element) => {
    const children = element.props?.children;
    return typeof element.props?.onClick !== "undefined" && collectText(children).join("").includes(text);
  })[0];
}

function bodyChildren(element: any): any[] {
  return (element.props.children.props.children as any[]).filter(Boolean);
}

describe("#1475 SELECT PROCESS replaces the run-control caption", () => {
  test("the button renders directly under the status row and the caption is gone", () => {
    const element = pane();
    const keys = bodyChildren(element).map((child) => child.key);
    expect(keys.indexOf("select-process")).toBe(keys.indexOf("status-row") + 1);
    expect(collectText(element).join("\n")).not.toContain("run control");
    expect(collectText(element).join("\n")).toContain("[SELECT PROCESS ▾]");
  });

  test("the command bar keeps only the subordinate inspect/govern groups — no launch cluster", async () => {
    // Mounted for real: CommandBarPane is a nested component, so its text only exists in a
    // rendered frame, not in the unexpanded element tree.
    const chunks: string[] = [];
    const element = React.createElement(OperatorSurfacePane, {
      telemetry: telemetry(),
      activityLines: [],
      commands: REGISTRY,
      width: 60, height: 40, terminalColumns: 60, terminalRows: 40,
      commandBarMaxRows: 6,
      nowMs: Date.parse("2026-08-05T00:00:02.000Z"),
    } as never);
    const handle = mountInk(element, { stream: { write(s: string) { chunks.push(s); } }, stdout: { columns: 60, rows: 40 } });
    await new Promise<void>((resolve) => setTimeout(resolve, 10));
    const frame = buildFrame(60, 40);
    parseRenderedIntoFrame(chunks.join(""), frame, new StylePool());
    handle.unmount();
    const text = frame.cells.map((row) => row.map((cell) => cell?.char ?? " ").join("")).join("\n");
    expect(text).toContain("[observatory]");
    expect(text).toContain("[admit]");
    expect(text).not.toContain("[train]");
    expect(text).not.toContain("[finetune]");
    expect(text).not.toContain("[verify]");
    expect(text).not.toContain("[resume]");
    expect(text).not.toContain("launch");
  });

  test("without a registry the pane is exactly the legacy pane: no select button, no menu", () => {
    const element = pane({ commands: undefined });
    const keys = bodyChildren(element).map((child) => child.key);
    expect(keys).not.toContain("select-process");
    expect(keys).not.toContain("process-menu");
  });
});

describe("#1475 dropdown dialog", () => {
  test("clicking the toggle fires onProcessMenuToggle; closed means no menu in the tree", () => {
    const toggles: number[] = [];
    const closed = pane({ onProcessMenuToggle: () => toggles.push(1) });
    expect(bodyChildren(closed).map((child) => child.key)).not.toContain("process-menu");
    const toggle = elementWithText(closed, "[SELECT PROCESS ▾]");
    expect(typeof toggle.props.onClick).toBe("function");
    toggle.props.onClick();
    expect(toggles).toEqual([1]);
  });

  test("open: one clickable row per process in registry order, rendered where the button is", () => {
    const selections: string[] = [];
    const element = pane({ processMenuOpen: true, onProcessSelect: (name: string) => selections.push(name) });
    const keys = bodyChildren(element).map((child) => child.key);
    expect(keys.indexOf("process-menu")).toBe(keys.indexOf("select-process") + 1);
    const menu = bodyChildren(element).find((child) => child.key === "process-menu");
    expect(menu.props.borderTitle).toBe("SELECT PROCESS");
    const optionKeys = (menu.props.children as any[]).filter(Boolean).map((child: any) => child.key);
    expect(optionKeys).toEqual([
      "process-option-finetune", "process-option-train", "process-option-verify",
      "process-option-verify-training", "process-option-benchmark", "process-option-resume",
    ]);
    const trainRow = (menu.props.children as any[]).find((child: any) => child?.key === "process-option-train");
    trainRow.props.onClick();
    expect(selections).toEqual(["train"]);
  });

  test("a height-tight pane pages instead of dropping options, and the pager is clickable", () => {
    const pages: number[] = [];
    // height 12 -> processMenuRowBudget 4 -> 3 options + pager per page.
    const element = pane({ height: 12, terminalRows: 12, processMenuOpen: true, onProcessMenuPageChange: (page: number) => pages.push(page) });
    const menu = bodyChildren(element).find((child) => child.key === "process-menu");
    const rows = (menu.props.children as any[]).filter(Boolean);
    expect(rows.map((row: any) => row.key)).toEqual([
      "process-option-finetune", "process-option-train", "process-option-verify", "process-menu-pager",
    ]);
    const pager = rows[rows.length - 1]!;
    expect(collectText(pager).join("")).toContain("+3 more");
    pager.props.onClick();
    expect(pages).toEqual([1]);
  });

  test("the selection is marked with the ❯ vocabulary and the toggle re-labels", () => {
    const element = pane({ processMenuOpen: true, selectedProcess: "train" });
    const text = collectText(element).join("\n");
    expect(text).toContain("❯ train");
    expect(text).toContain("[PROCESS: train ▾]");
    expect(text).not.toContain("[SELECT PROCESS ▾]");
  });

  test("hover rides onMouseEnter/onMouseLeave for both the toggle and the option rows", () => {
    const hovers: Array<string | undefined> = [];
    const element = pane({
      processMenuOpen: true,
      onProcessMenuToggle: () => {},
      onHoverProcess: (name: string | undefined) => hovers.push(name),
    });
    const toggle = elementWithText(element, "[SELECT PROCESS ▾]");
    toggle.props.onMouseEnter();
    toggle.props.onMouseLeave();
    const menu = bodyChildren(element).find((child) => child.key === "process-menu");
    const trainRow = (menu.props.children as any[]).find((child: any) => child?.key === "process-option-train");
    trainRow.props.onMouseEnter();
    expect(hovers).toEqual([SELECT_PROCESS_TOGGLE_HOVER, undefined, "train"]);
  });
});

describe("#1475 START stage machine rendering", () => {
  function startTextElement(element: any): any {
    const controls = bodyChildren(element).find((child) => child.key === "controls");
    const flat = collectElements(controls, (candidate) => {
      const text = candidate.props?.children;
      return typeof text === "string" && (text.includes("[START]") || text.includes("[CONFIRM START]"));
    });
    return flat[0];
  }

  test("unarmed: gray, not highlighted, but still clickable so the click can say why", () => {
    const calls: string[] = [];
    const element = pane({ onControl: (action: string) => calls.push(action) });
    const startText = startTextElement(element);
    expect(startText.props.color).toBe("gray");
    expect(startText.props.inverse).toBeFalsy();
    const controls = bodyChildren(element).find((child) => child.key === "controls");
    const startBox = collectElements(controls, (candidate) =>
      typeof candidate.props?.onClick === "function" && collectText(candidate).join("").includes("[START]"),
    )[0];
    startBox.props.onClick();
    expect(calls).toEqual(["START"]);
  });

  test("armed: selecting a process HIGHLIGHTS START (green, bold, inverse)", () => {
    const startText = startTextElement(pane({ selectedProcess: "train" }));
    expect(startText.props.color).toBe("green");
    expect(startText.props.bold).toBe(true);
    expect(startText.props.inverse).toBe(true);
    expect(startText.props.children).toContain("[START]");
  });

  test("confirm: an outstanding offer for the selected process re-labels the button", () => {
    const startText = startTextElement(pane({
      selectedProcess: "train",
      processOffer: { process: "train", offerId: "train-9-zz" },
    }));
    expect(startText.props.children).toContain("[CONFIRM START]");
    expect(startText.props.color).toBe("yellow");
    expect(startText.props.inverse).toBe(true);
  });

  test("an offer for a different process leaves the armed label alone", () => {
    const startText = startTextElement(pane({
      selectedProcess: "verify",
      processOffer: { process: "train", offerId: "train-9-zz" },
    }));
    expect(startText.props.children).toContain("[START]");
    expect(startText.props.children).not.toContain("CONFIRM");
  });
});

describe("#1475 legibility width sweep", () => {
  async function mountAt(width: number, height: number, overrides: PaneOverrides = {}): Promise<string[]> {
    const chunks: string[] = [];
    const element = React.createElement(OperatorSurfacePane, {
      telemetry: telemetry(),
      activityLines: [],
      commands: REGISTRY,
      width, height, terminalColumns: width, terminalRows: height,
      nowMs: Date.parse("2026-08-05T00:00:02.000Z"),
      ...overrides,
    } as never);
    const handle = mountInk(element, { stream: { write(s: string) { chunks.push(s); } }, stdout: { columns: width, rows: height } });
    await new Promise<void>((resolve) => setTimeout(resolve, 10));
    const frame = buildFrame(width, height);
    parseRenderedIntoFrame(chunks.join(""), frame, new StylePool());
    handle.unmount();
    return frame.cells.map((row) => row.map((cell) => cell?.char ?? " ").join(""));
  }

  test("the toggle renders IN FULL at 30, 40, and 60 columns, closed and open", async () => {
    for (const width of [30, 40, 60]) {
      const closed = await mountAt(width, 30);
      expect(closed.every((row) => row.length === width)).toBe(true);
      expect(closed.some((row) => row.includes("[SELECT PROCESS ▾]"))).toBe(true);
      const open = await mountAt(width, 30, { processMenuOpen: true });
      // Every option name is present, whole, on its own dialog row.
      for (const name of ["finetune", "train", "verify-training", "resume"]) {
        expect(open.some((row) => row.includes(` ${name}`))).toBe(true);
      }
    }
  });

  test("armed and confirm labels never truncate at a narrow pane — controls wrap, not clip", async () => {
    const rows = await mountAt(26, 30, {
      selectedProcess: "train",
      processOffer: { process: "train", offerId: "train-1-x" },
    });
    expect(rows.some((row) => row.includes("[CONFIRM START]"))).toBe(true);
    for (const label of ["[PAUSE]", "[RESUME]", "[RESTART]"]) {
      expect(rows.some((row) => row.includes(label))).toBe(true);
    }
  });
});
