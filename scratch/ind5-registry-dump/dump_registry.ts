// dump_registry.ts -- IND-5 comprehend_v2 producer helper (issue #88).
//
// Dumps the ACTUAL live slash-command registry (tools/ember-cli/src/
// command-registry.ts's getCommands()) as JSON to stdout, using the default
// (unmocked) dependency set -- i.e. exactly the builtin commands the CLI
// registers at real boot, with no skill-dir / plugin / MCP overrides. This
// is invoked by ind5_comprehend_producer.py's run_registry_dump() with one
// argv: the absolute path to the execution tree's ember-cli `src` dir. It
// performs a read-only import + in-memory call -- no writes, no server, no
// GPU, no network.
//
// Usage: bun run dump_registry.ts <path-to-ember-cli-src>

import { pathToFileURL } from "node:url";
import { resolve } from "node:path";

async function main(): Promise<void> {
  const cliSrcArg = process.argv[2];
  if (!cliSrcArg) {
    process.stderr.write("usage: dump_registry.ts <path-to-ember-cli-src>\n");
    process.exit(1);
  }
  const cliSrc = resolve(cliSrcArg);
  const registryUrl = pathToFileURL(resolve(cliSrc, "command-registry.ts")).href;
  const { getCommands } = await import(registryUrl);
  // cwd only affects the per-cwd skill-dir lookup, which the default deps
  // resolve to an empty array regardless of value -- any real directory is
  // fine here, and cliSrc itself is guaranteed to exist.
  const commands = await getCommands(cliSrc);
  const out = commands.map((c: { name: string; aliases?: string[] }) => ({
    name: c.name,
    aliases: c.aliases ?? [],
  }));
  process.stdout.write(JSON.stringify(out));
}

main().catch((err) => {
  process.stderr.write(`dump_registry.ts failed: ${err instanceof Error ? err.stack ?? err.message : String(err)}\n`);
  process.exit(1);
});
