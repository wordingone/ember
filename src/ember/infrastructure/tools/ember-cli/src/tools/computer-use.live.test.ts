// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// tools/computer-use.live.test.ts -- LIVE Computer tool test against the real
// PowerShell payload. Opens its OWN Notepad and touches only that window; no
// real mouse/keyboard input. Opt-in: EMBER_COMPUTER_LIVE_TEST=1 (Windows only).
import { describe, expect, test } from "bun:test";
import { existsSync, mkdtempSync, readFileSync } from "fs";
import { tmpdir } from "os";
import { join } from "path";
import { runComputerAction } from "./computer-use.ts";

const live = process.platform === "win32" && process.env["EMBER_COMPUTER_LIVE_TEST"] === "1";

describe.skipIf(!live)("Computer tool, live Notepad", () => {
  test("open_app -> ui_tree -> set_value -> read back -> screenshot -> refuse foreign close -> close_window", async () => {
    process.env["EMBER_HOME"] = mkdtempSync(join(tmpdir(), "ember-cu-live-"));
    const opened = await runComputerAction({ action: "open_app", exe: "notepad" });
    expect(opened.type).toBe("text");
    const hwnd = Number(/hwnd=(\d+)/.exec((opened as { text: string }).text)![1]);
    try {
      const tree = await runComputerAction({ action: "ui_tree", hwnd });
      expect((tree as { text: string }).text).toMatch(/Document|Edit/);

      const wrong = await runComputerAction({ action: "set_value", hwnd, element: "Editt", value: "x" });
      expect(wrong.type).toBe("error");
      expect((wrong as { error: string }).error).toContain("Close matches");

      const set = await runComputerAction({ action: "set_value", hwnd, element: "Document:Text editor", value: "hello from ember" });
      expect(set.type).toBe("text");

      const back = await runComputerAction({ action: "ui_tree", hwnd, depth: 3 });
      expect((back as { text: string }).text).toContain('value="hello from ember"');

      const shot = await runComputerAction({ action: "screenshot", hwnd });
      const m = /saved to (.+?\.png)/.exec((shot as { text: string }).text)!;
      expect(existsSync(m[1]!)).toBe(true);
      expect(readFileSync(m[1]!).subarray(0, 4).toString("hex")).toBe("89504e47");

      const list = await runComputerAction({ action: "list_windows" });
      const foreign = [...(list as { text: string }).text.matchAll(/hwnd=(\d+)/g)].map((x) => Number(x[1])).find((h) => h !== hwnd);
      if (foreign !== undefined) {
        const refused = await runComputerAction({ action: "close_window", hwnd: foreign });
        expect(refused.type).toBe("error");
        expect((refused as { error: string }).error).toContain("not_owned");
      }
    } finally {
      // Win11 Notepad restores unsaved tabs on next launch: leave it empty.
      await runComputerAction({ action: "set_value", hwnd, value: "" });
      const closed = await runComputerAction({ action: "close_window", hwnd });
      expect((closed as { text?: string }).text ?? "").toContain("Closed window");
    }
    const gone = await runComputerAction({ action: "ui_tree", hwnd });
    expect((gone as { error: string }).error).toContain("no longer exists");
  }, 120_000);
});
