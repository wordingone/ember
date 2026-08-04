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
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../ink/rendering-pipeline.ts";
import { CommandBarPane, commandBarMaxRows } from "./command-bar-pane.ts";
import type { CommandButton, CommandButtonActivation } from "../services/command-buttons.ts";
import { getCommands, resetCommandRegistryForTests, setCommandRegistryDeps } from "../command-registry.ts";
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
        expect(text).toContain(`[/${command.name}]`);
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
      expect(lines.join("\n")).toContain("[/brand-new-command]");
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
        const openings = joined.split(`[/${command.name.slice(0, 3)}`).length - 1;
        if (openings > 0) expect(joined).toContain(`[/${command.name}]`);
      }
      for (const line of lines) expect(line.length).toBeLessThanOrEqual(width);
    }
  });

  test("commandBarMaxRows never crowds a short terminal", () => {
    expect(commandBarMaxRows(20)).toBe(1);
    expect(commandBarMaxRows(30)).toBe(2);
    expect(commandBarMaxRows(44)).toBe(3);
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
    expect(targets.map((t) => t.label)).toEqual(["[/verify]", "[/admit]", "[/train]"]);
    for (const target of targets) target.onClick?.();
    expect(seen.map((s) => s.activation.kind)).toEqual(["dispatch", "prefill", "rejected"]);
    expect(seen[0]!.activation).toEqual({ kind: "dispatch", text: "/verify" });
    expect(seen[1]!.activation).toMatchObject({ text: "/admit " });
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

  test("the overflow disclosure is NOT clickable — only real commands are", () => {
    const commands = ["one", "two", "three", "four", "five", "six", "seven", "eight"].map((n) => cmd(n));
    const rendered = CommandBarPane({ commands, width: 24, maxRows: 1, onActivate: () => {} });
    const labels = clickTargets(rendered).map((t) => t.label);
    expect(labels.every((label) => label.startsWith("[/"))).toBe(true);
    expect(allText(rendered)).toContain("more");
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
