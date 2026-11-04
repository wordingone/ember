// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// Script entry for the detached model-server reaper (see server-reaper.ts).  Kept separate from the
// CLI entry so the reaper loads only the lease modules, not the whole application.
import { reaperMain } from "./server-reaper.ts";

await reaperMain(Number(process.argv[2]), process.argv[3] ?? "");
process.exit(0);
