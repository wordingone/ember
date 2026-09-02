// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { describe, expect, test } from "bun:test";
import React, { useState } from "react";
import { Text } from "../ink/components.ts";
import { mountInk } from "../ink/reconciler.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../../../../../../../tools/ember-cli/src/ink/rendering-pipeline.ts";
import {
  DEFAULT_PROMPT_PERMISSION_MODE,
  PERMISSION_MODES,
  usePromptInput,
  type PermissionMode,
} from "./prompt-input.ts";

async function flush(): Promise<void> {
  for (let index = 0; index < 4; index++) {
    await new Promise<void>((resolve) => setImmediate(resolve));
  }
}

function frameText(raw: string): string {
  const frame = buildFrame(30, 3);
  parseRenderedIntoFrame(raw, frame, new StylePool());
  return frame.cells.map((row) => row.map((cell) => cell?.char ?? " ").join("")).join("\n");
}

describe("#1215 prompt sandbox default", () => {
  test("the prompt hook and its cycle share the same sandbox-first default", () => {
    expect(DEFAULT_PROMPT_PERMISSION_MODE).toBe("regular");
    expect(PERMISSION_MODES[0]).toBe(DEFAULT_PROMPT_PERMISSION_MODE);
  });

  test("a controlled session mode and cycle callback are authoritative", async () => {
    let rendered = "";
    let cycleCount = 0;
    let cycle: (() => void) | undefined;

    function Probe(): React.ReactElement {
      const [mode, setMode] = useState<PermissionMode>("bypass");
      const [state, actions] = usePromptInput({
        permissionMode: mode,
        onPermissionModeCycle: () => {
          cycleCount += 1;
          setMode("regular");
        },
      });
      cycle = actions.cyclePermissionMode;
      return React.createElement(Text, null, `MODE:${state.permissionMode}`);
    }

    const handle = mountInk(React.createElement(Probe), {
      stream: { write(chunk: string) { rendered += chunk; } },
      stdout: { columns: 30, rows: 3 },
    });
    await flush();
    expect(frameText(rendered)).toContain("MODE:bypass");

    cycle!();
    await flush();
    expect(cycleCount).toBe(1);
    expect(frameText(rendered)).toContain("MODE:regular");
    handle.unmount();
  });
});