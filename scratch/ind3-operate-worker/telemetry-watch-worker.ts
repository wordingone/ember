// telemetry-watch-worker.ts -- IND-3 OPERATE producer helper (C-IND).
//
// A minimal, real, CPU-only operator surface built around the ACTUAL
// tools/ember-cli/src/services/telemetry-watch.ts service (unmodified) --
// the same mechanism the live `/watch` slash command uses. This process is
// the thing that gets LAUNCHED / TORN DOWN / INTERRUPTED-AND-RESUMED for
// the IND-3 OPERATE receipts: no GPU, no model server, just the real
// telemetry tail-poller running as its own OS process so it can be
// genuinely activated and deactivated (not merely called as a function).
//
// Protocol (all file-based -- no signals, cross-platform, matches this
// repo's existing planned-outage.json marker convention):
//   argv: <channelPath> <heartbeatPath> <stopMarkerPath>
//   1. Starts the real startTelemetryWatch() against channelPath.
//   2. Writes {pid, ts, status:"ready"} to heartbeatPath once running.
//   3. Polls for stopMarkerPath every 250ms; on seeing it, calls
//      handle.stop() (real teardown of the real watcher), writes
//      {pid, ts, status:"stopped"} to heartbeatPath, and exits 0. This is
//      the GRACEFUL stop path (the "teardown" leg).
//   4. If the process is killed directly (taskkill /F, no marker file) --
//      that is the "interrupted_resume" leg's ungraceful stop; there is no
//      graceful handler for it by design, since the whole point of that leg
//      is to prove the system survives an UNPLANNED termination and can be
//      relaunched, not that this process catches SIGKILL (it cannot).

import { pathToFileURL } from "node:url";
import { resolve } from "node:path";
import { writeFileSync, existsSync } from "node:fs";

async function main(): Promise<void> {
  const [channelPathArg, heartbeatPathArg, stopMarkerPathArg] = process.argv.slice(2);
  if (!channelPathArg || !heartbeatPathArg || !stopMarkerPathArg) {
    process.stderr.write("usage: telemetry-watch-worker.ts <channelPath> <heartbeatPath> <stopMarkerPath>\n");
    process.exit(1);
  }
  const cliSrc = resolve(__dirname, "..", "..", "tools", "ember-cli", "src");
  const serviceUrl = pathToFileURL(resolve(cliSrc, "services", "telemetry-watch.ts")).href;
  const { startTelemetryWatch } = await import(serviceUrl);

  const handle = startTelemetryWatch({ channelPath: resolve(channelPathArg) });

  writeFileSync(
    heartbeatPathArg,
    JSON.stringify({ pid: process.pid, ts: new Date().toISOString(), status: "ready" }),
    "utf-8",
  );

  const pollStop = setInterval(() => {
    if (existsSync(stopMarkerPathArg)) {
      clearInterval(pollStop);
      handle.stop();
      writeFileSync(
        heartbeatPathArg,
        JSON.stringify({ pid: process.pid, ts: new Date().toISOString(), status: "stopped" }),
        "utf-8",
      );
      process.exit(0);
    }
  }, 250);
}

main().catch((err) => {
  process.stderr.write(`telemetry-watch-worker.ts failed: ${err instanceof Error ? err.stack ?? err.message : String(err)}\n`);
  process.exit(1);
});
