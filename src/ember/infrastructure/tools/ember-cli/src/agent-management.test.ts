// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Tests for agent-management — covers spec ACs 1-12.
import { test, expect, describe } from "bun:test";
import { writeFile, unlink } from "fs/promises";
import { join } from "path";
import { tmpdir } from "os";
import {
  validateAgentIdentifier,
  hasOverride,
  resolveSelectedTools,
  saveAgentToFile,
  deleteAgentFromFile,
  writeFileAndFlush,
  wizardHistoryCreate,
  wizardHistoryPush,
  wizardHistoryBack,
  parseGenerateResponse,
  colorPickerNext,
  colorPickerPrev,
  afterDeleteMode,
  serializeAgentFile,
  parseAgentFile,
  COLOR_OPTIONS,
  AGENT_COLORS,
  AgentsMenu,
  AgentsList,
  ToolSelector,
  ColorPicker,
} from "./agent-management.ts";
import type { AgentDefinition } from "./agent-management.ts";

// ---------------------------------------------------------------------------
// AC1: "my-agent" (8 chars, alphanumeric + hyphen) passes validation
// ---------------------------------------------------------------------------

describe("AC1 — valid identifier passes", () => {
  test("AC1: validateAgentIdentifier('my-agent') returns true", () => {
    expect(validateAgentIdentifier("my-agent")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// AC2: "a" (1 char) fails validation — too short
// ---------------------------------------------------------------------------

describe("AC2 — too-short identifier fails", () => {
  test("AC2: validateAgentIdentifier('a') returns false", () => {
    expect(validateAgentIdentifier("a")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// AC3: "-bad" (starts with hyphen) fails validation
// ---------------------------------------------------------------------------

describe("AC3 — hyphen-start identifier fails", () => {
  test("AC3: validateAgentIdentifier('-bad') returns false", () => {
    expect(validateAgentIdentifier("-bad")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// AC4: project agent same identifier as user agent shows ⚠ override
// ---------------------------------------------------------------------------

describe("AC4 — override detection", () => {
  test("AC4: hasOverride returns true when project agent shadows user agent", () => {
    const userAgents = [{ agentType: "my-helper" }];
    const projectAgent = { agentType: "my-helper" };
    expect(hasOverride(userAgents, projectAgent)).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// AC5: ToolSelector with nothing selected → tools: undefined (all tools)
// ---------------------------------------------------------------------------

describe("AC5 — empty selection yields undefined tools", () => {
  test("AC5: resolveSelectedTools([]) returns undefined", () => {
    expect(resolveSelectedTools([])).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// AC6: saveAgentToFile with checkExists: true fails if file already exists
// ---------------------------------------------------------------------------

describe("AC6 — exclusive create fails on existing file", () => {
  test("AC6: saveAgentToFile(checkExists=true) rejects with EEXIST on existing file", async () => {
    const path = join(tmpdir(), `agent-ac6-${Date.now()}.md`);
    await writeFile(path, "existing content", "utf8");
    try {
      await expect(saveAgentToFile(path, "new content", true)).rejects.toThrow();
    } finally {
      await unlink(path).catch(() => {});
    }
  });
});

// ---------------------------------------------------------------------------
// AC7: deleteAgentFromFile succeeds if file already deleted
// ---------------------------------------------------------------------------

describe("AC7 — delete of already-deleted file is a no-op", () => {
  test("AC7: deleteAgentFromFile on non-existent path resolves without error", async () => {
    const path = join(tmpdir(), `agent-ac7-${Date.now()}-never-created.md`);
    await expect(deleteAgentFromFile(path)).resolves.toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// AC8: Wizard Esc goes back to came-from step, not necessarily the prior numbered step
// ---------------------------------------------------------------------------

describe("AC8 — wizard history back goes to came-from step", () => {
  test("AC8: wizardHistoryBack returns to the step the user came FROM", () => {
    // Start at 'type', jump to 'generate' (non-linear), then Esc should go back to 'type'
    const h0 = wizardHistoryCreate("type");
    // Jump past several steps directly to 'generate'
    const h1 = wizardHistoryPush(h0, "generate");
    const back = wizardHistoryBack(h1);
    expect(back.current).toBe("type");
    // Stack should be empty again
    expect(back.stack).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// AC9: GenerateStep falls back to regex extraction when JSON is invalid
// ---------------------------------------------------------------------------

describe("AC9 — parseGenerateResponse regex fallback", () => {
  test("AC9: falls back to regex when model response is not valid JSON", () => {
    const raw = `
      Here is the agent:
      "identifier": "my-bot",
      "whenToUse": "When you need a bot",
      "systemPrompt": "You are a helpful bot."
    `;
    const result = parseGenerateResponse(raw);
    expect(result).not.toBeNull();
    expect(result?.identifier).toBe("my-bot");
    expect(result?.whenToUse).toBe("When you need a bot");
    expect(result?.systemPrompt).toBe("You are a helpful bot.");
  });
});

// ---------------------------------------------------------------------------
// AC10: ColorPicker Down-arrow from last color wraps to 'automatic'
// ---------------------------------------------------------------------------

describe("AC10 — ColorPicker circular navigation wraps", () => {
  test("AC10: colorPickerNext from last AGENT_COLOR wraps to 'automatic'", () => {
    const lastColor = AGENT_COLORS[AGENT_COLORS.length - 1];
    expect(lastColor).toBeDefined();
    // lastColor is the last entry before 'automatic' wraps
    const next = colorPickerNext(lastColor as string);
    expect(next).toBe("automatic");
  });
});

// ---------------------------------------------------------------------------
// AC11: Deleting from delete-confirm returns to list-agents, not agent-menu
// ---------------------------------------------------------------------------

describe("AC11 — afterDeleteMode returns list-agents", () => {
  test("AC11: afterDeleteMode() is 'list-agents'", () => {
    expect(afterDeleteMode()).toBe("list-agents");
  });
});

// ---------------------------------------------------------------------------
// AC12: writeFileAndFlush ensures durability (datasync before returning)
// ---------------------------------------------------------------------------

describe("AC12 — writeFileAndFlush writes and syncs", () => {
  test("AC12: writeFileAndFlush creates file with correct content", async () => {
    const path = join(tmpdir(), `agent-ac12-${Date.now()}.md`);
    const content = "---\nname: test\n---\n\nHello";
    await writeFileAndFlush(path, content);
    const { readFile } = await import("fs/promises");
    const written = await readFile(path, "utf8");
    expect(written).toBe(content);
    await unlink(path).catch(() => {});
  });
});

// ---------------------------------------------------------------------------
// Additional structural checks
// ---------------------------------------------------------------------------

describe("module structure", () => {
  test("AgentsMenu is a function", () => {
    expect(typeof AgentsMenu).toBe("function");
  });

  test("COLOR_OPTIONS starts with 'automatic'", () => {
    expect(COLOR_OPTIONS[0]).toBe("automatic");
  });

  test("colorPickerPrev wraps from 'automatic' to last color", () => {
    const prev = colorPickerPrev("automatic");
    const lastColor = AGENT_COLORS[AGENT_COLORS.length - 1];
    expect(lastColor).toBeDefined(); // noUncheckedIndexedAccess guard
    expect(prev).toBe(lastColor!);   // ! removes | undefined; array is non-empty
  });

  test("parseGenerateResponse parses valid JSON", () => {
    const raw = JSON.stringify({ identifier: "bot", whenToUse: "Always", systemPrompt: "Be helpful." });
    const result = parseGenerateResponse(raw);
    expect(result?.identifier).toBe("bot");
  });

  test("serializeAgentFile produces expected YAML frontmatter", () => {
    const def: AgentDefinition = {
      agentType: "my-agent",
      name: "My Agent",
      description: "A test agent.",
      model: "sonnet",
      systemPrompt: "You are helpful.",
      location: "user",
      filePath: "/path/to/agent.md",
    };
    const out = serializeAgentFile(def);
    expect(out).toContain("---");
    expect(out).toContain("name: My Agent");
    expect(out).toContain("model: sonnet");
    expect(out).toContain("You are helpful.");
  });
});
