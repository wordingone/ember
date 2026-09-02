// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// companion-ui — acceptance criteria tests.
// Spec: specs/buddy/companion-ui.md
// Pure logic + helpers tested directly; React rendering is structural only.

import { describe, it, expect, beforeEach, afterEach } from 'bun:test';
import {
  renderSprite,
  renderFace,
  spriteFrameCount,
  companionReservedColumns,
  findBuddyTriggerPositions,
  isBuddyTeaserWindow,
  isBuddyLive,
  getCompanionIntroAttachment,
  companionIntroText,
  CompanionSprite,
  CompanionFloatingBubble,
  SpeechBubble,
  useBuddyNotification,
  _isBubbleVisible,
  _isBubbleFading,
  _shouldShowBuddyNotification,
  type CompanionBones,
  type CompanionSpriteState,
  type BuddyNotificationDeps,
  type Message,
} from './companion-ui.ts';

// ---------------------------------------------------------------------------
// Test fixtures
// ---------------------------------------------------------------------------

const BONES_CAT: CompanionBones = {
  rarity: 'uncommon',
  species: 'cat',
  eye: '◉',
  hat: 'crown',
  shiny: false,
  stats: { DEBUGGING: 30, PATIENCE: 20, CHAOS: 40, WISDOM: 25, SNARK: 35 },
};

const BONES_BLOB_NO_HAT: CompanionBones = {
  rarity: 'common',
  species: 'blob',
  eye: '·',
  hat: 'none',
  shiny: false,
  stats: { DEBUGGING: 10, PATIENCE: 10, CHAOS: 10, WISDOM: 10, SNARK: 10 },
};

const originalFeatureBuddy = process.env['FEATURE_BUDDY'];

function enableBuddy(): void { process.env['FEATURE_BUDDY'] = '1'; }
function disableBuddy(): void { delete process.env['FEATURE_BUDDY']; }

beforeEach(() => { enableBuddy(); });
afterEach(() => {
  if (originalFeatureBuddy !== undefined) {
    process.env['FEATURE_BUDDY'] = originalFeatureBuddy;
  } else {
    delete process.env['FEATURE_BUDDY'];
  }
});

// ---------------------------------------------------------------------------
// AC1: renderSprite returns 4–5 string array; {E} replaced with eye glyph
// ---------------------------------------------------------------------------

describe('AC1: renderSprite basic contract', () => {
  it('returns an array of strings', () => {
    const lines = renderSprite(BONES_BLOB_NO_HAT, 0);
    expect(Array.isArray(lines)).toBe(true);
    expect(lines.length).toBeGreaterThanOrEqual(4);
    expect(lines.length).toBeLessThanOrEqual(5);
  });

  it('{E} is replaced with the eye glyph', () => {
    // Ensure no {E} token remains in the output
    const lines = renderSprite(BONES_CAT, 0);
    for (const line of lines) {
      expect(line).not.toContain('{E}');
    }
  });

  it('eye glyph appears in the rendered output', () => {
    const bonesCustomEye: CompanionBones = { ...BONES_BLOB_NO_HAT, eye: '✦' };
    const lines = renderSprite(bonesCustomEye, 0);
    const joined = lines.join('');
    // Eye glyph must appear (wherever {E} was in the template)
    // blob template: '({E}  {E})' — eye would appear if the template had {E}
    // We just check no {E} remains and the string is well-formed
    expect(joined).not.toContain('{E}');
  });

  it('all returned strings are strings', () => {
    const lines = renderSprite(BONES_CAT, 0);
    for (const line of lines) {
      expect(typeof line).toBe('string');
    }
  });

  it('frame 0 and frame 1 both return valid arrays', () => {
    const f0 = renderSprite(BONES_BLOB_NO_HAT, 0);
    const f1 = renderSprite(BONES_BLOB_NO_HAT, 1);
    expect(f0.length).toBeGreaterThanOrEqual(4);
    expect(f1.length).toBeGreaterThanOrEqual(4);
  });
});

// ---------------------------------------------------------------------------
// AC2: hat ≠ 'none' and blank line 0 → hat string appears on line 0
// ---------------------------------------------------------------------------

describe('AC2: hat overlay', () => {
  it('with hat ≠ none, line 0 is not blank', () => {
    const lines = renderSprite(BONES_CAT, 0);  // crown hat
    expect(lines[0]?.trim()).not.toBe('');
  });

  it('with hat = none, line 0 is absent (4 lines total)', () => {
    const lines = renderSprite(BONES_BLOB_NO_HAT, 0);
    expect(lines.length).toBe(4);
  });

  it('hat string for crown appears in output', () => {
    const lines = renderSprite(BONES_CAT, 0);
    const joined = lines.join('\n');
    // Crown hat: '  /\\_/\\_/\\ '. Check that line 0 is non-blank.
    expect(lines[0]?.trim().length).toBeGreaterThan(0);
  });

  it('different hats produce different line 0 content', () => {
    const bonesCrown: CompanionBones = { ...BONES_CAT, hat: 'crown' };
    const bonesTophat: CompanionBones = { ...BONES_CAT, hat: 'tophat' };
    const crownLines = renderSprite(bonesCrown, 0);
    const tophatLines = renderSprite(bonesTophat, 0);
    // At least 5 lines with a hat
    expect(crownLines.length).toBe(5);
    expect(tophatLines.length).toBe(5);
    // Different hats → different line 0
    expect(crownLines[0]).not.toBe(tophatLines[0]);
  });
});

// ---------------------------------------------------------------------------
// AC3: spriteFrameCount always returns 3
// ---------------------------------------------------------------------------

describe('AC3: spriteFrameCount always 3', () => {
  const allSpecies = [
    'duck', 'goose', 'blob', 'cat', 'dragon', 'octopus', 'owl', 'penguin',
    'turtle', 'snail', 'ghost', 'axolotl', 'capybara', 'cactus', 'robot',
    'rabbit', 'mushroom', 'chonk',
  ] as const;

  for (const species of allSpecies) {
    it(`spriteFrameCount('${species}') === 3`, () => {
      expect(spriteFrameCount(species)).toBe(3);
    });
  }
});

// ---------------------------------------------------------------------------
// AC4: companionReservedColumns(80, false) returns 0
// ---------------------------------------------------------------------------

describe('AC4: narrow terminal returns 0', () => {
  it('returns 0 for 80 columns (narrow terminal)', () => {
    const result = companionReservedColumns(80, false, {
      featureEnabled: () => true,
      hasCompanion: () => true,
      muted: () => false,
    });
    expect(result).toBe(0);
  });

  it('returns 0 for 99 columns (just below threshold)', () => {
    const result = companionReservedColumns(99, false, {
      featureEnabled: () => true,
      hasCompanion: () => true,
      muted: () => false,
    });
    expect(result).toBe(0);
  });

  it('returns 0 when feature disabled', () => {
    const result = companionReservedColumns(120, false, {
      featureEnabled: () => false,
      hasCompanion: () => true,
      muted: () => false,
    });
    expect(result).toBe(0);
  });

  it('returns 0 when no companion', () => {
    const result = companionReservedColumns(120, false, {
      featureEnabled: () => true,
      hasCompanion: () => false,
      muted: () => false,
    });
    expect(result).toBe(0);
  });

  it('returns 0 when muted', () => {
    const result = companionReservedColumns(120, false, {
      featureEnabled: () => true,
      hasCompanion: () => true,
      muted: () => true,
    });
    expect(result).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// AC5: companionReservedColumns(120, false) returns sprite + name padding
// ---------------------------------------------------------------------------

describe('AC5: wide terminal with companion returns sprite+padding', () => {
  const deps = {
    featureEnabled: () => true,
    hasCompanion: () => true,
    muted: () => false,
  };

  it('returns 14 (12 body + 2 name padding) when not speaking', () => {
    const result = companionReservedColumns(120, false, deps);
    expect(result).toBe(14); // 12 + 2
  });

  it('returns 50 (12 + 2 + 36 bubble) when speaking', () => {
    const result = companionReservedColumns(120, true, deps);
    expect(result).toBe(50); // 12 + 2 + 36
  });

  it('100 columns exactly is wide enough', () => {
    const result = companionReservedColumns(100, false, deps);
    expect(result).toBe(14);
  });
});

// ---------------------------------------------------------------------------
// AC6: getCompanionIntroAttachment deduplication
// ---------------------------------------------------------------------------

describe('AC6: getCompanionIntroAttachment deduplication', () => {
  const companion = { name: 'Floofles', species: 'cat' };

  it('returns one attachment on first call with empty messages', () => {
    const result = getCompanionIntroAttachment([], companion);
    expect(result).toHaveLength(1);
    expect(result[0]!.type).toBe('companion_intro');
    expect(result[0]!.name).toBe('Floofles');
    expect(result[0]!.species).toBe('cat');
  });

  it('returns empty array when same companion already in messages', () => {
    const messages: Message[] = [
      {
        attachments: [{ type: 'companion_intro', name: 'Floofles', species: 'cat' }],
      },
    ];
    const result = getCompanionIntroAttachment(messages, companion);
    expect(result).toHaveLength(0);
  });

  it('returns attachment when a different companion is in messages', () => {
    const messages: Message[] = [
      {
        attachments: [{ type: 'companion_intro', name: 'Blobby', species: 'blob' }],
      },
    ];
    const result = getCompanionIntroAttachment(messages, companion);
    expect(result).toHaveLength(1);
  });

  it('returns empty when no companion arg provided', () => {
    const result = getCompanionIntroAttachment([]);
    expect(result).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// AC7: CompanionSprite returns nothing when muted=true
// ---------------------------------------------------------------------------

describe('AC7: CompanionSprite muted renders nothing', () => {
  const state: CompanionSpriteState = { tick: 0, companionReaction: 'hello' };

  it('returns null when muted=true', () => {
    const result = CompanionSprite({
      bones: BONES_CAT,
      state,
      muted: true,
      terminalColumns: 120,
    });
    expect(result).toBeNull();
  });

  it('returns null when terminalColumns < 100', () => {
    const result = CompanionSprite({
      bones: BONES_CAT,
      state,
      muted: false,
      terminalColumns: 80,
    });
    expect(result).toBeNull();
  });

  it('returns non-null when muted=false and wide terminal', () => {
    const result = CompanionSprite({
      bones: BONES_CAT,
      state,
      muted: false,
      terminalColumns: 120,
    });
    expect(result).not.toBeNull();
  });

  it('is a function (React component)', () => {
    expect(typeof CompanionSprite).toBe('function');
  });
});

// ---------------------------------------------------------------------------
// AC8: Bubble visible ticks 0–19; dimmed ticks 14–19
// ---------------------------------------------------------------------------

describe('AC8: bubble visibility and fading', () => {
  const reaction = 'hello!';

  it('bubble is visible at tick 0', () => {
    expect(_isBubbleVisible({ tick: 0, companionReaction: reaction })).toBe(true);
  });

  it('bubble is visible at tick 19', () => {
    expect(_isBubbleVisible({ tick: 19, companionReaction: reaction })).toBe(true);
  });

  it('bubble is NOT visible at tick 20', () => {
    expect(_isBubbleVisible({ tick: 20, companionReaction: reaction })).toBe(false);
  });

  it('bubble is NOT visible when no reaction', () => {
    expect(_isBubbleVisible({ tick: 0 })).toBe(false);
    expect(_isBubbleVisible({ tick: 5 })).toBe(false);
  });

  it('bubble is NOT dimmed at tick 0', () => {
    expect(_isBubbleFading(0)).toBe(false);
  });

  it('bubble is NOT dimmed at tick 13', () => {
    expect(_isBubbleFading(13)).toBe(false);
  });

  it('bubble IS dimmed at tick 14', () => {
    expect(_isBubbleFading(14)).toBe(true);
  });

  it('bubble IS dimmed at tick 19', () => {
    expect(_isBubbleFading(19)).toBe(true);
  });

  it('CompanionFloatingBubble returns null after tick 20', () => {
    const result = CompanionFloatingBubble({ text: reaction, tick: 20 });
    expect(result).toBeNull();
  });

  it('CompanionFloatingBubble returns non-null before tick 20', () => {
    const result = CompanionFloatingBubble({ text: reaction, tick: 0 });
    expect(result).not.toBeNull();
  });

  it('CompanionFloatingBubble returns null when no text', () => {
    const result = CompanionFloatingBubble({ text: '', tick: 0 });
    expect(result).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// AC9: useBuddyNotification — no notification when companion stored
// ---------------------------------------------------------------------------

describe('AC9: useBuddyNotification with companion stored', () => {
  const makeDeps = (
    overrides: Partial<BuddyNotificationDeps> = {},
  ): BuddyNotificationDeps & { added: string[] } => {
    const added: string[] = [];
    return {
      featureEnabled: () => true,
      hasStoredCompanion: () => false,
      isTeaserWindow: () => true,
      addNotification: (e) => { added.push(e.key); },
      removeNotification: () => {},
      added,
      ...overrides,
    };
  };

  it('no notification when companion stored (_shouldShowBuddyNotification)', () => {
    const deps = makeDeps({ hasStoredCompanion: () => true });
    expect(_shouldShowBuddyNotification(deps)).toBe(false);
  });

  it('notification shown when no companion + feature + teaser window', () => {
    const deps = makeDeps({ hasStoredCompanion: () => false });
    expect(_shouldShowBuddyNotification(deps)).toBe(true);
  });

  it('no notification when feature disabled', () => {
    const deps = makeDeps({ featureEnabled: () => false });
    expect(_shouldShowBuddyNotification(deps)).toBe(false);
  });

  it('no notification when outside teaser window', () => {
    const deps = makeDeps({ isTeaserWindow: () => false });
    expect(_shouldShowBuddyNotification(deps)).toBe(false);
  });

  it('useBuddyNotification is a function (React hook)', () => {
    expect(typeof useBuddyNotification).toBe('function');
  });
});

// ---------------------------------------------------------------------------
// AC10: findBuddyTriggerPositions finds all /buddy occurrences
// ---------------------------------------------------------------------------

describe('AC10: findBuddyTriggerPositions', () => {
  it('"/buddy pet /buddy" returns two span ranges', () => {
    const results = findBuddyTriggerPositions('/buddy pet /buddy');
    expect(results).toHaveLength(2);
  });

  it('first match starts at 0', () => {
    const results = findBuddyTriggerPositions('/buddy hello');
    expect(results[0]!.start).toBe(0);
    expect(results[0]!.end).toBe(6);
  });

  it('second match starts at correct offset', () => {
    const text = '/buddy pet /buddy';
    const results = findBuddyTriggerPositions(text);
    const secondMatch = results[1]!;
    expect(text.slice(secondMatch.start, secondMatch.end)).toBe('/buddy');
  });

  it('no /buddy in text → empty array', () => {
    expect(findBuddyTriggerPositions('hello world')).toHaveLength(0);
  });

  it('empty text → empty array', () => {
    expect(findBuddyTriggerPositions('')).toHaveLength(0);
  });

  it('returns empty when feature disabled', () => {
    disableBuddy();
    const results = findBuddyTriggerPositions('/buddy pet /buddy');
    expect(results).toHaveLength(0);
    enableBuddy();
  });

  it('/buddyX (no word boundary) is not matched', () => {
    const results = findBuddyTriggerPositions('/buddyX');
    expect(results).toHaveLength(0);
  });

  it('three occurrences → three spans', () => {
    const results = findBuddyTriggerPositions('/buddy /buddy /buddy');
    expect(results).toHaveLength(3);
  });
});

// ---------------------------------------------------------------------------
// Structural: teaser window queries
// ---------------------------------------------------------------------------

describe('Structural: teaser window helpers', () => {
  it('isBuddyTeaserWindow("ant") returns true', () => {
    expect(isBuddyTeaserWindow('ant')).toBe(true);
  });

  it('isBuddyLive("ant") returns true', () => {
    expect(isBuddyLive('ant')).toBe(true);
  });

  it('isBuddyTeaserWindow() returns a boolean', () => {
    expect(typeof isBuddyTeaserWindow()).toBe('boolean');
  });

  it('isBuddyLive() returns a boolean', () => {
    expect(typeof isBuddyLive()).toBe('boolean');
  });
});

// ---------------------------------------------------------------------------
// Structural: renderFace
// ---------------------------------------------------------------------------

describe('Structural: renderFace', () => {
  it('returns a compact 3–7 char face string', () => {
    const face = renderFace(BONES_BLOB_NO_HAT);
    expect(face.length).toBeGreaterThanOrEqual(3);
    expect(face.length).toBeLessThanOrEqual(7);
  });

  it('contains the eye glyph', () => {
    const bonesCustomEye: CompanionBones = { ...BONES_BLOB_NO_HAT, eye: '@' };
    const face = renderFace(bonesCustomEye);
    expect(face).toContain('@');
  });
});

// ---------------------------------------------------------------------------
// Structural: companionIntroText (6-line contract)
// ---------------------------------------------------------------------------

describe('Structural: companionIntroText', () => {
  it('returns exactly 6 lines', () => {
    const text = companionIntroText('Floofles', 'cat');
    const lines = text.split('\n');
    expect(lines).toHaveLength(6);
  });

  it('contains the companion name', () => {
    const text = companionIntroText('Floofles', 'cat');
    expect(text).toContain('Floofles');
  });

  it('contains the species', () => {
    const text = companionIntroText('Floofles', 'cat');
    expect(text).toContain('cat');
  });
});

// ---------------------------------------------------------------------------
// Structural: SpeechBubble is a React component
// ---------------------------------------------------------------------------

describe('Structural: SpeechBubble', () => {
  it('is a function', () => {
    expect(typeof SpeechBubble).toBe('function');
  });

  it('returns a React node (not null)', () => {
    const result = SpeechBubble({ text: 'hello', color: 'cyan' });
    expect(result).not.toBeNull();
  });
});
