// Tests for the /plugin command: arg parsing (AC1, AC2, AC5) and
// routing (AC3) and pagination helper (AC4).

import { describe, it, expect, beforeEach } from "bun:test";
import {
  parsePluginArgs,
  pluginCommand,
  setPluginCommandDeps,
  resetPluginCommandDeps,
  createPaginationState,
  adjustScrollToKeepInView,
  goToPage,
  nextPage,
  prevPage,
  type ParsedPluginCommand,
} from "./plugin.ts";
import type { CommandContext } from "../types/command-types.ts";

function makeContext(extras: Record<string, unknown> = {}): CommandContext {
  return {
    sessionId: "test",
    mode: "default",
    cwd: "/test",
    ...extras,
  } as unknown as CommandContext;
}

// ---------------------------------------------------------------------------
// AC1: No args or unknown first token → menu view
// ---------------------------------------------------------------------------

describe("parsePluginArgs — AC1", () => {
  it("no args → menu", () => {
    expect(parsePluginArgs("")).toEqual({ type: "menu" });
  });

  it("whitespace only → menu", () => {
    expect(parsePluginArgs("   ")).toEqual({ type: "menu" });
  });

  it("unknown token → menu", () => {
    expect(parsePluginArgs("foobar")).toEqual({ type: "menu" });
  });

  it("unknown multi-token → menu", () => {
    expect(parsePluginArgs("blah blah")).toEqual({ type: "menu" });
  });
});

// ---------------------------------------------------------------------------
// AC2: install with URL/path → isUrlOrPath=true; without → false
// ---------------------------------------------------------------------------

describe("parsePluginArgs — AC2: install routing", () => {
  it("install with https URL → isUrlOrPath true", () => {
    const cmd = parsePluginArgs("install https://example.com/plugin") as {
      type: "install";
      target: string;
      isUrlOrPath: boolean;
    };
    expect(cmd.type).toBe("install");
    expect(cmd.isUrlOrPath).toBe(true);
  });

  it("install with http URL → isUrlOrPath true", () => {
    const cmd = parsePluginArgs("install http://example.com/plugin") as {
      type: "install";
      target: string;
      isUrlOrPath: boolean;
    };
    expect(cmd.isUrlOrPath).toBe(true);
  });

  it("install with file:// URL → isUrlOrPath true", () => {
    const cmd = parsePluginArgs("install file:///local/plugin") as {
      type: "install";
      target: string;
      isUrlOrPath: boolean;
    };
    expect(cmd.isUrlOrPath).toBe(true);
  });

  it("install with path separator → isUrlOrPath true", () => {
    const cmd = parsePluginArgs("install ./my-plugin") as {
      type: "install";
      target: string;
      isUrlOrPath: boolean;
    };
    expect(cmd.isUrlOrPath).toBe(true);
  });

  it("install with @ → isUrlOrPath true (marketplace URL)", () => {
    const cmd = parsePluginArgs("install @scope/plugin") as {
      type: "install";
      target: string;
      isUrlOrPath: boolean;
    };
    expect(cmd.isUrlOrPath).toBe(true);
  });

  it("install with plain name → isUrlOrPath false", () => {
    const cmd = parsePluginArgs("install my-plugin") as {
      type: "install";
      target: string;
      isUrlOrPath: boolean;
    };
    expect(cmd.type).toBe("install");
    expect(cmd.isUrlOrPath).toBe(false);
    expect(cmd.target).toBe("my-plugin");
  });

  it("install with no target → isUrlOrPath false, target undefined", () => {
    const cmd = parsePluginArgs("install") as {
      type: "install";
      target?: string;
      isUrlOrPath: boolean;
    };
    expect(cmd.type).toBe("install");
    expect(cmd.target).toBeUndefined();
    expect(cmd.isUrlOrPath).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// AC3: Ant users see PluginSettings; others see standard panel
// ---------------------------------------------------------------------------

describe("pluginCommand — AC3: ant vs standard routing", () => {
  let antRenderCalled = false;
  let standardRenderCalled = false;

  beforeEach(() => {
    antRenderCalled = false;
    standardRenderCalled = false;
    resetPluginCommandDeps();
  });

  it("AC3: ant user → renderPluginSettings called", async () => {
    setPluginCommandDeps({
      isAntUser: () => true,
      renderPluginSettings: () => {
        antRenderCalled = true;
      },
      renderMcpSettings: () => {
        standardRenderCalled = true;
      },
    });
    await pluginCommand.execute("", makeContext());
    expect(antRenderCalled).toBe(true);
    expect(standardRenderCalled).toBe(false);
  });

  it("AC3: non-ant user → renderMcpSettings called", async () => {
    setPluginCommandDeps({
      isAntUser: () => false,
      renderPluginSettings: () => {
        antRenderCalled = true;
      },
      renderMcpSettings: () => {
        standardRenderCalled = true;
      },
    });
    await pluginCommand.execute("", makeContext());
    expect(antRenderCalled).toBe(false);
    expect(standardRenderCalled).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// AC4: Pagination helper keeps selected item in view
// ---------------------------------------------------------------------------

describe("pagination helper — AC4", () => {
  it("createPaginationState with defaults", () => {
    const state = createPaginationState(10);
    expect(state.selectedIndex).toBe(0);
    expect(state.scrollOffset).toBe(0);
    expect(state.maxVisible).toBe(5);
    expect(state.canScrollUp).toBe(false);
    expect(state.canScrollDown).toBe(true);
  });

  it("AC4: scrolls down when selected item goes below visible window", () => {
    const state = createPaginationState(10, 5);
    const updated = adjustScrollToKeepInView(state, 6);
    expect(updated.selectedIndex).toBe(6);
    expect(updated.scrollOffset).toBe(2); // 6 - 5 + 1
    expect(updated.canScrollDown).toBe(true);
    expect(updated.canScrollUp).toBe(true);
  });

  it("AC4: scrolls up when selected item goes above visible window", () => {
    const state = { ...createPaginationState(10, 5), scrollOffset: 5 };
    const updated = adjustScrollToKeepInView(state, 3);
    expect(updated.scrollOffset).toBe(3);
    expect(updated.canScrollUp).toBe(true);
  });

  it("AC4: no-ops for page navigation methods", () => {
    const state = createPaginationState(10, 5);
    expect(goToPage(state, 2)).toBe(state);
    expect(nextPage(state)).toBe(state);
    expect(prevPage(state)).toBe(state);
  });

  it("AC4: canScrollDown is false when all items fit", () => {
    const state = createPaginationState(3, 5);
    expect(state.canScrollDown).toBe(false);
  });

  it("AC4: scroll offset clamped at upper bound", () => {
    const state = createPaginationState(5, 5);
    const updated = adjustScrollToKeepInView(state, 4);
    expect(updated.scrollOffset).toBe(0); // all items fit, no scroll needed
  });
});

// ---------------------------------------------------------------------------
// AC5: marketplace and market are identical
// ---------------------------------------------------------------------------

describe("parsePluginArgs — AC5: marketplace === market", () => {
  it("marketplace with action parses correctly", () => {
    const cmd = parsePluginArgs("marketplace add https://example.com") as {
      type: "marketplace";
      action?: string;
      target?: string;
    };
    expect(cmd.type).toBe("marketplace");
    expect(cmd.action).toBe("add");
    expect(cmd.target).toBe("https://example.com");
  });

  it("market produces same result as marketplace", () => {
    const mkt = parsePluginArgs("marketplace list");
    const mktAlias = parsePluginArgs("market list");
    expect(mkt).toEqual(mktAlias);
  });

  it("rm is normalized to remove", () => {
    const cmd = parsePluginArgs("marketplace rm my-plugin") as {
      type: "marketplace";
      action?: string;
      target?: string;
    };
    expect(cmd.action).toBe("remove");
    expect(cmd.target).toBe("my-plugin");
  });
});

// ---------------------------------------------------------------------------
// General command structure
// ---------------------------------------------------------------------------

describe("pluginCommand structure", () => {
  it("name is 'plugin'", () => expect(pluginCommand.name).toBe("plugin"));
  it("type is local-jsx", () => expect(pluginCommand.type).toBe("local-jsx"));
  it("is enabled", () => expect(pluginCommand.isEnabled()).toBe(true));
});
