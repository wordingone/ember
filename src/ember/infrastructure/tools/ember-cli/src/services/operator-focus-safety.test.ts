// operator-focus-safety.test.ts — ember #165 acceptance: "no focus change during
// injection (foreground window unchanged)". GetForegroundWindow before/after is
// not exercisable from a headless test runner, so the substitute that IS
// deterministically checkable: none of the operator input channel's source
// files reference any focus-stealing API at all. If the API is never called,
// the window can never be stolen.

import { describe, test, expect } from "bun:test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

// Every file the operator input channel touches — the transport, the queue
// logic, the receipt writer, and the ReplScreen wiring that composes them.
const FILES_UNDER_TEST = [
  path.join(here, "operator-pipe.ts"),
  path.join(here, "operator-input.ts"),
  path.join(here, "operator-receipts.ts"),
  path.join(here, "..", "screens", "repl.ts"),
];

// Any of these appearing in the operator-channel source is a focus-stealing
// defect: SetForegroundWindow / SendKeys / SendInput family, and the console-
// attach mechanism the 2026-07-05 receipt showed is ACCESS_DENIED anyway
// (AttachConsole + WriteConsoleInput) — the whole point of #165 is to avoid it.
const FORBIDDEN_PATTERNS = [
  /SetForegroundWindow/i,
  /SendKeys/i,
  /SendInput/i,
  /AttachConsole/i,
  /WriteConsoleInput/i,
  /BringWindowToTop/i,
  /SwitchToThisWindow/i,
];

describe("operator input channel — no focus APIs referenced (ember #165 acceptance)", () => {
  for (const filePath of FILES_UNDER_TEST) {
    const rel = path.relative(path.join(here, "..", ".."), filePath);

    test(`${rel} does not reference any focus-stealing API`, () => {
      expect(fs.existsSync(filePath)).toBe(true);
      const source = fs.readFileSync(filePath, "utf8");

      for (const pattern of FORBIDDEN_PATTERNS) {
        expect(pattern.test(source)).toBe(false);
      }
    });
  }
});
