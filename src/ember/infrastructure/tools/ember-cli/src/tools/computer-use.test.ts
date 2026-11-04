// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// tools/computer-use.test.ts -- Computer tool units with the PowerShell runner mocked.
import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { mkdtempSync, writeFileSync } from "fs";
import { tmpdir } from "os";
import { join } from "path";
import {
  computerTool,
  getOwnedHwndsForTests,
  resetComputerSessionForTests,
  runComputerAction,
  setPsRunnerForTests,
  type PsResult,
} from "./computer-use.ts";
import { COMPUTER_USE_PS_SCRIPT } from "./computer-use-ps.ts";
import { BUILTIN_TOOLS } from "./builtin-tools.ts";

type Call = { action: string; args: Record<string, unknown>; timeoutMs: number };
let calls: Call[] = [];
let reply: (c: Call) => PsResult = () => ({ ok: true });
const saved: Record<string, string | undefined> = {};

beforeEach(() => {
  calls = [];
  reply = () => ({ ok: true });
  for (const k of ["EMBER_COMPUTER_REAL_INPUT", "EMBER_VISION", "EMBER_HOME"]) saved[k] = process.env[k];
  delete process.env["EMBER_COMPUTER_REAL_INPUT"];
  delete process.env["EMBER_VISION"];
  process.env["EMBER_HOME"] = mkdtempSync(join(tmpdir(), "ember-cu-test-"));
  resetComputerSessionForTests();
  setPsRunnerForTests(async (action, args, timeoutMs) => {
    const c = { action, args, timeoutMs };
    calls.push(c);
    return reply(c);
  });
});
afterEach(() => {
  setPsRunnerForTests(undefined);
  for (const [k, v] of Object.entries(saved)) {
    if (v === undefined) delete process.env[k];
    else process.env[k] = v;
  }
});

const win = (hwnd: number) => ({
  hwnd, title: "Untitled - Notepad", process: "Notepad", pid: 7, bounds: [0, 0, 800, 600], visible: true, minimized: false,
});

describe("registration", () => {
  test("Computer is a built-in tool with a precise prompt", () => {
    expect(BUILTIN_TOOLS.some((t) => t.name === "Computer")).toBe(true);
    const p = computerTool.prompt!();
    expect(p).toContain("ui_tree");
    expect(p).toContain("screenshot");
    expect(p).toMatch(/Preferred/);
    expect(computerTool.inputJSONSchema).toBeDefined();
  });
});

describe("observe actions", () => {
  test("list_windows formats hwnd, title, process, pid, bounds, state", async () => {
    reply = () => ({ ok: true, windows: [win(42)] });
    const r = await runComputerAction({ action: "list_windows" });
    expect(r.type).toBe("text");
    const t = (r as { text: string }).text;
    expect(t).toContain("hwnd=42");
    expect(t).toContain("pid=7");
    expect(t).toContain("proc=Notepad");
    expect(t).toContain("[0,0,800,600]");
    expect(t).toContain("visible");
  });

  test("ui_tree returns the tree text and passes depth/max_nodes through", async () => {
    reply = () => ({ ok: true, window: win(5), nodes: 2, tree: 'Window "x"\n  Edit #e' });
    const r = await runComputerAction({ action: "ui_tree", hwnd: 5, depth: 3, max_nodes: 20 });
    expect((r as { text: string }).text).toContain("Edit #e");
    expect(calls[0]!.args).toMatchObject({ hwnd: 5, depth: 3, max_nodes: 20 });
  });
});

describe("screenshot", () => {
  const png = Buffer.from("89504e470d0a1a0a", "hex");
  test("with vision: saves under EMBER_HOME/screens and returns an image block", async () => {
    process.env["EMBER_VISION"] = "1";
    reply = (c) => {
      writeFileSync(c.args["save_path"] as string, png);
      return { ok: true, target: "window", path: c.args["save_path"], width: 1280, height: 700, original_width: 1920, original_height: 1050, window: win(9) };
    };
    const r = await runComputerAction({ action: "screenshot", hwnd: 9 });
    expect(r.type).toBe("image");
    expect(calls[0]!.args["save_path"]).toContain(join(process.env["EMBER_HOME"]!, "screens"));
    expect(calls[0]!.args["max_width"]).toBe(1280);
    const block = computerTool.mapToolResultToToolResultBlockParam(r as never, "t1");
    const content = block.content as Array<{ type: string; source?: { data: string; media_type: string } }>;
    expect(content[1]!.type).toBe("image");
    expect(content[1]!.source!.data).toBe(png.toString("base64"));
    expect(content[1]!.source!.media_type).toBe("image/png");
  });

  test("without a vision projector: text only, path reported, no image block", async () => {
    reply = (c) => ({ ok: true, target: "screen", path: c.args["save_path"], width: 1280, height: 720, original_width: 1920, original_height: 1080 });
    const r = await runComputerAction({ action: "screenshot" });
    expect(r.type).toBe("text");
    expect((r as { text: string }).text).toContain("no vision projector");
    const block = computerTool.mapToolResultToToolResultBlockParam(r as never, "t2");
    expect(typeof block.content).toBe("string");
  });
});

describe("UIA actions", () => {
  test.each(["invoke", "set_value", "toggle", "select", "expand", "scroll"] as const)("%s routes to the runner with its arguments", async (action) => {
    reply = (c) => c.action === "open_app" ? { ok: true, launched_pid: 7, window: win(3) } : { ok: true, message: "did it", state: action === "toggle" ? "On" : undefined, value_now: action === "set_value" ? "abc" : undefined };
    await runComputerAction({ action: "open_app", exe: "notepad" });
    calls = [];
    const r = await runComputerAction({ action, hwnd: 3, element: "#Box", value: "abc", state: "on", direction: "down", amount: 2 });
    expect(r.type).toBe("text");
    expect(calls[0]!.action).toBe(action);
    expect(calls[0]!.args).toMatchObject({ hwnd: 3, element: "#Box", value: "abc" });
  });

  test("element not found surfaces the close matches", async () => {
    reply = (c) => c.action === "open_app" ? { ok: true, launched_pid: 7, window: win(3) } : { ok: false, kind: "element_not_found", error: 'Element not found: "Sav". Close matches: Button "Save" #SaveBtn' };
    await runComputerAction({ action: "open_app", exe: "notepad" });
    const r = await runComputerAction({ action: "invoke", hwnd: 3, element: "Sav" });
    expect(r.type).toBe("error");
    expect((r as { error: string }).error).toContain("Close matches");
    expect((r as { error: string }).error).toContain("[element_not_found]");
  });

  test("window gone gives a clear error", async () => {
    reply = () => ({ ok: false, kind: "window_gone", error: "Window hwnd 3 no longer exists." });
    const r = await runComputerAction({ action: "ui_tree", hwnd: 3 });
    expect((r as { error: string }).error).toContain("no longer exists");
  });

  test("PowerShell failure is surfaced with its stderr text", async () => {
    reply = () => ({ ok: false, kind: "powershell_failed", error: "powershell exited with code 1. stderr: boom" });
    const r = await runComputerAction({ action: "ui_tree", hwnd: 3 });
    expect((r as { error: string }).error).toContain("stderr: boom");
  });

  test("every call carries a bounded timeout", async () => {
    await runComputerAction({ action: "list_windows" });
    await runComputerAction({ action: "list_windows", timeout_ms: 999_999 });
    await runComputerAction({ action: "open_app", exe: "notepad" });
    expect(calls[0]!.timeoutMs).toBe(30_000);
    expect(calls[1]!.timeoutMs).toBe(120_000);
    expect(calls[2]!.timeoutMs).toBe(45_000);
  });
});

describe("open_app / close_window ownership", () => {
  test("open_app records the hwnd; close_window passes only owned hwnds to the payload", async () => {
    reply = (c) =>
      c.action === "open_app"
        ? { ok: true, launched_pid: 99, window: win(777), foreground_taken_then_restored: false }
        : { ok: true, closed: true, hwnd: c.args["hwnd"], title: "Untitled" };
    const o = await runComputerAction({ action: "open_app", exe: "notepad" });
    expect((o as { text: string }).text).toContain("hwnd=777");
    expect(getOwnedHwndsForTests()).toEqual([777]);
    const c = await runComputerAction({ action: "close_window", hwnd: 777 });
    expect((c as { text: string }).text).toContain("Closed window 777");
    expect(calls[1]!.args["owned"]).toEqual([777]);
    expect(getOwnedHwndsForTests()).toEqual([]);
  });

  test("close_window of a foreign hwnd is refused by the payload with an explicit error", async () => {
    reply = () => ({ ok: false, kind: "not_owned", error: "Refusing to close: not opened by the Computer tool." });
    const r = await runComputerAction({ action: "close_window", hwnd: 12345 });
    expect(r.type).toBe("error");
    expect(calls[0]!.args["owned"]).toEqual([]);
  });

  test("a close that leaves a dialog reports the dialogs", async () => {
    reply = () => ({ ok: true, closed: false, hwnd: 5, title: "x", message: "WM_CLOSE sent but the window is still open (probably a save/confirm dialog).", owned_dialogs: [win(6)] });
    const r = await runComputerAction({ action: "close_window", hwnd: 5 });
    expect((r as { text: string }).text).toContain("still open");
    expect((r as { text: string }).text).toContain("hwnd=6");
  });
});

describe("real input is opt-in", () => {
  test("type_text and click_at are refused without EMBER_COMPUTER_REAL_INPUT and never reach PowerShell", async () => {
    const a = await runComputerAction({ action: "type_text", text: "hi", hwnd: 1 });
    const b = await runComputerAction({ action: "click_at", x: 1, y: 2 });
    expect(a.type).toBe("error");
    expect(b.type).toBe("error");
    expect(calls.length).toBe(0);
    const perm = await computerTool.checkPermissions({ action: "type_text", text: "hi" } as never, {} as never);
    expect(perm.behavior).toBe("deny");
  });

  test("with the env var set the per-call permission is still 'ask'", async () => {
    process.env["EMBER_COMPUTER_REAL_INPUT"] = "1";
    const p1 = await computerTool.checkPermissions({ action: "type_text", text: "hi" } as never, {} as never);
    const p2 = await computerTool.checkPermissions({ action: "click_at", x: 1, y: 2 } as never, {} as never);
    const p3 = await computerTool.checkPermissions({ action: "set_value", value: "x" } as never, {} as never);
    expect(p1.behavior).toBe("ask");
    expect(p2.behavior).toBe("ask");
    expect(p3.behavior).toBe("allow");
  });
});

describe("ownership applies to every mutating action (#2381 CV-8)", () => {
  const MUT: Array<"invoke" | "set_value" | "toggle" | "select" | "expand" | "scroll"> = ["invoke", "set_value", "toggle", "select", "expand", "scroll"];

  test.each(MUT)("%s on a window the tool did not open is refused with [not_owned] and never reaches PowerShell", async (action) => {
    const r = await runComputerAction({ action, hwnd: 999, element: "#x", value: "v" });
    expect(r.type).toBe("error");
    expect((r as { error: string }).error).toContain("[not_owned]");
    expect(calls.length).toBe(0);
  });

  test.each(MUT)("%s sends the owned hwnds and pids to the payload so it can refuse foreign windows", async (action) => {
    reply = (c) => c.action === "open_app" ? { ok: true, launched_pid: 7, window: win(41) } : { ok: false, kind: "not_owned", error: "Refusing to act on this window" };
    await runComputerAction({ action: "open_app", exe: "notepad" });
    const r = await runComputerAction({ action, hwnd: 999, element: "#x", value: "v" });
    expect((r as { error: string }).error).toContain("[not_owned]");
    expect(calls[1]!.args["owned"]).toEqual([41]);
    expect(calls[1]!.args["owned_pids"]).toEqual([7]);
  });

  test("read-only actions stay allowed on any window", async () => {
    reply = () => ({ ok: true, windows: [win(1)], window: win(1), nodes: 1, tree: "x", path: "p", target: "screen" });
    for (const action of ["list_windows", "ui_tree", "screenshot"] as const) {
      const r = await runComputerAction({ action, hwnd: 999 });
      expect(r.type).not.toBe("error");
    }
  });

  test("the payload enforces ownership in the UIA path, allowing same-process dialogs but not ApplicationFrameHost siblings", () => {
    const uia = COMPUTER_USE_PS_SCRIPT.slice(COMPUTER_USE_PS_SCRIPT.indexOf("function Do-Uia"));
    expect(uia.slice(0, 200)).toContain("Assert-Owned $h $true");
    expect(COMPUTER_USE_PS_SCRIPT).toContain("function Assert-Owned");
    expect(COMPUTER_USE_PS_SCRIPT).toContain("'not_owned'");
    expect(COMPUTER_USE_PS_SCRIPT).toContain("ApplicationFrameHost");
    expect(COMPUTER_USE_PS_SCRIPT).toContain("owned_pids");
  });
});

describe("UWP open_app (#2381 CV-13)", () => {
  test("the payload matches new ApplicationFrameHost frames by title (calc -> Calculator)", () => {
    const open = COMPUTER_USE_PS_SCRIPT.slice(COMPUTER_USE_PS_SCRIPT.indexOf("function Do-OpenApp"), COMPUTER_USE_PS_SCRIPT.indexOf("function Do-CloseWindow"));
    expect(open).toContain("ApplicationFrameHost");
    expect(open).toContain("'calc' = 'calculator'");
  });

  test("an AFH-framed Calculator window is recorded as owned, and its pid (the shared frame host) is not", async () => {
    reply = () => ({ ok: true, launched_pid: 5, window: { ...win(88), title: "Calculator", process: "ApplicationFrameHost", pid: 900 } });
    await runComputerAction({ action: "open_app", exe: "calculator" });
    expect(getOwnedHwndsForTests()).toEqual([88]);
    reply = (c) => ({ ok: true, closed: true, hwnd: c.args["hwnd"], title: "Calculator" });
    await runComputerAction({ action: "close_window", hwnd: 88 });
    expect(calls[1]!.args["owned_pids"]).toEqual([]);
  });
});

describe("close_window never claims content was discarded (#2381 CV-6/7)", () => {
  test("result says closed, unsaved content may be kept by the app", async () => {
    reply = (c) => c.action === "open_app" ? { ok: true, launched_pid: 7, window: win(5) } : { ok: true, closed: true, hwnd: 5, title: "Untitled - Notepad" };
    await runComputerAction({ action: "open_app", exe: "notepad" });
    const r = await runComputerAction({ action: "close_window", hwnd: 5 });
    const t = (r as { text: string }).text;
    expect(t).toContain("Closed window 5");
    expect(t).toMatch(/may be kept by the app/);
    expect(t.toLowerCase()).not.toContain("discard");
  });
});
