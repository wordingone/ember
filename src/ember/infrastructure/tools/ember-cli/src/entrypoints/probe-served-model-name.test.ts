// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { test, expect } from "bun:test";
import { probeServedModelName } from "./process-entry.ts";

const fake = (body: unknown, ok = true) =>
  (async () => ({ ok, json: async () => body })) as unknown as typeof fetch;

test("reads the first model id and drops .gguf", async () => {
  expect(await probeServedModelName("http://h:1", fake({ data: [{ id: "models/Qwen3.8-27B-UD-Q4_K_XL.gguf" }] })))
    .toBe("Qwen3.8-27B-UD-Q4_K_XL");
});
test("undefined on error, empty list, or non-ok", async () => {
  expect(await probeServedModelName("http://h:1", fake({ data: [] }))).toBeUndefined();
  expect(await probeServedModelName("http://h:1", fake({}, false))).toBeUndefined();
  const boom = (async () => { throw new Error("down"); }) as unknown as typeof fetch;
  expect(await probeServedModelName("http://h:1", boom)).toBeUndefined();
});
test("live server on 18810 if up", async () => {
  const name = await probeServedModelName("http://127.0.0.1:18810");
  if (name !== undefined) expect(name).toContain("Qwen");
});
