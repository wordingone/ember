// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { describe, expect, test } from "bun:test";
import {
  OPERATOR_GRAPH_CARD_MAX_HEIGHT,
  operatorGraphGridColumns,
  renderOperatorGraphCardRows,
  OperatorSurfacePane,
  operatorControlLabel,
  operatorGraphCardColor,
  operatorGraphCardLayout,
  renderOperatorGraphCard,
} from "./operator-surface-pane.ts";

function collectElements(node: any, predicate: (element: any) => boolean, found: any[] = []): any[] {
  if (!node || typeof node !== "object") return found;
  if (predicate(node)) found.push(node);
  const children = node.props?.children;
  for (const child of Array.isArray(children) ? children : [children]) collectElements(child, predicate, found);
  return found;
}
function collectText(node: any): string[] {
  if (typeof node === "string") return [node];
  if (Array.isArray(node)) return node.flatMap(collectText);
  if (node && typeof node === "object") return collectText(node.props?.children);
  return [];
}

describe("#894 responsive contained cockpit charts", () => {
  test("cards consume responsive height but never grow past the legibility cap", () => {
    expect(operatorGraphCardLayout(6, 60)).toEqual({
      cardHeight: OPERATOR_GRAPH_CARD_MAX_HEIGHT,
      visibleCardCount: 6,
      hiddenCardCount: 0,
    });
    expect(operatorGraphCardLayout(6, 18)).toEqual({
      cardHeight: 3,
      visibleCardCount: 6,
      hiddenCardCount: 0,
    });
    expect(operatorGraphCardLayout(10, 13)).toEqual({
      cardHeight: 3,
      visibleCardCount: 4,
      hiddenCardCount: 6,
    });
    expect(operatorGraphCardLayout(10, 12)).toEqual({ cardHeight: 3, visibleCardCount: 3, hiddenCardCount: 7 });
    expect(OPERATOR_GRAPH_CARD_MAX_HEIGHT).toBeLessThanOrEqual(5);
  });

  test("wide panes keep every independently colored graph in one bounded column", () => {
    expect(operatorGraphGridColumns(64)).toBe(1);
    expect(operatorGraphGridColumns(160)).toBe(1);
    const cards = [
      { id: "loss" as const, title: "LOSS", values: [2, 1], unit: "" },
      { id: "tokens" as const, title: "TOKENS/S", values: [100, 120], unit: "tok/s" },
      { id: "energy" as const, title: "ENERGY", values: [3, 4], unit: "J" },
      { id: "gpu" as const, title: "GPU", values: [40, 50], unit: "%" },
    ];
    const rendered = renderOperatorGraphCardRows(cards, 96, 12);
    expect(rendered.layout).toEqual({ cardHeight: 3, visibleCardCount: 4, hiddenCardCount: 0 });
    expect(rendered.rows).toHaveLength(4);
    expect(rendered.rows[0]!.segments.map((segment) => segment.text).join(" ")).toContain("1.00");
    expect(rendered.rows[1]!.segments.map((segment) => segment.text).join(" ")).toContain("120.00 tok/s");
    expect(rendered.rows.every((row) => row.segments.filter((segment) => segment.text.trim()).length === 1)).toBe(true);
    expect(rendered.rows.every((row) => row.segments.reduce((sum, segment) => sum + segment.text.length, 0) === 94)).toBe(true);
  });

  test("card content excludes hand-built border glyphs and retains current/min/max context", () => {
    const lines = renderOperatorGraphCard("HOST RAM", [10, 12, 11, 15, 14], "GiB", 48, 4);
    expect(lines).toHaveLength(2);
    expect(lines.every((line) => line.length === 46)).toBe(true);
    expect(lines.every((line) => !line.startsWith("+") && !line.endsWith("+") && !line.startsWith("|") && !line.endsWith("|"))).toBe(true);
    expect(lines.join("\n")).toContain("14.00 GiB");
    expect(lines.join("\n")).toContain("min 10.00");
    expect(lines.join("\n")).toContain("max 15.00");
  });

  test("unbound and unavailable cards remain explicit inside the same boundary", () => {
    expect(renderOperatorGraphCard("GPU", undefined, "%", 24, 3).join("\n")).toContain("SOURCE UNBOUND");
    expect(renderOperatorGraphCard("GPU", [null, null], "%", 24, 3, "nvidia-smi unavailable").join("\n")).toContain("nvidia-smi");
  });

  test("metric identity has a stable non-gray color and control labels are plain", () => {
    const ids = ["memory", "ram", "vram", "cpu", "gpu", "disk", "loss", "tokens", "learning-rate", "energy"] as const;
    const colors = ids.map((id) => operatorGraphCardColor(id));
    expect(new Set(colors).size).toBeGreaterThanOrEqual(5);
    expect(colors.every((color) => color !== "gray")).toBe(true);
    expect(["START", "PAUSE", "RESUME", "RESTART"].map((action) => operatorControlLabel(action as any))).toEqual([
      "[START]",
      "[PAUSE]",
      "[RESUME]",
      "[RESTART]",
    ]);
  });
  test("production pane renders bounded colored cards rather than an unbounded gray stream", () => {
    const telemetry = {
      recentEvents: [
        { ts: "2026-07-30T12:00:00.000Z", kind: "train_step", source: "journal", payload: { run_id: "run-1", step: 1, loss: 2, tokens_per_second: 100, learning_rate: 0.001 } },
        { ts: "2026-07-30T12:00:01.000Z", kind: "train_step", source: "journal", payload: { run_id: "run-1", step: 2, loss: 1, tokens_per_second: 120, learning_rate: 0.0009 } },
      ],
    } as any;
    const series = (unit: string, values: Array<number | null>) => ({ unit, values });
    const host = {
      memory: series("GiB", [0.3, 0.4]),
      ram: series("GiB", [10, 12]),
      vram: series("GiB", [4, 5]),
      cpu: series("%", [20, 30]),
      gpu: series("%", [40, 50]),
      disk: series("%", [60, 61]),
    } as any;
    const element = OperatorSurfacePane({
      telemetry,
      activityLines: [],
      host,
      width: 60,
      height: 36,
      terminalColumns: 60,
      terminalRows: 36,
      nowMs: Date.parse("2026-07-30T12:00:02.000Z"),
    });
    const cardNodes = collectElements(element, (child) => child.props?.borderTitle !== undefined);
    expect(cardNodes.length).toBe(10);
    expect(cardNodes.every((child) => child.props.borderStyle === "single")).toBe(true);
    expect(cardNodes.every((child) => child.props.borderColor !== "gray")).toBe(true);
    expect(cardNodes.map((child) => child.props.borderTitle)).toContain("LOSS");
  });

  test("constrained production pane reports whole hidden cards instead of clipping middle rows", () => {
    const element = OperatorSurfacePane({
      telemetry: { recentEvents: [] } as any,
      activityLines: [],
      host: {
        memory: { unit: "GiB", values: [0.3] }, ram: { unit: "GiB", values: [10] },
        vram: { unit: "GiB", values: [4] }, cpu: { unit: "%", values: [20] },
        gpu: { unit: "%", values: [40] }, disk: { unit: "%", values: [60] },
      } as any,
      width: 60,
      height: 16,
      terminalColumns: 60,
      terminalRows: 16,
    });
    const rows = collectText(element);
    expect(rows.some((row: string) => row.includes("more charts"))).toBe(true);
    expect(rows.every((row: string) => row.length <= 56)).toBe(true);
  });
});
