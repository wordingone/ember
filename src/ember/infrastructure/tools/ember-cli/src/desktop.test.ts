// Tests for /desktop (/app): platform gate (AC1), cloud gate (AC2),
// renders handoff on supported platforms (AC3), aliases (AC4).

import { describe, it, expect, beforeEach } from "bun:test";
import {
  desktopCommand,
  setDesktopCommandDeps,
  resetDesktopCommandDeps,
  isSupportedPlatform,
} from "./desktop.ts";
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
// AC1: Absent on Linux and non-x64 Windows
// ---------------------------------------------------------------------------

describe("desktopCommand — AC1", () => {
  beforeEach(() => resetDesktopCommandDeps());

  it("AC1: disabled on Linux", () => {
    setDesktopCommandDeps({
      isCloudSurface: () => true,
      getPlatform: () => "linux",
      getArch: () => "x64",
    });
    expect(desktopCommand.isEnabled()).toBe(false);
  });

  it("AC1: disabled on Windows arm64", () => {
    setDesktopCommandDeps({
      isCloudSurface: () => true,
      getPlatform: () => "win32",
      getArch: () => "arm64",
    });
    expect(desktopCommand.isEnabled()).toBe(false);
  });

  it("AC1: disabled on FreeBSD", () => {
    setDesktopCommandDeps({
      isCloudSurface: () => true,
      getPlatform: () => "freebsd",
      getArch: () => "x64",
    });
    expect(desktopCommand.isEnabled()).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// AC2: Absent when not cloud surface
// ---------------------------------------------------------------------------

describe("desktopCommand — AC2", () => {
  beforeEach(() => resetDesktopCommandDeps());

  it("AC2: disabled when not cloud surface (macOS)", () => {
    setDesktopCommandDeps({
      isCloudSurface: () => false,
      getPlatform: () => "darwin",
      getArch: () => "arm64",
    });
    expect(desktopCommand.isEnabled()).toBe(false);
  });

  it("AC2: disabled when not cloud surface (win32 x64)", () => {
    setDesktopCommandDeps({
      isCloudSurface: () => false,
      getPlatform: () => "win32",
      getArch: () => "x64",
    });
    expect(desktopCommand.isEnabled()).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// AC3: Renders DesktopHandoff on supported platforms
// ---------------------------------------------------------------------------

describe("desktopCommand — AC3", () => {
  beforeEach(() => resetDesktopCommandDeps());

  it("AC3: renders on macOS", async () => {
    let handoffCalled = false;
    setDesktopCommandDeps({
      isCloudSurface: () => true,
      getPlatform: () => "darwin",
      getArch: () => "arm64",
      renderDesktopHandoff: () => { handoffCalled = true; },
    });
    await desktopCommand.execute("", makeContext());
    expect(handoffCalled).toBe(true);
  });

  it("AC3: renders on Windows x64", async () => {
    let handoffCalled = false;
    setDesktopCommandDeps({
      isCloudSurface: () => true,
      getPlatform: () => "win32",
      getArch: () => "x64",
      renderDesktopHandoff: () => { handoffCalled = true; },
    });
    await desktopCommand.execute("", makeContext());
    expect(handoffCalled).toBe(true);
  });

  it("AC3: onDone is passed through to renderDesktopHandoff", async () => {
    const cap = { onDone: null as ((r?: string) => void) | null };
    setDesktopCommandDeps({
      isCloudSurface: () => true,
      getPlatform: () => "darwin",
      getArch: () => "arm64",
      renderDesktopHandoff: (onDone) => { cap.onDone = onDone; },
    });

    let doneCalled = false;
    const ctx = makeContext({ onDone: () => { doneCalled = true; } });
    await desktopCommand.execute("", ctx);

    cap.onDone?.();
    expect(doneCalled).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// AC4: /desktop and /app invoke the same command (same aliases)
// ---------------------------------------------------------------------------

describe("desktopCommand — AC4", () => {
  it("AC4: name is desktop", () => expect(desktopCommand.name).toBe("desktop"));

  it("AC4: aliases includes 'app'", () => {
    expect(desktopCommand.aliases).toContain("app");
  });

  it("AC4: execute same function for /app as /desktop (same object)", () => {
    // Both /app and /desktop map to desktopCommand — registry handles alias resolution
    // The command object is the same regardless of which alias was used
    expect(desktopCommand.name).toBe("desktop");
    expect(desktopCommand.aliases).toContain("app");
  });
});

// ---------------------------------------------------------------------------
// isSupportedPlatform helper
// ---------------------------------------------------------------------------

describe("isSupportedPlatform", () => {
  it("true on darwin regardless of arch", () => {
    expect(isSupportedPlatform("darwin", "arm64")).toBe(true);
    expect(isSupportedPlatform("darwin", "x64")).toBe(true);
  });

  it("true on win32 x64 only", () => {
    expect(isSupportedPlatform("win32", "x64")).toBe(true);
    expect(isSupportedPlatform("win32", "arm64")).toBe(false);
    expect(isSupportedPlatform("win32", "ia32")).toBe(false);
  });

  it("false on linux", () => {
    expect(isSupportedPlatform("linux", "x64")).toBe(false);
  });

  it("false on freebsd", () => {
    expect(isSupportedPlatform("freebsd", "x64")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Command structure
// ---------------------------------------------------------------------------

describe("desktopCommand structure", () => {
  it("type is local-jsx", () => expect(desktopCommand.type).toBe("local-jsx"));
  it("availability includes cloud", () => {
    expect(desktopCommand.availability).toContain("cloud");
  });
});
