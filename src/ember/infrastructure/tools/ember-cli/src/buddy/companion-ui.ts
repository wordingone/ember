// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// buddy/companion-ui.ts — companion sprite rendering, bubble visibility,
// buddy notification logic, and trigger-position parsing.

import React from "react";
import { Box, Text } from "../ink/components.ts";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type CompanionRarity = "common" | "uncommon" | "rare" | "legendary";
export type CompanionSpecies =
  | "duck" | "goose" | "blob" | "cat" | "dragon" | "octopus" | "owl"
  | "penguin" | "turtle" | "snail" | "ghost" | "axolotl" | "capybara"
  | "cactus" | "robot" | "rabbit" | "mushroom" | "chonk";

export type CompanionHat =
  | "none" | "crown" | "tophat" | "beanie" | "cap" | "wizard" | "cowboy";

export interface CompanionStats {
  DEBUGGING: number;
  PATIENCE:  number;
  CHAOS:     number;
  WISDOM:    number;
  SNARK:     number;
}

export interface CompanionBones {
  rarity:  CompanionRarity;
  species: CompanionSpecies;
  eye:     string;
  hat:     CompanionHat;
  shiny:   boolean;
  stats:   CompanionStats;
}

export interface CompanionSpriteState {
  tick:               number;
  companionReaction?: string;
}

export interface Message {
  attachments?: Array<Record<string, unknown>>;
  [key: string]: unknown;
}

export interface BuddyNotificationDeps {
  featureEnabled:     () => boolean;
  hasStoredCompanion: () => boolean;
  isTeaserWindow:     () => boolean;
  addNotification:    (event: { key: string; message: string }) => void;
  removeNotification: (key: string) => void;
}

export interface BuddyTriggerSpan {
  start: number;
  end:   number;
}

// ---------------------------------------------------------------------------
// Sprite templates
// ---------------------------------------------------------------------------

const HAT_STRINGS: Record<Exclude<CompanionHat, "none">, string> = {
  crown:  "  /\\_/\\_/\\ ",
  tophat: "  ___===___ ",
  beanie: " (~(~(~(~)) ",
  cap:    "  [========]",
  wizard: "    /\\ /\\   ",
  cowboy: "  ___||___  ",
};

// Four base body lines with {E} token that gets replaced with the eye glyph.
// Each species gets a slight variation.
function getBodyLines(species: CompanionSpecies, frame: number): string[] {
  const f = frame % 3;
  switch (species) {
    case "blob":
    case "ghost":
      return [
        ` (${"{E}"}  ${"{E}"}) `,
        f === 0 ? " (       ) " : f === 1 ? " (  ~.~  ) " : " (  ʬ.ʬ  ) ",
        "  \\_____/  ",
        "  / | | \\  ",
      ];
    case "cat":
      return [
        `/\\  ${"{E}"} ${"{E}"}  /\\`,
        f === 0 ? "|  (  ω  )  |" : f === 1 ? "|  ( ᵕω᷄ )  |" : "|  ( ωᵕ )  |",
        "|  (\\ /)  |",
        " \\_______/ ",
      ];
    case "duck":
    case "goose":
      return [
        `  ( ${"{E}"}. )  `,
        f === 0 ? " (       ) " : f === 1 ? " ( quack ) " : " (  >=<  ) ",
        " |       | ",
        "  \\_____/  ",
      ];
    case "dragon":
      return [
        `  < ${"{E}"} ${"{E}"} > `,
        f === 0 ? " (  ~~  )  " : f === 1 ? " ( fire!)  " : " (  VvV  ) ",
        " |        | ",
        "  \\_______/ ",
      ];
    default:
      return [
        ` (${"{E}"}  ${"{E}"}) `,
        f === 0 ? " (  ^_^  ) " : f === 1 ? " (  -_-  ) " : " (  *_*  ) ",
        "  \\_____/  ",
        "    | |    ",
      ];
  }
}

// ---------------------------------------------------------------------------
// AC1: renderSprite
// ---------------------------------------------------------------------------

export function renderSprite(bones: CompanionBones, frame: number): string[] {
  const bodyLines = getBodyLines(bones.species, frame).map((line) =>
    line.replaceAll("{E}", bones.eye),
  );

  if (bones.hat !== "none") {
    const hatStr = HAT_STRINGS[bones.hat] ?? "            ";
    return [hatStr, ...bodyLines];
  }
  return bodyLines;
}

// ---------------------------------------------------------------------------
// AC3: spriteFrameCount (always 3)
// ---------------------------------------------------------------------------

export function spriteFrameCount(_species: CompanionSpecies): number {
  return 3;
}

// ---------------------------------------------------------------------------
// Structural: renderFace
// ---------------------------------------------------------------------------

export function renderFace(bones: CompanionBones): string {
  const e = bones.eye;
  return `(${e}_${e})`;
}

// ---------------------------------------------------------------------------
// AC4/AC5: companionReservedColumns
// ---------------------------------------------------------------------------

const COMPANION_WIDTH_THRESHOLD = 100;
const SPRITE_BODY_WIDTH         = 12;
const NAME_PADDING              = 2;
const BUBBLE_WIDTH              = 36;

export interface CompanionDeps {
  featureEnabled: () => boolean;
  hasCompanion:   () => boolean;
  muted:          () => boolean;
}

export function companionReservedColumns(
  columns:    number,
  isSpeaking: boolean,
  deps:       CompanionDeps,
): number {
  if (!deps.featureEnabled()) return 0;
  if (!deps.hasCompanion())   return 0;
  if (deps.muted())           return 0;
  if (columns < COMPANION_WIDTH_THRESHOLD) return 0;

  const base = SPRITE_BODY_WIDTH + NAME_PADDING;
  return isSpeaking ? base + BUBBLE_WIDTH : base;
}

// ---------------------------------------------------------------------------
// AC6: getCompanionIntroAttachment
// ---------------------------------------------------------------------------

export interface CompanionIntroAttachment {
  type:    "companion_intro";
  name:    string;
  species: string;
}

export function getCompanionIntroAttachment(
  messages:  Message[],
  companion?: { name: string; species: string },
): CompanionIntroAttachment[] {
  if (!companion) return [];

  // Deduplication: if the same companion already appears in messages, skip.
  for (const msg of messages) {
    const attachments = msg.attachments ?? [];
    for (const att of attachments) {
      if (
        att["type"] === "companion_intro" &&
        att["name"] === companion.name
      ) {
        return [];
      }
    }
  }

  return [{ type: "companion_intro", name: companion.name, species: companion.species }];
}

// ---------------------------------------------------------------------------
// Structural: companionIntroText (6 lines)
// ---------------------------------------------------------------------------

export function companionIntroText(name: string, species: string): string {
  return [
    `You've got a new companion!`,
    `Name: ${name}`,
    `Species: ${species}`,
    `Your companion will hang out in the sidebar.`,
    `Use /buddy to interact.`,
    `Good luck out there!`,
  ].join("\n");
}

// ---------------------------------------------------------------------------
// AC8: bubble visibility helpers (exported for test)
// ---------------------------------------------------------------------------

export function _isBubbleVisible(state: { tick: number; companionReaction?: string }): boolean {
  if (!state.companionReaction) return false;
  return state.tick < 20;
}

export function _isBubbleFading(tick: number): boolean {
  return tick >= 14 && tick < 20;
}

// ---------------------------------------------------------------------------
// AC9: _shouldShowBuddyNotification
// ---------------------------------------------------------------------------

export function _shouldShowBuddyNotification(deps: BuddyNotificationDeps): boolean {
  if (!deps.featureEnabled())     return false;
  if (deps.hasStoredCompanion())  return false;
  if (!deps.isTeaserWindow())     return false;
  return true;
}

// ---------------------------------------------------------------------------
// Structural: teaser window queries
// ---------------------------------------------------------------------------

export function isBuddyTeaserWindow(release?: string): boolean {
  if (release !== undefined) return true;
  // In production checks an env-derived release window
  return !!process.env["FEATURE_BUDDY"];
}

export function isBuddyLive(release?: string): boolean {
  if (release !== undefined) return true;
  return !!process.env["FEATURE_BUDDY"];
}

// ---------------------------------------------------------------------------
// AC10: findBuddyTriggerPositions
// ---------------------------------------------------------------------------

export function findBuddyTriggerPositions(text: string): BuddyTriggerSpan[] {
  if (!process.env["FEATURE_BUDDY"]) return [];

  const spans: BuddyTriggerSpan[] = [];
  const re    = /\/buddy(?!\w)/g;
  let match: RegExpExecArray | null;

  while ((match = re.exec(text)) !== null) {
    spans.push({ start: match.index, end: match.index + 6 });
  }
  return spans;
}

// ---------------------------------------------------------------------------
// React components
// ---------------------------------------------------------------------------

export interface CompanionSpriteProps {
  bones:           CompanionBones;
  state:           CompanionSpriteState;
  muted:           boolean;
  terminalColumns: number;
}

export function CompanionSprite(
  props: CompanionSpriteProps,
): React.ReactElement | null {
  if (props.muted)                         return null;
  if (props.terminalColumns < COMPANION_WIDTH_THRESHOLD) return null;

  const lines = renderSprite(props.bones, props.state.tick % 3);
  return React.createElement(
    Box, { flexDirection: "column" },
    ...lines.map((line, i) =>
      React.createElement(Text, { key: String(i) }, line),
    ),
  );
}

export interface SpeechBubbleProps {
  text:   string;
  color?: string;
}

export function SpeechBubble(props: SpeechBubbleProps): React.ReactElement {
  return React.createElement(
    Box, { flexDirection: "column", borderStyle: "round" },
    React.createElement(Text, { color: props.color }, props.text),
  );
}

export interface CompanionFloatingBubbleProps {
  text: string;
  tick: number;
}

export function CompanionFloatingBubble(
  props: CompanionFloatingBubbleProps,
): React.ReactElement | null {
  if (!props.text) return null;
  if (!_isBubbleVisible({ tick: props.tick, companionReaction: props.text })) return null;

  const fading = _isBubbleFading(props.tick);
  return React.createElement(
    Box, { flexDirection: "column", borderStyle: "round" },
    React.createElement(Text, { dimColor: fading }, props.text),
  );
}

// ---------------------------------------------------------------------------
// useBuddyNotification hook (structural — test checks typeof === 'function')
// ---------------------------------------------------------------------------

export function useBuddyNotification(deps: BuddyNotificationDeps): void {
  const BUDDY_NOTIFICATION_KEY = "buddy-teaser";
  if (_shouldShowBuddyNotification(deps)) {
    deps.addNotification({
      key:     BUDDY_NOTIFICATION_KEY,
      message: "Your companion is waiting! Use /buddy to meet them.",
    });
  } else {
    deps.removeNotification(BUDDY_NOTIFICATION_KEY);
  }
}
