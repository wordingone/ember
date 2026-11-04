// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// #2380 S43: ember created tools/ember-cli/state/activity-feed-tailpoll-debug.jsonl inside the
// user's working directory. In open-weights mode the activity feed keeps its own files under
// EMBER_HOME and does not write the per-tick diagnostic unless asked.
import { afterEach, describe, expect, it } from "bun:test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { activityStateDir, startActivityFeed, type ActivityFeedHandle } from "./activity-feed.ts";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const dirs: string[] = [];
let handle: ActivityFeedHandle | undefined;
afterEach(() => {
  handle?.stop();
  handle = undefined;
  for (const d of dirs.splice(0)) fs.rmSync(d, { recursive: true, force: true });
});
function tmp(prefix: string): string {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), prefix));
  dirs.push(d);
  return d;
}
function listAll(root: string, dir: string = root, out: string[] = []): string[] {
  for (const name of fs.readdirSync(dir)) {
    const p = path.join(dir, name);
    if (fs.statSync(p).isDirectory()) listAll(root, p, out); else out.push(path.relative(root, p));
  }
  return out;
}

describe("activity feed state location (#2380 S43)", () => {
  it("open-weights mode keeps state under EMBER_HOME; the Ember repo keeps tools/ember-cli/state", () => {
    expect(activityStateDir("C:\\proj", { EMBER_OPEN_WEIGHTS_ACTIVE: "1", EMBER_HOME: "C:\\home\\.ember" }))
      .toBe(path.join("C:\\home\\.ember", "state"));
    expect(activityStateDir("C:\\proj", { EMBER_OPEN_WEIGHTS: "1", EMBER_HOME: "C:\\h" })).toBe(path.join("C:\\h", "state"));
    expect(activityStateDir("C:\\repo", {})).toBe(path.join("C:\\repo", "tools", "ember-cli", "state"));
  });

  it("a feed started in a user's project leaves nothing in the project directory", async () => {
    const project = tmp("ember-feed-proj-");
    const home = tmp("ember-feed-home-");
    handle = startActivityFeed({
      repoRoot: project,
      env: { EMBER_OPEN_WEIGHTS_ACTIVE: "1", EMBER_HOME: home, EMBER_HEADLESS_CAPTURE: "" },
    });
    await sleep(1500);
    handle.stop();
    handle = undefined;
    await sleep(100);
    expect(listAll(project)).toEqual([]);
    expect(fs.existsSync(path.join(project, "tools"))).toBe(false);
    // and the per-tick diagnostic is not written at all unless asked for
    expect(listAll(home).filter((f) => f.includes("tailpoll"))).toEqual([]);
  }, 10_000);

  it("the diagnostic is available on request, and then lands under EMBER_HOME", async () => {
    const project = tmp("ember-feed-proj-");
    const home = tmp("ember-feed-home-");
    handle = startActivityFeed({
      repoRoot: project,
      env: { EMBER_OPEN_WEIGHTS_ACTIVE: "1", EMBER_HOME: home, EMBER_ACTIVITY_TAILPOLL_DEBUG: "1" },
    });
    await sleep(800);
    handle.stop();
    handle = undefined;
    await sleep(100);
    expect(listAll(project)).toEqual([]);
    expect(listAll(home)).toContain(path.join("state", "activity-feed-tailpoll-debug.jsonl"));
  }, 10_000);
});
