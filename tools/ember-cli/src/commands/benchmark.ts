// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// commands/benchmark.ts — /benchmark status|list (default: list) + /benchmark run <benchmark_id>.
// Read-only exposure of manifests/ember-01-custody/benchmark-registry.json (schema
// ember-01-benchmark-registry-v1). No new backend logic, no mutation, no harness
// execution -- 'run' truthfully reports "not_executed: harness is <harness_status>"
// for every row (no real harness is wired yet) rather than faking a result.
//
// Repo-root resolution mirrors commands/custody.ts (resolveEmberRepoRootOrCwd), so the
// registry path resolves the same way regardless of the ember-cli's launch cwd.

import type { CommandContext, RegistryCommand } from "../types/command-types.ts";
import { resolveEmberRepoRootOrCwd } from "../utils/repo-root.ts";
import { readFileSync } from "fs";
import { join } from "path";

// ---------------------------------------------------------------------------
// Registry shape (manifests/ember-01-custody/benchmark-registry.json, schema v1)
// ---------------------------------------------------------------------------

export interface BenchmarkRow {
  benchmark_id: string;
  display_name: string;
  version: string;
  provenance_class: string;
  subject_requirement: string;
  harness_status: string;
  data_status: string;
  license_status: string;
  execution_status: string;
  subject_class: string;
  completion: boolean;
  evidence: string[];
  split: string;
  harness_path: string | null;
  harness_identity: { algorithm: string; value: string } | null;
  comparator_requirements: {
    owned_subject_required: boolean;
    borrowed_reference_role: string;
    lineage_signal_allowed: boolean;
  };
  lineage_admissibility: string;
  completion_eligibility: string;
}

export interface BenchmarkRegistry {
  authority: {
    goal_id: string;
    workstream_id: string;
    next_executed_outcome: string;
  };
  schema: string;
  direct_recovered_minimum: number;
  operator_recollection_minimum: number;
  completion_rule: string;
  benchmarks: BenchmarkRow[];
}

// ---------------------------------------------------------------------------
// Deps (injectable for testing)
// ---------------------------------------------------------------------------

interface BenchmarkCommandDeps {
  /** Injectable for tests; defaults to the real fs.readFileSync bound to the resolved
   *  registry path. Returning/throwing lets tests exercise missing/unreadable files
   *  without touching the real filesystem. */
  readRegistryFile?: (path: string) => string;
  /** Injectable for tests; defaults to `resolveEmberRepoRootOrCwd({}, "[ember] /benchmark")`. */
  resolveRepoRoot?: () => string;
  /** Injectable for tests; overrides the registry path entirely (bypasses repo-root
   *  resolution + the manifests/ember-01-custody/ convention). */
  registryPath?: string;
}

/** Default registry path convention: manifests/ember-01-custody/benchmark-registry.json
 *  relative to the resolved ember repo root. */
function _defaultRegistryPath(repoRoot: string): string {
  return join(repoRoot, "manifests", "ember-01-custody", "benchmark-registry.json");
}

function _defaultReadRegistryFile(path: string): string {
  return readFileSync(path, "utf8");
}

// ---------------------------------------------------------------------------
// Parsing -- fail CLOSED on anything short of a valid registry
// ---------------------------------------------------------------------------

export interface RegistryLoadResult {
  ok: true;
  registry: BenchmarkRegistry;
}
export interface RegistryLoadError {
  ok: false;
  error: string;
}

/** Loads + validates the benchmark registry. FAIL-CLOSED: any missing file, unreadable
 *  file, malformed JSON, or JSON that doesn't carry a `benchmarks` array of row objects
 *  with a `benchmark_id` returns `{ok: false, error}` -- never a fake-empty registry
 *  (`{benchmarks: []}`) and never a partial/guessed row. Exported (prefixed _) for
 *  direct unit testing of the parse boundary without going through execute().
 */
export function _loadBenchmarkRegistry(
  path: string,
  readFile: (path: string) => string = _defaultReadRegistryFile,
): RegistryLoadResult | RegistryLoadError {
  let raw: string;
  try {
    raw = readFile(path);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return { ok: false, error: `could not read registry at ${path}: ${msg}` };
  }

  let payload: unknown;
  try {
    payload = JSON.parse(raw);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return { ok: false, error: `registry at ${path} is not valid JSON: ${msg}` };
  }

  if (typeof payload !== "object" || payload === null) {
    return { ok: false, error: `registry at ${path} did not parse to a JSON object` };
  }
  const record = payload as Record<string, unknown>;
  const benchmarks = record["benchmarks"];
  if (!Array.isArray(benchmarks)) {
    return { ok: false, error: `registry at ${path} is missing a "benchmarks" array` };
  }

  for (let i = 0; i < benchmarks.length; i++) {
    const row = benchmarks[i];
    if (typeof row !== "object" || row === null) {
      return { ok: false, error: `registry at ${path}: benchmarks[${i}] is not an object` };
    }
    const r = row as Record<string, unknown>;
    if (typeof r["benchmark_id"] !== "string" || r["benchmark_id"].trim() === "") {
      return {
        ok: false,
        error: `registry at ${path}: benchmarks[${i}] is missing a non-empty "benchmark_id"`,
      };
    }
    if (typeof r["harness_status"] !== "string") {
      return {
        ok: false,
        error: `registry at ${path}: benchmarks[${i}] (${r["benchmark_id"]}) is missing "harness_status"`,
      };
    }
    if (typeof r["completion"] !== "boolean") {
      return {
        ok: false,
        error: `registry at ${path}: benchmarks[${i}] (${r["benchmark_id"]}) is missing boolean "completion"`,
      };
    }
  }

  return { ok: true, registry: record as unknown as BenchmarkRegistry };
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

/** Renders the per-benchmark status table. Exported for direct unit testing of the
 *  render shape without going through the command's execute() plumbing. */
export function renderBenchmarkTable(registry: BenchmarkRegistry): string {
  const header = [
    "benchmark_id",
    "harness_status",
    "data_status",
    "license_status",
    "execution_status",
    "completion",
    "completion_eligibility",
  ];
  const rows = registry.benchmarks.map((b) => [
    b.benchmark_id,
    b.harness_status,
    b.data_status,
    b.license_status,
    b.execution_status,
    String(b.completion),
    b.completion_eligibility,
  ]);

  const widths = header.map((h, i) =>
    Math.max(h.length, ...rows.map((r) => (r[i] ?? "").length)),
  );
  const fmt = (cols: string[]): string => cols.map((c, i) => c.padEnd(widths[i] ?? 0)).join("  ");

  const lines = [fmt(header), fmt(widths.map((w) => "-".repeat(w))), ...rows.map((r) => fmt(r))];
  lines.push("");
  lines.push(`${registry.benchmarks.length} benchmark(s) — schema ${registry.schema}`);
  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

/** Creates the read-only `/benchmark status|list` (default: list) + `/benchmark run
 *  <benchmark_id>` command. */
export function createBenchmarkCommand(deps: BenchmarkCommandDeps = {}): RegistryCommand {
  const doResolveRepoRoot =
    deps.resolveRepoRoot ?? (() => resolveEmberRepoRootOrCwd({}, "[ember] /benchmark"));
  const doReadRegistryFile = deps.readRegistryFile ?? _defaultReadRegistryFile;

  function resolvedRegistryPath(): string {
    return deps.registryPath ?? _defaultRegistryPath(doResolveRepoRoot());
  }

  return {
    name: "benchmark",
    description:
      "Show the benchmark registry (read-only): /benchmark status|list, /benchmark run <id>",
    isEnabled(): boolean {
      return true;
    },
    async execute(args: string, _ctx: CommandContext) {
      const parts = args.trim().split(/\s+/);
      const subcommand = parts[0] ?? "";

      // /benchmark status | list | "" -> render the full table
      if (subcommand === "status" || subcommand === "list" || subcommand === "") {
        const path = resolvedRegistryPath();
        const loaded = _loadBenchmarkRegistry(path, doReadRegistryFile);
        if (!loaded.ok) {
          return {
            type: "message" as const,
            message: `error: benchmark registry unavailable: ${loaded.error}`,
            exitCode: 1,
          };
        }
        return {
          type: "message" as const,
          message: renderBenchmarkTable(loaded.registry),
        };
      }

      // /benchmark run <benchmark_id> -> truthful not-executed report, never a fake run.
      if (subcommand === "run") {
        const benchmarkId = parts[1];
        if (!benchmarkId) {
          return {
            type: "message" as const,
            message: "usage: /benchmark run <benchmark_id>",
            exitCode: 1,
          };
        }

        const path = resolvedRegistryPath();
        const loaded = _loadBenchmarkRegistry(path, doReadRegistryFile);
        if (!loaded.ok) {
          return {
            type: "message" as const,
            message: `error: benchmark registry unavailable: ${loaded.error}`,
            exitCode: 1,
          };
        }

        const row = loaded.registry.benchmarks.find((b) => b.benchmark_id === benchmarkId);
        if (!row) {
          return {
            type: "message" as const,
            message: `error: unknown benchmark_id "${benchmarkId}"`,
            exitCode: 1,
          };
        }

        // No real harness is wired yet for any row -- report truthfully, never execute.
        return {
          type: "message" as const,
          message: `${benchmarkId}: not_executed: harness is ${row.harness_status}`,
          exitCode: 1,
        };
      }

      // Unknown subcommand -> clear usage line
      return {
        type: "message" as const,
        message: "usage: /benchmark status|list|run <benchmark_id>",
      };
    },
  };
}
