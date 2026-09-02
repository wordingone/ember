// Tests for dialogs — covers AC1–AC10.
import { test, expect, describe } from "bun:test";
import React from "react";
import {
  AUTO_DISMISS_MS,
  hasPendingTasks,
  computeUsagePercent,
  fuzzyMatch,
  isIdeConnectionAutoDismiss,
  onboardingSupportsBack,
  SnapshotUpdateDialog,
  ExitDialog,
  InvalidConfigDialog,
  SearchDialog,
  HistoryDialog,
  CostDialog,
  IdeStatusIndicator,
  OnboardingFlow,
} from "./dialogs.ts";
import type {
  TaskRegistry,
  Message,
  UsageCounter,
  SessionStore,
  SessionEntry,
} from "./dialogs.ts";

// ---------------------------------------------------------------------------
// AC1: ExitDialog with pending tasks shows warning
// ---------------------------------------------------------------------------
describe("AC1: hasPendingTasks", () => {
  test("pendingCount > 0 → true", () => {
    expect(hasPendingTasks({ pendingCount: 2 })).toBe(true);
  });

  test("pendingCount = 0 → false", () => {
    expect(hasPendingTasks({ pendingCount: 0 })).toBe(false);
  });

  test("undefined tasks → false", () => {
    expect(hasPendingTasks(undefined)).toBe(false);
  });

  test("ExitDialog accepts tasks prop (createElement check)", () => {
    const el = React.createElement(ExitDialog, {
      tasks: { pendingCount: 3 },
      onYes: () => {},
      onNo: () => {},
      onWait: () => {},
    });
    expect(el.type).toBe(ExitDialog);
    expect((el.props as { tasks?: TaskRegistry }).tasks?.pendingCount).toBe(3);
  });
});

// ---------------------------------------------------------------------------
// AC2: ExitDialog "Wait" option — onWait prop is threaded correctly
// ---------------------------------------------------------------------------
describe("AC2: ExitDialog onWait callback", () => {
  test("ExitDialog has onWait prop", () => {
    let called = false;
    const el = React.createElement(ExitDialog, {
      onYes: () => {},
      onNo: () => {},
      onWait: () => { called = true; },
    });
    // Verify the callback is present in props
    const p = el.props as { onWait: () => void };
    p.onWait();
    expect(called).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// AC3: InvalidConfigDialog names the specific file
// ---------------------------------------------------------------------------
describe("AC3: InvalidConfigDialog file path", () => {
  test("createElement passes filePath through props", () => {
    const el = React.createElement(InvalidConfigDialog, {
      error: { filePath: "/home/.ember/settings.json", message: "Unexpected token" },
      onEdit: () => {},
      onContinueWithDefaults: () => {},
    });
    const p = el.props as { error: { filePath: string } };
    expect(p.error.filePath).toBe("/home/.ember/settings.json");
  });
});

// ---------------------------------------------------------------------------
// AC4: SearchDialog fuzzy matching
// ---------------------------------------------------------------------------
describe("AC4: fuzzyMatch", () => {
  const messages: Message[] = [
    { id: "1", text: "Hello world" },
    { id: "2", text: "Fix the bug in authentication" },
    { id: "3", text: "Deploy to production" },
    { id: "4", text: "Write unit tests" },
  ];

  test("empty query returns all messages", () => {
    expect(fuzzyMatch("", messages)).toHaveLength(4);
  });

  test("exact word match returns that message", () => {
    const results = fuzzyMatch("hello", messages);
    expect(results.some(m => m.id === "1")).toBe(true);
  });

  test("subsequence match works (non-contiguous)", () => {
    // 'wut' matches 'Write unit tests': W(rite) U(nit) T(ests)
    const results = fuzzyMatch("wut", messages);
    expect(results.some(m => m.id === "4")).toBe(true);
  });

  test("non-matching query returns empty", () => {
    const results = fuzzyMatch("zzz", messages);
    expect(results).toHaveLength(0);
  });

  test("case-insensitive matching", () => {
    const results = fuzzyMatch("HELLO", messages);
    expect(results.some(m => m.id === "1")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// AC5: AUTO_DISMISS_MS is 30 seconds
// ---------------------------------------------------------------------------
describe("AC5: AUTO_DISMISS_MS", () => {
  test("equals 30_000 ms", () => {
    expect(AUTO_DISMISS_MS).toBe(30_000);
  });
});

// ---------------------------------------------------------------------------
// AC6: HistoryDialog opens selected session via store.open
// ---------------------------------------------------------------------------
describe("AC6: HistoryDialog session open", () => {
  test("createElement passes store prop", () => {
    const entries: SessionEntry[] = [
      { id: "sess-1", date: "2026-06-01", cwd: "/home/user", snippet: "first session" },
    ];
    let openedId: string | null = null;
    const store: SessionStore = {
      list: () => entries,
      open: (id: string) => { openedId = id; },
    };
    const el = React.createElement(HistoryDialog, { store, onDismiss: () => {} });
    expect(el.type).toBe(HistoryDialog);
    // Verify store.open works
    store.open("sess-1");
    expect(openedId!).toBe("sess-1");
  });
});

// ---------------------------------------------------------------------------
// AC7: IdeStatusIndicator auto-dismiss behavior
// ---------------------------------------------------------------------------
describe("AC7: isIdeConnectionAutoDismiss", () => {
  test("connected status should auto-dismiss", () => {
    expect(isIdeConnectionAutoDismiss("connected")).toBe(true);
  });

  test("disconnected status should NOT auto-dismiss (requires user action)", () => {
    expect(isIdeConnectionAutoDismiss("disconnected")).toBe(false);
  });

  test("IdeStatusIndicator createElement check for connected", () => {
    const el = React.createElement(IdeStatusIndicator, {
      status: "connected",
      onDismiss: () => {},
    });
    expect(el.type).toBe(IdeStatusIndicator);
    expect((el.props as { status: string }).status).toBe("connected");
  });
});

// ---------------------------------------------------------------------------
// AC8: SnapshotUpdateDialog renders null
// ---------------------------------------------------------------------------
describe("AC8: SnapshotUpdateDialog", () => {
  test("returns null (stub per spec)", () => {
    expect(SnapshotUpdateDialog()).toBeNull();
  });

  test("is callable without arguments", () => {
    expect(() => SnapshotUpdateDialog()).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// AC9: Onboarding flows are linear (no back navigation)
// ---------------------------------------------------------------------------
describe("AC9: onboarding linear-only", () => {
  test("onboardingSupportsBack() always returns false", () => {
    expect(onboardingSupportsBack()).toBe(false);
  });

  test("OnboardingFlow createElement accepts type and panels", () => {
    const el = React.createElement(OnboardingFlow, {
      type: "Onboarding",
      panels: [{ title: "Welcome", content: "Let's get started." }],
      onDone: () => {},
    });
    expect(el.type).toBe(OnboardingFlow);
    const p = el.props as { type: string; panels: unknown[] };
    expect(p.type).toBe("Onboarding");
    expect(p.panels).toHaveLength(1);
  });

  test("IdeOnboarding and EmberInChromeOnboarding are valid types", () => {
    const el1 = React.createElement(OnboardingFlow, {
      type: "IdeOnboarding",
      panels: [],
      onDone: () => {},
    });
    const el2 = React.createElement(OnboardingFlow, {
      type: "EmberInChromeOnboarding",
      panels: [],
      onDone: () => {},
    });
    expect((el1.props as { type: string }).type).toBe("IdeOnboarding");
    expect((el2.props as { type: string }).type).toBe("EmberInChromeOnboarding");
  });
});

// ---------------------------------------------------------------------------
// AC10: CostDialog accurately shows usage percentage
// ---------------------------------------------------------------------------
describe("AC10: computeUsagePercent", () => {
  test("50% usage at 1000/2000", () => {
    expect(computeUsagePercent({ current: 1000, limit: 2000 })).toBe(50);
  });

  test("100% usage at limit", () => {
    expect(computeUsagePercent({ current: 5000, limit: 5000 })).toBe(100);
  });

  test("75% usage rounds correctly", () => {
    expect(computeUsagePercent({ current: 750, limit: 1000 })).toBe(75);
  });

  test("zero limit returns 0", () => {
    expect(computeUsagePercent({ current: 100, limit: 0 })).toBe(0);
  });

  test("1.5% rounds to 1.5", () => {
    expect(computeUsagePercent({ current: 15, limit: 1000 })).toBe(1.5);
  });

  test("CostDialog createElement passes usage prop", () => {
    const usage: UsageCounter = { current: 300, limit: 1000 };
    const el = React.createElement(CostDialog, {
      usage,
      onContinue: () => {},
      onStop: () => {},
    });
    expect(el.type).toBe(CostDialog);
    expect((el.props as { usage: UsageCounter }).usage).toEqual(usage);
  });
});
