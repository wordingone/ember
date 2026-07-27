// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// services/custody-bindings.ts — machine-local root-binding store for `/custody set`.
//
// Persists logical-root-id -> machine-path mappings so a per-machine path never leaks
// into tracked output (manifests/ember-01-custody/root-spec.json's `path_policy`:
// "logical root IDs in tracked output; machine paths supplied at execution"). The store
// lives at `<repoRoot>/.ember/root-bindings.json`, gitignored (`.ember/`), and is
// read-merge-written so a second `set` call never clobbers a previously-persisted
// binding for a different root_id.
//
// fs is fully dependency-injected (readFileSync/writeFileSync/existsSync/mkdirSync) so
// tests never touch the real filesystem -- mirrors the injectable-deps convention used
// throughout services/ (e.g. services/compaction.ts's AutocompactDeps).

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

// ---------------------------------------------------------------------------
// Shapes
// ---------------------------------------------------------------------------

export interface RootBinding {
  root_id: string;
  machine_path: string;
  binding_env: string;
}

export interface RootBindingsStore {
  roots: Record<string, RootBinding>;
}

export interface CustodyBindingsDeps {
  existsSync?: (path: string) => boolean;
  readFileSync?: (path: string) => string;
  writeFileSync?: (path: string, data: string) => void;
  mkdirSync?: (path: string) => void;
}

function resolveDeps(deps: CustodyBindingsDeps): Required<CustodyBindingsDeps> {
  return {
    existsSync: deps.existsSync ?? existsSync,
    readFileSync: deps.readFileSync ?? ((p: string) => readFileSync(p, "utf-8")),
    writeFileSync: deps.writeFileSync ?? ((p: string, data: string) => writeFileSync(p, data, "utf-8")),
    mkdirSync: deps.mkdirSync ?? ((p: string) => void mkdirSync(p, { recursive: true })),
  };
}

/** Path to the machine-local binding store for a given repo root. Exported so callers
 *  (e.g. tests, `/custody status`) never hand-roll the join. */
export function rootBindingsStorePath(repoRoot: string): string {
  return join(repoRoot, ".ember", "root-bindings.json");
}

/** Env var name a logical root id maps to, mirroring root-spec.json's `binding` field
 *  convention (EMBER_<ROOT_ID_UPPER_SNAKE>_ROOT is NOT assumed here -- the exact binding
 *  is supplied by the caller / root-spec, not derived). This helper only covers the
 *  fallback case where no explicit binding_env is given. */
export function deriveBindingEnvName(rootId: string): string {
  return `EMBER_${rootId.replace(/[^a-zA-Z0-9]+/g, "_").toUpperCase()}_ROOT`;
}

// ---------------------------------------------------------------------------
// Read
// ---------------------------------------------------------------------------

/** Reads the binding store, fail-open: a missing or unreadable/malformed store returns
 *  `{ roots: {} }` rather than throwing -- `/custody status` must never break when no
 *  binding has ever been set. */
export function readRootBindingsStore(
  repoRoot: string,
  deps: CustodyBindingsDeps = {},
): RootBindingsStore {
  const d = resolveDeps(deps);
  const storePath = rootBindingsStorePath(repoRoot);
  if (!d.existsSync(storePath)) return { roots: {} };

  try {
    const raw = d.readFileSync(storePath);
    const parsed = JSON.parse(raw) as unknown;
    if (
      parsed &&
      typeof parsed === "object" &&
      "roots" in parsed &&
      typeof (parsed as { roots: unknown }).roots === "object" &&
      (parsed as { roots: unknown }).roots !== null
    ) {
      return { roots: { ...(parsed as RootBindingsStore).roots } };
    }
    return { roots: {} };
  } catch {
    // Malformed JSON / unreadable file -- fail open to "no bindings", never crash a
    // read-only status query.
    return { roots: {} };
  }
}

// ---------------------------------------------------------------------------
// Parse (fail-closed validation for `set`)
// ---------------------------------------------------------------------------

export class MalformedBindingArgError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "MalformedBindingArgError";
  }
}

/** Parses a `root_id=path` argument. Fails CLOSED (throws MalformedBindingArgError) on
 *  any shape that isn't exactly one `=`-delimited pair with non-empty root_id and path --
 *  never silently guesses or drops the write. */
export function parseBindingArg(arg: string): { rootId: string; machinePath: string } {
  const trimmed = arg.trim();
  const eqIndex = trimmed.indexOf("=");
  if (eqIndex <= 0 || eqIndex === trimmed.length - 1) {
    throw new MalformedBindingArgError(
      `malformed binding argument ${JSON.stringify(arg)} -- expected shape root_id=path`,
    );
  }
  const rootId = trimmed.slice(0, eqIndex).trim();
  const machinePath = trimmed.slice(eqIndex + 1).trim();
  if (!rootId || !machinePath) {
    throw new MalformedBindingArgError(
      `malformed binding argument ${JSON.stringify(arg)} -- expected shape root_id=path`,
    );
  }
  if (!/^[a-zA-Z0-9][a-zA-Z0-9._-]*$/.test(rootId)) {
    throw new MalformedBindingArgError(
      `malformed root_id ${JSON.stringify(rootId)} in argument ${JSON.stringify(arg)}`,
    );
  }
  return { rootId, machinePath };
}

// ---------------------------------------------------------------------------
// Write (read-merge-write)
// ---------------------------------------------------------------------------

/** Persists one binding into the store: reads whatever exists (fail-open to empty),
 *  merges in the new/updated `root_id` entry, and writes the whole store back --
 *  NEVER clobbers bindings for other root_ids. Creates `.ember/` if absent. */
export function writeRootBinding(
  repoRoot: string,
  rootId: string,
  machinePath: string,
  deps: CustodyBindingsDeps = {},
  bindingEnv: string = deriveBindingEnvName(rootId),
): RootBinding {
  const d = resolveDeps(deps);
  const storePath = rootBindingsStorePath(repoRoot);
  const storeDir = dirname(storePath);

  const existing = readRootBindingsStore(repoRoot, deps);
  const binding: RootBinding = { root_id: rootId, machine_path: machinePath, binding_env: bindingEnv };
  const next: RootBindingsStore = {
    roots: { ...existing.roots, [rootId]: binding },
  };

  if (!d.existsSync(storeDir)) d.mkdirSync(storeDir);
  d.writeFileSync(storePath, JSON.stringify(next, null, 2) + "\n");

  return binding;
}
