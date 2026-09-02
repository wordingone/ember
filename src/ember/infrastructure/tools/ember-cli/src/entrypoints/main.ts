// entrypoints/main.ts — compiled binary entry point.
// Sets up global error handlers, then delegates to process-entry.ts::main().
// This file is what `bun build --compile` compiles into the standalone binary.
// Bundle: entrypoints/main.ts (lines 323519–end)

// ---------------------------------------------------------------------------
// Uncaught error handlers (installed before anything else runs)
// ---------------------------------------------------------------------------

function handleUncaught(err: unknown): void {
  const msg = err instanceof Error
    ? `${err.name}: ${err.message}\n${err.stack ?? ""}`
    : String(err);
  process.stderr.write(`[ember] uncaught exception:\n${msg}\n`);
  process.exit(1);
}

function handleRejection(reason: unknown): void {
  const msg = reason instanceof Error
    ? `${reason.name}: ${reason.message}\n${reason.stack ?? ""}`
    : String(reason);
  process.stderr.write(`[ember] unhandled rejection:\n${msg}\n`);
  process.exit(1);
}

process.on("uncaughtException",  handleUncaught);
process.on("unhandledRejection", handleRejection);

// ---------------------------------------------------------------------------
// boot — entry gate; allows test injection via opts.mainFn
// ---------------------------------------------------------------------------

export interface BootOptions {
  /** Override the main function (used in tests to bypass full boot). */
  mainFn?: () => Promise<void>;
}

export async function boot(opts: BootOptions = {}): Promise<void> {
  if (opts.mainFn) {
    await opts.mainFn();
    return;
  }
  const { main } = await import("./process-entry.ts");
  await main();
}

// ---------------------------------------------------------------------------
// Top-level boot call — executes when the binary starts
// ---------------------------------------------------------------------------

await boot();
