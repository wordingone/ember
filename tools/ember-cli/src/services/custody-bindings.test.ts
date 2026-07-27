// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// services/custody-bindings.test.ts — unit tests for the machine-local root-binding
// store (`/custody set`). fs is fully mocked in-memory; no real filesystem is touched.

import { describe, it, expect } from "bun:test";
import { join as pathJoin } from "node:path";
import {
  deriveBindingEnvName,
  MalformedBindingArgError,
  parseBindingArg,
  readRootBindingsStore,
  rootBindingsStorePath,
  writeRootBinding,
  type CustodyBindingsDeps,
} from "./custody-bindings.ts";

/** An in-memory fs double keyed by path -- lets a test assert exactly what got
 *  written without touching the real filesystem, and lets a later read see an
 *  earlier write's exact bytes (round-trip). */
function makeMemFs(initial: Record<string, string> = {}): {
  deps: Required<CustodyBindingsDeps>;
  files: Record<string, string>;
  dirs: Set<string>;
} {
  const files: Record<string, string> = { ...initial };
  const dirs = new Set<string>();
  const deps: Required<CustodyBindingsDeps> = {
    existsSync: (p: string) => p in files || dirs.has(p),
    readFileSync: (p: string) => {
      if (!(p in files)) throw new Error(`ENOENT: ${p}`);
      return files[p]!;
    },
    writeFileSync: (p: string, data: string) => {
      files[p] = data;
    },
    mkdirSync: (p: string) => {
      dirs.add(p);
    },
  };
  return { deps, files, dirs };
}

const REPO_ROOT = "/repo";

describe("parseBindingArg", () => {
  it("parses a well-formed root_id=path argument", () => {
    const parsed = parseBindingArg("benchmark-root=/mnt/data/bench");
    expect(parsed).toEqual({ rootId: "benchmark-root", machinePath: "/mnt/data/bench" });
  });

  it("trims surrounding whitespace", () => {
    const parsed = parseBindingArg("  benchmark-root = /mnt/data/bench  ");
    expect(parsed).toEqual({ rootId: "benchmark-root", machinePath: "/mnt/data/bench" });
  });

  it("fails closed (throws MalformedBindingArgError) with no '='", () => {
    expect(() => parseBindingArg("benchmark-root")).toThrow(MalformedBindingArgError);
  });

  it("fails closed with an empty root_id", () => {
    expect(() => parseBindingArg("=/mnt/data/bench")).toThrow(MalformedBindingArgError);
  });

  it("fails closed with an empty path", () => {
    expect(() => parseBindingArg("benchmark-root=")).toThrow(MalformedBindingArgError);
  });

  it("fails closed with an empty argument", () => {
    expect(() => parseBindingArg("")).toThrow(MalformedBindingArgError);
  });

  it("fails closed with an invalid root_id shape (path-like)", () => {
    expect(() => parseBindingArg("../escape=/mnt/data")).toThrow(MalformedBindingArgError);
  });

  it("preserves '=' characters inside the path value", () => {
    const parsed = parseBindingArg("root=/mnt/data?x=1");
    expect(parsed).toEqual({ rootId: "root", machinePath: "/mnt/data?x=1" });
  });
});

describe("deriveBindingEnvName", () => {
  it("upper-snake-cases a hyphenated root id", () => {
    expect(deriveBindingEnvName("benchmark-root")).toBe("EMBER_BENCHMARK_ROOT_ROOT");
  });
});

describe("readRootBindingsStore", () => {
  it("fails open to an empty store when the file is absent", () => {
    const { deps } = makeMemFs();
    const store = readRootBindingsStore(REPO_ROOT, deps);
    expect(store).toEqual({ roots: {} });
  });

  it("fails open to an empty store on malformed JSON", () => {
    const { deps } = makeMemFs({
      [rootBindingsStorePath(REPO_ROOT)]: "{ not valid json",
    });
    const store = readRootBindingsStore(REPO_ROOT, deps);
    expect(store).toEqual({ roots: {} });
  });

  it("fails open to an empty store when the JSON lacks a `roots` object", () => {
    const { deps } = makeMemFs({
      [rootBindingsStorePath(REPO_ROOT)]: JSON.stringify({ notRoots: true }),
    });
    const store = readRootBindingsStore(REPO_ROOT, deps);
    expect(store).toEqual({ roots: {} });
  });

  it("reads back a well-formed store", () => {
    const seeded = {
      roots: {
        "benchmark-root": {
          root_id: "benchmark-root",
          machine_path: "/mnt/data/bench",
          binding_env: "EMBER_BENCHMARK_ROOT",
        },
      },
    };
    const { deps } = makeMemFs({
      [rootBindingsStorePath(REPO_ROOT)]: JSON.stringify(seeded),
    });
    const store = readRootBindingsStore(REPO_ROOT, deps);
    expect(store).toEqual(seeded);
  });
});

describe("writeRootBinding", () => {
  it("writes a binding and round-trips it back via a read", () => {
    const { deps, files } = makeMemFs();

    const written = writeRootBinding(REPO_ROOT, "benchmark-root", "/mnt/data/bench", deps);
    expect(written).toEqual({
      root_id: "benchmark-root",
      machine_path: "/mnt/data/bench",
      binding_env: "EMBER_BENCHMARK_ROOT_ROOT",
    });

    // Store file exists at the documented path.
    const storePath = rootBindingsStorePath(REPO_ROOT);
    expect(files[storePath]).toBeDefined();

    // Round-trip: a fresh read sees exactly what was written.
    const readBack = readRootBindingsStore(REPO_ROOT, deps);
    expect(readBack.roots["benchmark-root"]).toEqual(written);
  });

  it("creates the .ember/ directory when absent", () => {
    const { deps, dirs } = makeMemFs();
    writeRootBinding(REPO_ROOT, "benchmark-root", "/mnt/data/bench", deps);
    expect(dirs.has(pathJoin(REPO_ROOT, ".ember"))).toBe(true);
  });

  it("read-merge-write: a second binding never clobbers an existing one for a different root_id", () => {
    const { deps } = makeMemFs();

    writeRootBinding(REPO_ROOT, "benchmark-root", "/mnt/data/bench", deps);
    writeRootBinding(REPO_ROOT, "external-data-root", "/mnt/data/external", deps);

    const store = readRootBindingsStore(REPO_ROOT, deps);
    expect(Object.keys(store.roots).sort()).toEqual(["benchmark-root", "external-data-root"]);
    expect(store.roots["benchmark-root"]?.machine_path).toBe("/mnt/data/bench");
    expect(store.roots["external-data-root"]?.machine_path).toBe("/mnt/data/external");
  });

  it("re-setting the same root_id overwrites only that entry", () => {
    const { deps } = makeMemFs();

    writeRootBinding(REPO_ROOT, "benchmark-root", "/mnt/data/bench-v1", deps);
    writeRootBinding(REPO_ROOT, "external-data-root", "/mnt/data/external", deps);
    writeRootBinding(REPO_ROOT, "benchmark-root", "/mnt/data/bench-v2", deps);

    const store = readRootBindingsStore(REPO_ROOT, deps);
    expect(store.roots["benchmark-root"]?.machine_path).toBe("/mnt/data/bench-v2");
    expect(store.roots["external-data-root"]?.machine_path).toBe("/mnt/data/external");
  });

  it("accepts an explicit binding_env override", () => {
    const { deps } = makeMemFs();
    const written = writeRootBinding(
      REPO_ROOT,
      "benchmark-root",
      "/mnt/data/bench",
      deps,
      "EMBER_CUSTOM_BINDING",
    );
    expect(written.binding_env).toBe("EMBER_CUSTOM_BINDING");
  });
});
