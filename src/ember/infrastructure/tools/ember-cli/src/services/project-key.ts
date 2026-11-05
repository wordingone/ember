// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/project-key.ts -- a filesystem-safe directory name for a working directory.
//
// Sessions ($EMBER_HOME/sessions/<key>/) and memory ($EMBER_HOME/memory/<key>/) are both
// kept per project. The key is the path with every unsafe run replaced by "-", plus a short
// hash of the exact path so that "a b" and "a-b" (and case variants on Windows) never share
// a directory.

import { createHash } from "node:crypto";
import { resolve } from "node:path";

export function projectKey(cwd: string): string {
  const abs = resolve(cwd);
  const canonical = process.platform === "win32" ? abs.toLowerCase() : abs;
  const slug = abs
    .replace(/[^A-Za-z0-9._]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(-80)
    .replace(/^-+/, "");
  const hash = createHash("sha1").update(canonical).digest("hex").slice(0, 8);
  return `${slug === "" ? "root" : slug}-${hash}`;
}
