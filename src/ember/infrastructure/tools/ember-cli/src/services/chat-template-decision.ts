// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// services/chat-template-decision.ts -- decide, by measurement, whether a pulled
// model should run with one of avir-cli's fixed chat templates instead of the
// template embedded in its GGUF.
//
// avir-cli ships three fixed Jinja templates (qwen35, qwen36, gemma4; copied
// unmodified into ../chat-templates/): enable_thinking history suppression,
// an is_error attribute on tool responses, and preserve_thinking.  They are only
// worth passing (`--chat-template-file`) when the model's own template actually
// fails the thing an agent harness needs: a tool-call round trip.
//
// Decision (pure, unit-tested, see decideTemplate):
//   - no fixed template for the GGUF architecture      -> keep embedded
//   - embedded template passes the tool-call probe      -> keep embedded
//   - embedded FAILED THE TEMPLATE (render error)       -> adopt the fixed template iff it passes
//   - embedded rendered fine but the model did not call -> INCONCLUSIVE, keep embedded (a model that
//     the tool                                             declines to call a tool is not a template fault)
// Both probe outcomes are recorded either way.

import { dirname, join } from "node:path";
import { chat } from "./llama-harness.ts";

export type FixedTemplate = "qwen35" | "qwen36" | "gemma4";

export const TEMPLATE_DIR = join(dirname(import.meta.path), "..", "chat-templates");

export function templatePath(t: FixedTemplate): string {
  return join(TEMPLATE_DIR, `${t}_chat_template.jinja`);
}

/** Which fixed template, if any, belongs to a model.  `arch` is the GGUF
 * general.architecture.  avir's qwen35 file is the older Qwen 3.5 template;
 * its qwen36 file is a superset (preserve_thinking, is_error) used for every later
 * qwen35-architecture model (avir purged 3.5 references: git 3c8901e3). */
export function templateFor(arch: string | null, nameHint: string): FixedTemplate | null {
  if (!arch) return null;
  if (/^qwen35/.test(arch)) return /qwen-?3[._-]?5(?![0-9])/i.test(nameHint) ? "qwen35" : "qwen36";
  if (/^gemma4/.test(arch)) return "gemma4";
  return null;
}

export type ProbeStage = "render" | "tool-call" | "pass";

export interface ToolProbeResult {
  ok: boolean;
  /** Where it failed: "render" = the template itself broke (HTTP error / jinja exception),
   * "tool-call" = rendered but the model produced no parseable tool call, "pass". */
  stage: ProbeStage;
  detail: string;
}

const TOOLS = [{
  type: "function",
  function: { name: "get_weather", description: "Get the current weather for a city.", parameters: { type: "object", properties: { city: { type: "string" } }, required: ["city"] } },
}];

/** Two-step probe against a running llama-server:
 *  1. /apply-template with a full tool round trip in the history (system, user, assistant tool_call,
 *     tool result, user) -- a template that cannot render this is broken for agent use.
 *  2. a real completion with tools offered; it must come back as a parseable tool call. */
export async function toolCallProbe(url: string): Promise<ToolProbeResult> {
  const history = [
    { role: "system", content: "You are a helpful assistant." },
    { role: "user", content: "What is the weather in Paris?" },
    { role: "assistant", content: "", tool_calls: [{ id: "call_1", type: "function", function: { name: "get_weather", arguments: JSON.stringify({ city: "Paris" }) } }] },
    { role: "tool", tool_call_id: "call_1", content: "18C and cloudy" },
    { role: "user", content: "And in Rome?" },
  ];
  const ar = await fetch(`${url}/apply-template`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ messages: history, tools: TOOLS }),
  }).catch((e: Error) => e);
  if (ar instanceof Error) return { ok: false, stage: "render", detail: `apply-template request failed: ${ar.message}` };
  if (!ar.ok) return { ok: false, stage: "render", detail: `apply-template HTTP ${ar.status}: ${(await ar.text()).slice(0, 200)}` };
  const rendered = ((await ar.json().catch(() => ({}))) as { prompt?: string }).prompt ?? "";
  if (!rendered.includes("Paris") || !rendered.includes("18C")) return { ok: false, stage: "render", detail: "tool call / tool result missing from the rendered prompt" };

  const r = await chat(url, {
    messages: [{ role: "user", content: "What is the weather in Paris? Use the get_weather tool." }],
    tools: TOOLS, tool_choice: "auto", max_tokens: 1024, temperature: 0, cache_prompt: false,
  });
  if (!r.ok) return { ok: false, stage: "render", detail: `completion HTTP ${r.status}: ${r.text.slice(0, 200)}` };
  const call = r.toolCalls[0];
  if (!call || call.name !== "get_weather") return { ok: false, stage: "tool-call", detail: `no get_weather tool call (finish_reason ${r.finishReason}, content ${JSON.stringify(r.text.slice(0, 80))})` };
  try {
    const a = JSON.parse(call.arguments) as { city?: string };
    if (!/paris/i.test(a.city ?? "")) return { ok: false, stage: "tool-call", detail: `tool call arguments lack the city: ${call.arguments.slice(0, 80)}` };
  } catch { return { ok: false, stage: "tool-call", detail: `tool call arguments are not JSON: ${call.arguments.slice(0, 80)}` }; }
  return { ok: true, stage: "pass", detail: `get_weather(${call.arguments})` };
}

export interface TemplateDecision {
  use: boolean;
  template: FixedTemplate | null;
  reason: string;
  /** True when a fixed template was probed although the architecture did not select one. */
  forced?: boolean;
  embeddedProbe?: ToolProbeResult;
  fixedProbe?: ToolProbeResult;
  at: string;
}

export function decideTemplate(p: { template: FixedTemplate | null; arch: string | null; embeddedProbe?: ToolProbeResult; fixedProbe?: ToolProbeResult; forced?: boolean; at?: string }): TemplateDecision {
  const at = p.at ?? new Date().toISOString();
  const base = { template: p.template, at, ...(p.embeddedProbe ? { embeddedProbe: p.embeddedProbe } : {}), ...(p.fixedProbe ? { fixedProbe: p.fixedProbe } : {}), ...(p.forced ? { forced: true } : {}) };
  if (!p.template) return { ...base, use: false, reason: `no avir fixed template for architecture ${p.arch ?? "unknown"}; embedded template kept` };
  const e = p.embeddedProbe;
  if (!e) return { ...base, use: false, reason: "embedded template was not probed; embedded kept" };
  if (e.ok) {
    return { ...base, use: false, reason: `embedded template passed the tool-call probe${p.fixedProbe ? `; fixed ${p.template} ${p.fixedProbe.ok ? "also passes" : "fails (" + p.fixedProbe.stage + ")"}` : ""}; embedded kept` };
  }
  if (e.stage === "tool-call") return { ...base, use: false, reason: `INCONCLUSIVE: embedded template rendered but the model made no usable tool call (${e.detail}); not a template fault, embedded kept` };
  if (!p.fixedProbe) return { ...base, use: false, reason: `embedded template failed to render (${e.detail}) and fixed ${p.template} was not probed; embedded kept` };
  if (p.fixedProbe.ok) return { ...base, use: true, reason: `embedded template failed (${e.stage}: ${e.detail}); fixed ${p.template} passes the same probe` };
  return { ...base, use: false, reason: `embedded template failed (${e.stage}) and fixed ${p.template} also failed (${p.fixedProbe.stage}: ${p.fixedProbe.detail}); embedded kept` };
}
