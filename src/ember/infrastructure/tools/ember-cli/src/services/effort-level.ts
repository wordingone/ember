// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// services/effort-level.ts -- selectable thinking level (issue #2370).
//
// The operator picks how hard the open-weights model thinks with `/effort`. The level is
// persisted in the ember home settings (`effortLevel` in settings.json) and sent on every
// model request as `chat_template_kwargs`. The Qwen3.8 chat template accepts
// `enable_thinking` (false turns thinking off) and `reasoning_effort` in low | medium |
// xhigh; any other value raises a template error, so the mapping below is the ONLY place a
// reasoning_effort value is produced.

import { readFileSync } from "node:fs";
import { getSettingsFilePathForSource, updateSettingsForSource } from "../settings.ts";

export const EFFORT_LEVELS = ["off", "low", "medium", "high", "max"] as const;
export type EffortLevel = (typeof EFFORT_LEVELS)[number];

/** Thinking on, at the model's own default (the template defaults to xhigh == "high"). */
export const DEFAULT_EFFORT_LEVEL: EffortLevel = "high";

/** `max` raises the output cap to at least this many tokens. */
export const MAX_EFFORT_MIN_OUTPUT_TOKENS = 32768;

export const EFFORT_SETTINGS_KEY = "effortLevel";

export type TemplateReasoningEffort = "low" | "medium" | "xhigh";

export interface ChatTemplateKwargs {
  enable_thinking: boolean;
  reasoning_effort?: TemplateReasoningEffort;
}

/** Parses operator text into a level; null when it is not one of the five levels. */
export function parseEffortLevel(text: string): EffortLevel | null {
  const t = text.trim().toLowerCase();
  return (EFFORT_LEVELS as readonly string[]).includes(t) ? (t as EffortLevel) : null;
}

/** Maps a level to the chat-template kwargs. off -> thinking disabled; high and max -> xhigh. */
export function chatTemplateKwargsForEffort(level: EffortLevel): ChatTemplateKwargs {
  switch (level) {
    case "off":
      return { enable_thinking: false };
    case "low":
      return { enable_thinking: true, reasoning_effort: "low" };
    case "medium":
      return { enable_thinking: true, reasoning_effort: "medium" };
    case "high":
    case "max":
      return { enable_thinking: true, reasoning_effort: "xhigh" };
  }
}

/** The output-token cap for a level: max raises it to at least 32768, others keep `base`. */
export function maxTokensForEffort(level: EffortLevel, base: number): number {
  return level === "max" ? Math.max(base, MAX_EFFORT_MIN_OUTPUT_TOKENS) : base;
}

/** One-line description of what a level sends, for /effort output. */
export function describeEffortLevel(level: EffortLevel): string {
  switch (level) {
    case "off":
      return "thinking disabled";
    case "low":
      return "thinking on, low effort";
    case "medium":
      return "thinking on, medium effort";
    case "high":
      return "thinking on, full effort (the default)";
    case "max":
      return `thinking on, full effort, output cap raised to at least ${MAX_EFFORT_MIN_OUTPUT_TOKENS} tokens`;
  }
}

// ---- Current level (session state, seeded from settings) ----

let current: EffortLevel | null = null;

function readPersistedEffortLevel(): EffortLevel {
  try {
    const raw = readFileSync(getSettingsFilePathForSource("user"), "utf-8");
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed === "object" && parsed !== null) {
      const v = (parsed as Record<string, unknown>)[EFFORT_SETTINGS_KEY];
      if (typeof v === "string") return parseEffortLevel(v) ?? DEFAULT_EFFORT_LEVEL;
    }
  } catch {
    // missing or unreadable settings -> default
  }
  return DEFAULT_EFFORT_LEVEL;
}

/** The active level: the session's choice, else the persisted setting, else the default. */
export function getEffortLevel(): EffortLevel {
  if (current === null) current = readPersistedEffortLevel();
  return current;
}

/** Sets the level for this session and persists it. Throws when the settings write fails
 *  (the in-memory level is already set, so the session keeps the operator's choice). */
export async function setEffortLevel(level: EffortLevel): Promise<void> {
  current = level;
  await updateSettingsForSource("user", { [EFFORT_SETTINGS_KEY]: level });
}

/** TEST-ONLY: forget the cached level so the next read re-seeds from settings. */
export function _resetEffortLevelForTests(level: EffortLevel | null = null): void {
  current = level;
}
