// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// tools/computer-use.ts -- Windows computer use for open-weights models.
//
// One tool, many actions, built on PowerShell + .NET (UI Automation, GDI+,
// user32 PrintWindow). Everything except the opt-in real-input actions is
// non-intrusive: no mouse movement, no keystrokes, no focus change.
//   list_windows / screenshot / ui_tree      -- observe
//   invoke / set_value / toggle / select / expand / scroll  -- UIA patterns
//   open_app / close_window                  -- lifecycle (WM_CLOSE only, only
//                                               for windows this tool opened)
//   type_text / click_at                     -- real SendInput; OFF unless
//                                               EMBER_COMPUTER_REAL_INPUT=1 AND
//                                               the per-call permission is granted

import { spawn } from "child_process";
import { createHash } from "crypto";
import { mkdirSync, writeFileSync, existsSync, readFileSync } from "fs";
import { homedir, tmpdir } from "os";
import { join } from "path";
import { z } from "zod";
import { buildTool, type ToolUseContext } from "../core/tool-interface.ts";
import { COMPUTER_USE_PS_SCRIPT } from "./computer-use-ps.ts";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export const COMPUTER_ACTIONS = [
  "list_windows",
  "screenshot",
  "ui_tree",
  "invoke",
  "set_value",
  "toggle",
  "select",
  "expand",
  "scroll",
  "open_app",
  "close_window",
  "type_text",
  "click_at",
] as const;
export type ComputerAction = (typeof COMPUTER_ACTIONS)[number];

const REAL_INPUT_ACTIONS: ReadonlySet<string> = new Set(["type_text", "click_at"]);

/** Raw JSON object the PowerShell payload prints. */
export interface PsResult {
  ok: boolean;
  kind?: string;
  error?: string;
  [key: string]: unknown;
}

export type PsRunner = (
  action: string,
  args: Record<string, unknown>,
  timeoutMs: number,
) => Promise<PsResult>;

export type ComputerOutput =
  | { type: "error"; error: string }
  | { type: "text"; text: string }
  | { type: "image"; text: string; path: string; mediaType: "image/png"; base64: string | null };

// ---------------------------------------------------------------------------
// PowerShell runner
// ---------------------------------------------------------------------------

const DEFAULT_TIMEOUT_MS = 30_000;
const MAX_TIMEOUT_MS = 120_000;

function ensureScriptFile(): string {
  const hash = createHash("sha256").update(COMPUTER_USE_PS_SCRIPT).digest("hex").slice(0, 12);
  const dir = join(tmpdir(), "ember-computer-use");
  const file = join(dir, `cu-${hash}.ps1`);
  if (!existsSync(file)) {
    mkdirSync(dir, { recursive: true });
    writeFileSync(file, COMPUTER_USE_PS_SCRIPT, "ascii");
  }
  return file;
}

/** Spawns powershell.exe on the payload script; one JSON object back. */
export const realPsRunner: PsRunner = (action, args, timeoutMs) =>
  new Promise<PsResult>((resolve) => {
    let scriptFile: string;
    try {
      scriptFile = ensureScriptFile();
    } catch (err) {
      resolve({ ok: false, kind: "setup_failed", error: `could not write the PowerShell payload: ${String(err)}` });
      return;
    }
    const child = spawn(
      "powershell.exe",
      ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", scriptFile],
      {
        windowsHide: true,
        stdio: ["ignore", "pipe", "pipe"],
        env: {
          ...process.env,
          EMBER_CU_ACTION: action,
          EMBER_CU_ARGS: JSON.stringify(args),
        },
      },
    );
    let stdout = "";
    let stderr = "";
    let settled = false;
    const done = (r: PsResult): void => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(r);
    };
    const timer = setTimeout(() => {
      // Our own child only (spawned just above); never a name-pattern kill.
      try {
        child.kill();
      } catch {
        /* already gone */
      }
      done({
        ok: false,
        kind: "timeout",
        error: `PowerShell call for "${action}" timed out after ${timeoutMs} ms and was stopped.${stderr ? ` stderr: ${stderr.trim().slice(0, 500)}` : ""}`,
      });
    }, timeoutMs);
    child.stdout.on("data", (d: Buffer) => {
      stdout += d.toString("utf8");
    });
    child.stderr.on("data", (d: Buffer) => {
      stderr += d.toString("utf8");
    });
    child.on("error", (err) => {
      done({ ok: false, kind: "spawn_failed", error: `could not start powershell.exe: ${err.message}` });
    });
    child.on("close", (code) => {
      const lines = stdout.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
      const last = lines[lines.length - 1];
      if (last !== undefined) {
        try {
          done(JSON.parse(last) as PsResult);
          return;
        } catch {
          /* fall through to the failure path */
        }
      }
      done({
        ok: false,
        kind: "powershell_failed",
        error: `powershell exited with code ${code}. stderr: ${(stderr.trim() || "(empty)").slice(0, 1500)}${stdout.trim() ? ` stdout: ${stdout.trim().slice(0, 500)}` : ""}`,
      });
    });
  });

let activeRunner: PsRunner = realPsRunner;

/** Test seam: replace the PowerShell runner (pass undefined to restore). */
export function setPsRunnerForTests(runner: PsRunner | undefined): void {
  activeRunner = runner ?? realPsRunner;
}

// ---------------------------------------------------------------------------
// Session state: windows this tool opened (close_window may only touch these)
// ---------------------------------------------------------------------------

const ownedHwnds = new Set<number>();
/** Pids of programs open_app launched (so their own popups/child windows count as owned). */
const ownedPids = new Set<number>();
/** Actions that change a window: only allowed on windows the Computer tool opened. */
const MUTATING_ACTIONS = new Set<ComputerAction>(["invoke", "set_value", "toggle", "select", "expand", "scroll", "close_window"]);

export function getOwnedHwndsForTests(): number[] {
  return [...ownedHwnds];
}
export function resetComputerSessionForTests(): void {
  ownedHwnds.clear();
  ownedPids.clear();
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function emberHome(): string {
  return process.env["EMBER_HOME"] || join(homedir(), ".ember");
}

function realInputEnabled(): boolean {
  return process.env["EMBER_COMPUTER_REAL_INPUT"] === "1";
}

function visionEnabled(): boolean {
  return process.env["EMBER_VISION"] === "1";
}

function fmtWindow(w: Record<string, unknown>): string {
  const b = Array.isArray(w["bounds"]) ? (w["bounds"] as number[]).join(",") : "?";
  const flags = [w["visible"] ? "visible" : "hidden", w["minimized"] ? "minimized" : ""]
    .filter(Boolean)
    .join(",");
  return `hwnd=${w["hwnd"]} pid=${w["pid"]} proc=${w["process"]} [${b}] ${flags} "${w["title"]}"`;
}

function err(error: string): ComputerOutput {
  return { type: "error", error };
}

function readPngBase64(path: string): string | null {
  try {
    return readFileSync(path).toString("base64");
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Core dispatch (exported for tests)
// ---------------------------------------------------------------------------

export interface ComputerInput {
  action: ComputerAction;
  hwnd?: number | undefined;
  window?: string | undefined;
  element?: string | undefined;
  automation_id?: string | undefined;
  name?: string | undefined;
  control_type?: string | undefined;
  index?: number | undefined;
  value?: string | undefined;
  text?: string | undefined;
  state?: string | undefined;
  direction?: string | undefined;
  amount?: number | undefined;
  depth?: number | undefined;
  max_nodes?: number | undefined;
  include_hidden?: boolean | undefined;
  exe?: string | undefined;
  args?: string | undefined;
  cwd?: string | undefined;
  wait_ms?: number | undefined;
  x?: number | undefined;
  y?: number | undefined;
  button?: string | undefined;
  timeout_ms?: number | undefined;
}

export async function runComputerAction(input: ComputerInput): Promise<ComputerOutput> {
  const action = input.action;
  if (process.platform !== "win32" && activeRunner === realPsRunner) {
    return err("The Computer tool only works on Windows (it drives UI Automation through PowerShell).");
  }
  if (REAL_INPUT_ACTIONS.has(action) && !realInputEnabled()) {
    return err(
      `${action} sends real keyboard/mouse input and is disabled. The operator must set EMBER_COMPUTER_REAL_INPUT=1. Use set_value / invoke / toggle (UI Automation) instead; they need no focus.`,
    );
  }
  const timeoutMs = Math.min(
    MAX_TIMEOUT_MS,
    Math.max(1000, input.timeout_ms ?? (action === "open_app" ? 45_000 : DEFAULT_TIMEOUT_MS)),
  );

  const args: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(input)) {
    if (k !== "action" && k !== "timeout_ms" && v !== undefined) args[k] = v;
  }

  let screenPath: string | undefined;
  if (action === "screenshot") {
    const dir = join(emberHome(), "screens");
    mkdirSync(dir, { recursive: true });
    screenPath = join(dir, `screen-${new Date().toISOString().replace(/[-:.TZ]/g, "").slice(0, 17)}-${Math.random().toString(36).slice(2, 6)}.png`);
    args["save_path"] = screenPath;
    args["max_width"] = 1280;
  }
  if (MUTATING_ACTIONS.has(action)) {
    args["owned"] = [...ownedHwnds];
    args["owned_pids"] = [...ownedPids];
    if (action !== "close_window" && ownedHwnds.size === 0 && ownedPids.size === 0) {
      return err(
        `[not_owned] Refusing ${action}: the Computer tool has not opened any window in this session, so there is nothing it may change. Use open_app first; list_windows, ui_tree and screenshot work on any window.`,
      );
    }
  }
  if (action === "close_window") {
    const h = input.hwnd;
    if (h === undefined && input.window === undefined) {
      return err("close_window needs hwnd (the one open_app returned).");
    }
  }

  const res = await activeRunner(action, args, timeoutMs);
  if (!res.ok) {
    const kind = res.kind ? `[${res.kind}] ` : "";
    return err(`${kind}${res.error ?? "unknown PowerShell error"}`);
  }

  switch (action) {
    case "list_windows": {
      const wins = (res["windows"] as Array<Record<string, unknown>> | undefined) ?? [];
      if (wins.length === 0) return { type: "text", text: "No windows found." };
      return { type: "text", text: `${wins.length} windows:\n${wins.map(fmtWindow).join("\n")}` };
    }
    case "ui_tree": {
      const w = res["window"] as Record<string, unknown>;
      return {
        type: "text",
        text: `UI tree of ${fmtWindow(w)} (${res["nodes"]} nodes). Format: ControlType "name" #automationId [x,y,w,h] patterns=... value="..."\n${res["tree"]}`,
      };
    }
    case "screenshot": {
      const path = String(res["path"] ?? screenPath);
      const w = res["width"];
      const h = res["height"];
      const ow = res["original_width"];
      const oh = res["original_height"];
      const note = res["note"] ? ` Note: ${res["note"]}` : "";
      const target = res["target"] === "window" ? fmtWindow(res["window"] as Record<string, unknown>) : "full screen";
      const text = `Screenshot of ${target}: ${w}x${h}px (captured ${ow}x${oh}), saved to ${path}.${note}`;
      if (!visionEnabled()) {
        return {
          type: "text",
          text: `${text} The loaded model has no vision projector, so the image was not attached; use ui_tree to read the UI.`,
        };
      }
      return { type: "image", text, path, mediaType: "image/png", base64: readPngBase64(path) };
    }
    case "open_app": {
      const w = res["window"] as Record<string, unknown> | undefined;
      if (!w) return err("open_app: the payload returned no window.");
      const hwnd = Number(w["hwnd"]);
      if (Number.isFinite(hwnd)) ownedHwnds.add(hwnd);
      const wpid = Number(w["pid"]);
      if (Number.isFinite(wpid) && wpid > 0 && String(w["process"] ?? "").toLowerCase() !== "applicationframehost") ownedPids.add(wpid);
      const fg = res["foreground_taken_then_restored"]
        ? res["foreground_restored"] === false
          ? " (the new window grabbed the foreground and could NOT be handed back)"
          : " (the new window briefly grabbed the foreground; it was handed back)"
        : "";
      return { type: "text", text: `Opened ${fmtWindow(w)} (launched pid ${res["launched_pid"]}).${fg} Use hwnd=${hwnd} for later actions.` };
    }
    case "close_window": {
      const hwnd = Number(res["hwnd"]);
      if (res["closed"]) {
        ownedHwnds.delete(hwnd);
        return {
          type: "text",
          text: `Closed window ${hwnd} "${res["title"]}". Any unsaved content was not saved by this tool and may be kept by the app (for example Notepad restores unsaved tabs when it reopens).`,
        };
      }
      const dlg = (res["owned_dialogs"] as Array<Record<string, unknown>> | undefined) ?? [];
      return {
        type: "text",
        text: `${res["message"]}${dlg.length ? `\nDialogs: ${dlg.map(fmtWindow).join("; ")}\nUse ui_tree/invoke on the dialog hwnd (for example its "Don't save" button), then close_window again.` : ""}`,
      };
    }
    default: {
      const extra = res["value_now"] !== undefined && res["value_now"] !== null ? ` Value now: "${res["value_now"]}"` : "";
      const st = res["state"] !== undefined ? ` State: ${res["state"]}.` : "";
      return { type: "text", text: `${res["message"] ?? "ok"}${st}${extra}` };
    }
  }
}

// ---------------------------------------------------------------------------
// Schema and tool definition
// ---------------------------------------------------------------------------

const ComputerInputSchema = z.object({
  action: z.enum(COMPUTER_ACTIONS).describe("What to do."),
  hwnd: z.number().int().optional().describe("Target window handle (from list_windows/open_app)."),
  window: z.string().optional().describe("Alternative to hwnd: a unique substring of the window title."),
  element: z.string().optional().describe(
    'UIA element: "#AutomationId", "Name", "ControlType:Name" (e.g. "Edit:Text editor"), or a path "Pane > Button:Save". Names match exactly (case-insensitive), else by unique substring.',
  ),
  automation_id: z.string().optional().describe("Alternative to element: exact AutomationId."),
  name: z.string().optional().describe("Alternative to element: element Name."),
  control_type: z.string().optional().describe("Alternative to element: ControlType such as Edit, Button, CheckBox."),
  index: z.number().int().optional().describe("Pick the Nth match (0-based) when several elements match."),
  value: z.string().optional().describe("set_value: the new text. select: text for editable combo boxes."),
  state: z.string().optional().describe("toggle: on/off. expand: expand/collapse."),
  direction: z.enum(["up", "down", "left", "right"]).optional().describe("scroll direction."),
  amount: z.number().int().optional().describe("scroll: number of page steps (default 1)."),
  depth: z.number().int().optional().describe("ui_tree: max depth (default 6)."),
  max_nodes: z.number().int().optional().describe("ui_tree: max elements (default 150)."),
  include_hidden: z.boolean().optional().describe("list_windows: include hidden/cloaked windows."),
  exe: z.string().optional().describe('open_app: program to launch, e.g. "notepad" or a full path.'),
  args: z.string().optional().describe("open_app: command-line arguments."),
  cwd: z.string().optional().describe("open_app: working directory."),
  wait_ms: z.number().int().optional().describe("open_app: how long to wait for the window (default 10000)."),
  text: z.string().optional().describe("type_text (real input, opt-in): text to type."),
  x: z.number().int().optional().describe("click_at (real input, opt-in): screen x."),
  y: z.number().int().optional().describe("click_at (real input, opt-in): screen y."),
  button: z.enum(["left", "right"]).optional(),
  timeout_ms: z.number().int().optional().describe("Per-call timeout (default 30000, max 120000)."),
});

export type ComputerToolInput = z.infer<typeof ComputerInputSchema>;

export const computerTool = Object.assign(
  buildTool<ComputerToolInput, ComputerOutput>({
    name: "Computer",

    inputSchema: ComputerInputSchema,

    isReadOnly: (input?: ComputerToolInput) =>
      input?.action === "list_windows" || input?.action === "screenshot" || input?.action === "ui_tree",
    isConcurrencySafe: () => false,
    isDestructive: () => false,
    isEnabled: () => process.platform === "win32",
    maxResultSizeChars: Infinity,

    description: () =>
      "Windows computer use: list windows, read a window's UI Automation tree, screenshot, and operate controls without touching the mouse or keyboard.",

    prompt: () => `## Computer tool (Windows)
Drive desktop apps without moving the real mouse or stealing focus. Everything below works on background windows.
Preferred loop: open_app (or list_windows) -> ui_tree -> act on elements with UI Automation -> ui_tree again to confirm.
- list_windows: hwnd, title, process, pid, bounds, visible/minimized for each window.
- open_app {exe, args?}: launch a program; returns its window hwnd. Use that hwnd afterwards.
- ui_tree {hwnd, depth?, max_nodes?, element?}: compact tree. Each line: ControlType "name" #automationId [x,y,w,h] patterns=... value="...". The text of an editor appears as value=. READ results from here.
- invoke {hwnd, element}: press a button / menu item (InvokePattern).
- set_value {hwnd, element, value}: put text into an edit control (ValuePattern); the editor is the element whose patterns= include Value (often "Document:Text editor" or "Edit:..."). Without element it targets the window's main editor. Prefer this over typing.
- toggle {hwnd, element, state?}, select {hwnd, element}, expand {hwnd, element, state?}, scroll {hwnd, element, direction, amount?}.
- screenshot {hwnd?}: PNG of one window (or the whole screen without hwnd) for visual checks (layout, images, rendering). It is saved under EMBER_HOME/screens and shown to you when you can see images. Do not use screenshots to read text that ui_tree can give you.
- invoke/set_value/toggle/select/expand/scroll/close_window act only on windows opened by open_app in this session (and their own dialogs); other windows are refused with [not_owned]. close_window sends WM_CLOSE. If a save dialog appears, handle it with ui_tree + invoke on the dialog hwnd, then close again.
- element syntax: "#AutomationId", "Name", "Edit:Name", or "Pane > Button:Save". If an element is not found the error lists close matches; fix the name from ui_tree.
- type_text and click_at (real keyboard/mouse) are disabled unless the operator enabled them; do not rely on them.
Never kill processes; never act on windows you did not open unless the user asked.`,

    checkPermissions: async (input: ComputerToolInput) => {
      if (REAL_INPUT_ACTIONS.has(input.action)) {
        if (!realInputEnabled()) {
          return {
            behavior: "deny" as const,
            updatedInput: input,
            message: `${input.action} is disabled: real input needs EMBER_COMPUTER_REAL_INPUT=1.`,
          };
        }
        return {
          behavior: "ask" as const,
          updatedInput: input,
          message:
            input.action === "type_text"
              ? `Computer: type ${JSON.stringify((input.text ?? "").slice(0, 80))} with REAL keystrokes${input.hwnd ? ` into window ${input.hwnd}` : ""}?`
              : `Computer: REAL ${input.button ?? "left"} click at screen (${input.x}, ${input.y})?`,
        };
      }
      return { behavior: "allow" as const, updatedInput: input };
    },

    call: async (args: ComputerToolInput, _ctx: ToolUseContext) => {
      const data = await runComputerAction(args as ComputerInput);
      return { data };
    },

    mapToolResultToToolResultBlockParam: (content: ComputerOutput, toolUseId: string) => {
      if (content.type === "error") {
        return { type: "tool_result" as const, tool_use_id: toolUseId, content: content.error, is_error: true };
      }
      if (content.type === "image" && content.base64) {
        return {
          type: "tool_result" as const,
          tool_use_id: toolUseId,
          content: [
            { type: "text", text: content.text },
            { type: "image", source: { type: "base64", media_type: content.mediaType, data: content.base64 } },
          ],
        };
      }
      return { type: "tool_result" as const, tool_use_id: toolUseId, content: content.text };
    },

    toAutoClassifierInput: (input?: ComputerToolInput) => `${input?.action ?? ""} ${input?.hwnd ?? input?.window ?? ""}`,
  }),
  {
    searchHint: "windows desktop UI automation screenshot open app notepad",
    alwaysLoad: true,
  } as const,
);
