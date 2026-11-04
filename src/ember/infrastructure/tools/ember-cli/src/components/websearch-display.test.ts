// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Blind test W26: a WebSearch result showed as one huge JSON blob that pushed the answer away.
import { test, expect } from "bun:test";
import { formatToolResultForDisplay } from "./tool-result-renderers.ts";

test("a WebSearch result shows a count and one title — url line per hit", () => {
  const raw = JSON.stringify({
    query: "2018 world cup",
    results: [
      { content: [{ url: "https://a.example/x", title: "Final - A", description: "long text" }] },
      { content: [{ url: "https://b.example/y", title: "Recap - B" }] },
      "Sources: Remember to cite the URLs above in your response.",
    ],
  });
  expect(formatToolResultForDisplay(raw)).toBe(
    '2 results for "2018 world cup"\nFinal - A — https://a.example/x\nRecap - B — https://b.example/y',
  );
});

test("an empty WebSearch says so", () => {
  expect(formatToolResultForDisplay(JSON.stringify({ query: "zz", results: ["No results found."] }))).toBe('No results for "zz"');
});
