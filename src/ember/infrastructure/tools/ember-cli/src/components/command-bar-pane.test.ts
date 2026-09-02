// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// components/command-bar-pane.test.ts — rendering + hit-surface contract for #1370.
//
// Two things are proved here that the pure-service tests cannot: that every registry command
// actually REACHES the frame (a button model nothing renders is the same defect as no button),
// and that each rendered button carries its own click handler producing its own activation —
// the mouse hit surface, not merely the layout.

import { describe, expect, test } from "bun:test";
import React from "react";
import { mountInk } from "../ink/reconciler.ts";
import { Box } from "../ink/components.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../../../../../../../tools/ember-cli/src/ink/rendering-pipeline.ts";
import { CommandBarPane, commandBarMaxRows } from "./command-bar-pane.ts";
import {
  buildCommandButtons,
  commandBarPages,
  resolveCommandBarPage,
  type CommandButton,
  type CommandButtonActivation,
} from "../services/command-buttons.ts";
import { getCommands, resetCommandRegistryForTests, setCommandRegistryDeps } from "../../../../../../../tools/ember-cli/src/command-registry.ts";
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

interface ClickTarget {
  label: string;
  onClick?: () => void;
  onMouseEnter?: () => void;
  onMouseLeave?: () => void;
}

/** Walks the returned element tree and collects every Box that carries a click handler together
 *  with the label text it wraps — i.e. the real mouse hit surface, as rendered. */
function clickTargets(node: unknown): ClickTarget[] {
  if (!node || typeof node !== "object") return [];
  if (Array.isArray(node)) return node.flatMap(clickTargets);
  const props = (node as { props?: Record<string, unknown> }).props;
  if (!props) return [];
  const children = props["children"];
  if (typeof props["onClick"] === "function" || typeof props["onMouseEnter"] === "function") {
    return [{
      label: textOf(children),
      onClick: props["onClick"] as () => void,
      onMouseEnter: props["onMouseEnter"] as (() => void) | undefined,
      onMouseLeave: props["onMouseLeave"] as (() => void) | undefined,
    }];
  }
  return clickTargets(children);
}

function textOf(node: unknown): string {
  if (typeof node === "string") return node;
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (node && typeof node === "object" && "props" in node) {
    return textOf((node as { props?: { children?: unknown } }).props?.children);
  }
  return "";
}

function allText(node: unknown): string {
  if (typeof node === "string") return node;
  if (Array.isArray(node)) return node.map(allText).join(" ");
  if (node && typeof node === "object" && "props" in node) {
    return allText((node as { props?: { children?: unknown } }).props?.children);
  }
  return "";
}

/** Labels of the command buttons rendered on this page, pager excluded. */
function labelsOf(node: unknown): string[] {
  return clickTargets(node).map((t) => t.label).filter((label) => /^\[[a-z0-9-]+\]$/.test(label));
}

/**
 * Walks the bar the way an operator with only a mouse would: click every button on the page,
 * then click the pager, and repeat. Nothing here reads the layout to find commands — reachability
 * is proved by the clicks themselves, which is the only thing issue #1370 actually asks for.
 */
function pageThroughByClicking(
  commands: RegistryCommand[],
  width: number,
  maxRows: number,
): { reached: string[]; finalPage: number; pageCount: number } {
  const reached: string[] = [];
  const pageCount = commandBarPages(buildCommandButtons(commands), width, maxRows).length;
  let page = 0;
  for (let step = 0; step < pageCount; step++) {
    let requested: number | undefined;
    const rendered = CommandBarPane({
      commands,
      width,
      maxRows,
      page,
      onActivate: (_activation, button) => reached.push(button.name),
      onPageChange: (next) => { requested = next; },
    });
    for (const target of clickTargets(rendered)) target.onClick?.();
    if (requested === undefined) break;
    page = requested;
  }
  return { reached, finalPage: resolveCommandBarPage(page, pageCount), pageCount };
}

async function renderToLines(
  element: React.ReactElement,
  columns: number,
  rows: number,
): Promise<string[]> {
  let raw = "";
  const root = React.createElement(
    Box,
    { flexDirection: "column", width: columns, height: rows },
    element,
  );
  const handle = mountInk(root, {
    stream: { write(chunk: string) { raw += chunk; } },
    stdout: { columns, rows },
  });
  for (let flush = 0; flush < 5; flush++) {
    await new Promise<void>((resolve) => setTimeout(resolve, 20));
  }
  // Parse BEFORE unmount: unmount emits its own screen-clearing pass, which would blank every
  // cell the frame is being asserted against.
  const frame = buildFrame(columns, rows);
  parseRenderedIntoFrame(raw, frame, new StylePool());
  handle.unmount();
  return frame.cells.map((line) => line.map((cell) => cell?.char ?? " ").join(""));
}

describe("CommandBarPane rendering", () => {
  test("renders a button for every command in the LIVE registry it is handed", async () => {
    resetCommandRegistryForTests();
    try {
      const commands = await getCommands(process.cwd());
      const rendered = CommandBarPane({ commands, width: 200, maxRows: 12 });
      const text = allText(rendered);
      for (const command of commands) {
        expect(text).toContain(`[${command.name}]`);
      }
    } finally {
      resetCommandRegistryForTests();
    }
  });

  test("a command registered at test time reaches the frame with no change to this component", async () => {
    resetCommandRegistryForTests();
    try {
      setCommandRegistryDeps({ getBuiltinCommands: () => [cmd("brand-new-command")] });
      const commands = await getCommands("/tmp/command-bar-growth");
      const lines = await renderToLines(
        React.createElement(CommandBarPane, { commands, width: 60, maxRows: 2 }),
        60,
        6,
      );
      expect(lines.join("\n")).toContain("[brand-new-command]");
    } finally {
      resetCommandRegistryForTests();
    }
  });

  test("an empty registry renders nothing at all rather than an empty bordered husk", () => {
    expect(CommandBarPane({ commands: [], width: 80 })).toBeNull();
  });

  test("width sweep: no button label is split or clipped without its own row", async () => {
    const commands = ["watch", "model", "train", "verify", "custody"].map((n) => cmd(n));
    for (const width of [24, 40, 60, 80, 120, 160]) {
      const lines = await renderToLines(
        React.createElement(CommandBarPane, { commands, width, maxRows: 3 }),
        width,
        8,
      );
      const joined = lines.join("\n");
      // Every label that appears at all appears WHOLE — a half-written "[/verif" would mean the
      // packer let a label cross the pane edge.
      for (const command of commands) {
        const openings = joined.split(`[${command.name.slice(0, 3)}`).length - 1;
        if (openings > 0) expect(joined).toContain(`[${command.name}]`);
      }
      for (const line of lines) expect(line.length).toBeLessThanOrEqual(width);
    }
  });

  test("commandBarMaxRows never crowds a short terminal", () => {
    // #1399 raised every tier: the bar left the transcript column for the live-run pane, and
    // it now spends a row per group caption.
    expect(commandBarMaxRows(20)).toBe(2);
    expect(commandBarMaxRows(26)).toBe(4);
    expect(commandBarMaxRows(30)).toBe(5);
    expect(commandBarMaxRows(44)).toBe(6);
  });

  test("the notice row renders the reason it was handed, bounded to the pane width", async () => {
    const lines = await renderToLines(
      React.createElement(CommandBarPane, {
        commands: [cmd("train")],
        width: 40,
        maxRows: 1,
        notice: "/train is not available right now",
      }),
      40,
      6,
    );
    expect(lines.join("\n")).toContain("/train is not available right now");
  });
});

describe("CommandBarPane hit surface", () => {
  test("every rendered button carries its own click handler and its own activation", () => {
    const seen: Array<{ activation: CommandButtonActivation; button: CommandButton }> = [];
    const rendered = CommandBarPane({
      commands: [
        cmd("verify"),
        cmd("admit", { argumentHint: "--workspace <path>" }),
        cmd("train", { isEnabled: () => false }),
      ],
      width: 120,
      maxRows: 3,
      onActivate: (activation, button) => seen.push({ activation, button }),
    });
    const targets = clickTargets(rendered);
    // Captions carry no click handler, so the hit surface is exactly the three buttons — and
    // every label that reaches it carries no slash (#1399).
    // Order is the GROUPED order (#1399): verify and train are `launch`, admit is `govern`.
    expect(targets.map((t) => t.label)).toEqual(["[verify]", "[train]", "[admit]"]);
    for (const target of targets) target.onClick?.();
    expect(seen.map((s) => s.activation.kind)).toEqual(["dispatch", "rejected", "prefill"]);
    expect(seen[0]!.activation).toEqual({ kind: "dispatch", text: "/verify" });
    expect(seen[2]!.activation).toMatchObject({ text: "/admit " });
  });

  test("a disabled command keeps its handler so the click can say why", () => {
    const seen: CommandButtonActivation[] = [];
    const rendered = CommandBarPane({
      commands: [cmd("train", { isEnabled: () => false })],
      width: 80,
      onActivate: (activation) => seen.push(activation),
    });
    clickTargets(rendered)[0]!.onClick?.();
    expect(seen).toHaveLength(1);
    expect(seen[0]!.kind).toBe("rejected");
  });

  test("hover reports a command name and clears it, and touches nothing else", () => {
    const hovers: Array<string | undefined> = [];
    const rendered = CommandBarPane({
      commands: [cmd("verify")],
      width: 80,
      onHoverCommand: (name) => hovers.push(name),
    });
    const target = clickTargets(rendered)[0]!;
    target.onMouseEnter?.();
    target.onMouseLeave?.();
    expect(hovers).toEqual(["verify", undefined]);
  });

  test("the pager IS clickable and advances the page — the overflow marker is not a dead end", () => {
    const commands = ["one", "two", "three", "four", "five", "six", "seven", "eight"].map((n) => cmd(n));
    let requested: number | undefined;
    const rendered = CommandBarPane({
      commands,
      width: 24,
      maxRows: 1,
      onActivate: () => {},
      onPageChange: (page) => { requested = page; },
    });
    const pager = clickTargets(rendered).find((t) => !/^\[[a-z0-9-]+\]$/.test(t.label));
    expect(pager).toBeDefined();
    expect(pager!.label).toContain("more");
    pager!.onClick?.();
    expect(requested).toBe(1);
  });

  test("a second page shows the commands the first page could not, and the pager wraps home", () => {
    const commands = ["one", "two", "three", "four", "five", "six", "seven", "eight"].map((n) => cmd(n));
    const first = labelsOf(CommandBarPane({ commands, width: 24, maxRows: 1, onActivate: () => {} }));
    const second = labelsOf(CommandBarPane({ commands, width: 24, maxRows: 1, page: 1, onActivate: () => {} }));
    expect(second.length).toBeGreaterThan(0);
    // Disjoint: paging shows NEW commands rather than re-showing the same ones.
    expect(second.some((label) => first.includes(label))).toBe(false);

    // From the last page the pager returns to the first, so no page is a trap.
    const pageCount = commandBarPages(buildCommandButtons(commands), 24, 1).length;
    let requested: number | undefined;
    const last = CommandBarPane({
      commands,
      width: 24,
      maxRows: 1,
      page: pageCount - 1,
      onActivate: () => {},
      onPageChange: (page) => { requested = page; },
    });
    clickTargets(last).find((t) => !/^\[[a-z0-9-]+\]$/.test(t.label))!.onClick?.();
    expect(resolveCommandBarPage(requested!, pageCount)).toBe(0);
  });

  test("every registered command is click-reachable by paging at every terminal size", () => {
    const commands = ["watch", "model", "train", "verify", "admit", "designate", "goal",
      "custody", "benchmark", "spine", "status", "plan", "review", "export"].map((n) => cmd(n));
    for (const [width, rows] of [[40, 24], [60, 20], [80, 24], [100, 30], [140, 40]] as const) {
      const walk = pageThroughByClicking(commands, width, commandBarMaxRows(rows));
      expect(new Set(walk.reached)).toEqual(new Set(commands.map((c) => c.name)));
      // The walk was driven entirely by clicking the pager, and it landed back on page 0.
      expect(walk.finalPage).toBe(0);
    }
  });

  test("an out-of-range remembered page never blanks the bar — a shrink wraps onto a real page", () => {
    const commands = ["one", "two", "three", "four", "five", "six"].map((n) => cmd(n));
    // Page 5 was valid at a narrow width; the same index arriving at a wide one must still render.
    for (const page of [5, 99, -1]) {
      const labels = labelsOf(CommandBarPane({ commands, width: 200, maxRows: 3, page, onActivate: () => {} }));
      expect(labels).toEqual(commands.map((c) => `[${c.name}]`));
    }
  });

  test("the pane exposes no focus props — a click cannot move keyboard focus", () => {
    const rendered = CommandBarPane({ commands: [cmd("verify")], width: 80, onActivate: () => {} });
    const collectPropNames = (node: unknown): string[] => {
      if (!node || typeof node !== "object") return [];
      if (Array.isArray(node)) return node.flatMap(collectPropNames);
      const props = (node as { props?: Record<string, unknown> }).props;
      if (!props) return [];
      return [...Object.keys(props), ...collectPropNames(props["children"])];
    };
    const names = collectPropNames(rendered);
    expect(names.some((name) => /focus/i.test(name))).toBe(false);
  });
});
