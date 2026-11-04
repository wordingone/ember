// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Tool-produced images (Computer screenshots) must reach llama-server as
// image_url data URIs when a vision projector is loaded, and be dropped with a
// note when it is not (a text-only server rejects image_url parts).
import { afterEach, describe, expect, test } from "bun:test";
import { convertMessagesToOpenAI } from "./api-openai-adapter.ts";

const msgs = [
  { role: "assistant" as const, content: [{ type: "tool_use" as const, id: "c1", name: "Computer", input: {} }] },
  {
    role: "user" as const,
    content: [{ type: "tool_result" as const, tool_use_id: "c1", content: "Screenshot saved", images: [{ media_type: "image/png", data: "QUJD" }] }],
  },
];

afterEach(() => {
  delete process.env["EMBER_VISION"];
});

describe("tool_result images", () => {
  test("EMBER_VISION=1: tool message stays text, a following user message carries the image_url data URI", () => {
    process.env["EMBER_VISION"] = "1";
    const out = convertMessagesToOpenAI(msgs);
    const tool = out.find((m) => m.role === "tool")!;
    expect(tool.content).toBe("Screenshot saved");
    const img = out[out.indexOf(tool) + 1]!;
    expect(img.role).toBe("user");
    const parts = img.content as Array<{ type: string; image_url?: { url: string } }>;
    expect(parts.find((p) => p.type === "image_url")!.image_url!.url).toBe("data:image/png;base64,QUJD");
  });

  test("no vision projector: image dropped, note appended, no image_url part sent", () => {
    const out = convertMessagesToOpenAI(msgs);
    expect(JSON.stringify(out)).not.toContain("image_url");
    expect(out.find((m) => m.role === "tool")!.content as string).toContain("no vision projector");
  });

  test("a plain user image block still becomes image_url (unchanged behavior)", () => {
    const out = convertMessagesToOpenAI([{ role: "user", content: [{ type: "image", source: { media_type: "image/jpeg", data: "WFla" } }] }]);
    expect(JSON.stringify(out)).toContain("data:image/jpeg;base64,WFla");
  });
});
