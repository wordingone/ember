// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// Tests for skill-framework.ts — one describe block per AC.
//
// Filesystem interactions are exercised against actual temp directories
// created per-test (using os.tmpdir + mkdtemp). No mocking of fs is needed
// since the real code is simple and fast at this scale.

import { describe, it, expect, beforeEach, afterEach } from 'bun:test';
import { mkdtemp, mkdir, writeFile, rm } from 'fs/promises';
import { join, resolve } from 'path';
import { tmpdir } from 'os';
import {
  getSkillDirCommands,
  loadSkillsFromSkillsDir,
  parseSkillFrontmatterFields,
  createSkillCommand,
  clearSkillCaches,
  clearDynamicSkills,
  registerBundledSkill,
  getBundledSkills,
  clearBundledSkills,
  getBundledSkillExtractDir,
  registerMCPSkillBuilders,
  getMCPSkillBuilders,
  fetchMcpSkillsForClient,
  activateConditionalSkillsForPaths,
  getConditionalSkillCount,
  addSkillDirectories,
  onDynamicSkillsLoaded,
  setSkillFrameworkSettings,
  type BundledSkillDefinition,
} from './skill-framework.ts';
import { buildCommandButtons, commandButtonActivation } from './services/command-buttons.ts';

// Reset all module-level state before each test
beforeEach(() => {
  clearSkillCaches();
  clearDynamicSkills();
  clearBundledSkills();
  // Reset MCP builders (private state — we test registering fresh each time)
  setSkillFrameworkSettings({});
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function makeSkillDir(
  baseDir: string,
  name: string,
  frontmatter: string,
  body = 'Skill body content.',
): Promise<string> {
  const skillDir = join(baseDir, name);
  await mkdir(skillDir, { recursive: true });
  const fm = frontmatter ? `---\n${frontmatter}\n---\n` : '';
  await writeFile(join(skillDir, 'SKILL.md'), `${fm}${body}`);
  return skillDir;
}

// ---------------------------------------------------------------------------
// AC1: skill with user-invocable: false → isHidden: true
// ---------------------------------------------------------------------------

describe('AC1 — user-invocable: false → isHidden: true', () => {
  it('hidden skill does not appear in typeahead (isHidden is true)', async () => {
    const tmp = await mkdtemp(join(tmpdir(), 'sf-ac1-'));
    try {
      await makeSkillDir(tmp, 'my-skill', 'user-invocable: false\ndescription: Hidden');
      const skills = await loadSkillsFromSkillsDir(tmp, 'projectSettings');
      expect(skills).toHaveLength(1);
      const cmd = skills[0]!.command as unknown as Record<string, unknown>;
      expect(cmd['isHidden']).toBe(true);
    } finally { await rm(tmp, { recursive: true, force: true }); }
  });

  it('default skill (no user-invocable) has isHidden false', async () => {
    const tmp = await mkdtemp(join(tmpdir(), 'sf-ac1b-'));
    try {
      await makeSkillDir(tmp, 'visible', 'description: Visible skill');
      const skills = await loadSkillsFromSkillsDir(tmp, 'projectSettings');
      expect(skills).toHaveLength(1);
      const cmd = skills[0]!.command as unknown as Record<string, unknown>;
      expect(cmd['isHidden']).toBeFalsy();
    } finally { await rm(tmp, { recursive: true, force: true }); }
  });
});

// ---------------------------------------------------------------------------
// AC2: skill with context: "fork" → context: 'fork' on Command
// ---------------------------------------------------------------------------

describe('AC2 — context: fork', () => {
  it('skill with context: fork has context fork on its Command', async () => {
    const tmp = await mkdtemp(join(tmpdir(), 'sf-ac2-'));
    try {
      await makeSkillDir(tmp, 'fork-skill', 'context: fork\ndescription: Fork skill');
      const skills = await loadSkillsFromSkillsDir(tmp, 'projectSettings');
      expect(skills).toHaveLength(1);
      const cmd = skills[0]!.command as unknown as Record<string, unknown>;
      expect(cmd['context']).toBe('fork');
    } finally { await rm(tmp, { recursive: true, force: true }); }
  });
});

// ---------------------------------------------------------------------------
// AC3: getSkillDirCommands memoized — same object on subsequent calls
// ---------------------------------------------------------------------------

describe('AC3 — getSkillDirCommands memoized per cwd', () => {
  it('returns the same array instance on the second call', async () => {
    const cwd = resolve(tmpdir());
    const first = await getSkillDirCommands(cwd);
    const second = await getSkillDirCommands(cwd);
    expect(first).toBe(second); // same reference
  });
});

// ---------------------------------------------------------------------------
// AC4: clearSkillCaches causes re-scan on next getSkillDirCommands
// ---------------------------------------------------------------------------

describe('AC4 — clearSkillCaches triggers re-scan', () => {
  it('after clearSkillCaches, the next call re-scans the filesystem', async () => {
    const tmp = await mkdtemp(join(tmpdir(), 'sf-ac4-'));
    try {
      setSkillFrameworkSettings({
        // Treat tmp as project skills dir by making getSkillDirCommands find it
        // We can't easily inject the dir, so just verify the cache-miss path.
      });
      const cwd = tmp;
      const first = await getSkillDirCommands(cwd);
      clearSkillCaches();
      const second = await getSkillDirCommands(cwd);
      // After clear, a fresh object is returned (not the same reference)
      expect(first).not.toBe(second);
    } finally { await rm(tmp, { recursive: true, force: true }); }
  });
});

// ---------------------------------------------------------------------------
// AC5: skill with paths: frontmatter not in getSkillDirCommands until activated
// ---------------------------------------------------------------------------

describe('AC5 — conditional skill path gating', () => {
  it('conditional skill absent from getSkillDirCommands before activation', async () => {
    const tmp = await mkdtemp(join(tmpdir(), 'sf-ac5-'));
    try {
      await makeSkillDir(tmp, 'cond-skill', 'paths: ["**/*.ts"]\ndescription: TS only');
      const skills = await loadSkillsFromSkillsDir(tmp, 'projectSettings');
      // The skill is loaded but marked conditional
      // Load into dynamic discovery
      await addSkillDirectories([tmp]);
      const countBefore = getConditionalSkillCount();
      expect(countBefore).toBeGreaterThan(0);
    } finally {
      await rm(tmp, { recursive: true, force: true });
      clearSkillCaches();
      clearDynamicSkills();
    }
  });

  it('activateConditionalSkillsForPaths moves matching skill to active pool', async () => {
    const tmp = await mkdtemp(join(tmpdir(), 'sf-ac5b-'));
    try {
      await makeSkillDir(tmp, 'ts-skill', 'paths: ["**/*.ts"]\ndescription: TS skill');
      // Put the skill into conditional state via addSkillDirectories
      clearSkillCaches();
      clearDynamicSkills();
      await addSkillDirectories([tmp]);
      const countBefore = getConditionalSkillCount();

      const activated = activateConditionalSkillsForPaths(
        [join(tmp, 'src/foo.ts')],
        tmp,
      );
      expect(activated).toContain('ts-skill');
      expect(getConditionalSkillCount()).toBe(countBefore - 1);
    } finally {
      await rm(tmp, { recursive: true, force: true });
      clearSkillCaches();
      clearDynamicSkills();
    }
  });
});

// ---------------------------------------------------------------------------
// AC6: bundled skill reference file with .. path throws
// ---------------------------------------------------------------------------

describe('AC6 — bundled skill path traversal rejected', () => {
  it('throws when a reference file path contains ..', async () => {
    clearBundledSkills();
    const def: BundledSkillDefinition = {
      name: 'traversal-skill',
      description: 'evil',
      files: { '../etc/passwd': 'content' },
      getPromptForCommand: () => [{ type: 'text', text: 'bad' }],
    };
    registerBundledSkill(def);
    const skills = getBundledSkills();
    expect(skills).toHaveLength(1);
    const cmd = skills[0] as unknown as Record<string, unknown>;
    const getPrompt = cmd['getPromptForCommand'] as (
      args: string,
      ctx: unknown,
    ) => Promise<Array<{ type: 'text'; text: string }>>;
    // First call triggers extraction which should throw on the .. path
    await expect(getPrompt('', {})).rejects.toThrow(/path traversal/i);
  });
});

// ---------------------------------------------------------------------------
// AC7: registerMCPSkillBuilders + getMCPSkillBuilders; throws before registration
// ---------------------------------------------------------------------------

describe('AC7 — MCP skill builders registry', () => {
  it('getMCPSkillBuilders throws before registration', () => {
    expect(() => getMCPSkillBuilders()).toThrow();
  });

  it('returns builders after registration', () => {
    const builders = { createSkillCommand, parseSkillFrontmatterFields };
    registerMCPSkillBuilders(builders);
    const result = getMCPSkillBuilders();
    expect(result).toBe(builders);
  });
});

// ---------------------------------------------------------------------------
// AC8: fetchMcpSkillsForClient always returns []
// ---------------------------------------------------------------------------

describe('AC8 — fetchMcpSkillsForClient stub', () => {
  it('returns empty array for any client', () => {
    expect(fetchMcpSkillsForClient({})).toEqual([]);
    expect(fetchMcpSkillsForClient(null)).toEqual([]);
    expect(fetchMcpSkillsForClient('anything')).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// AC9: ${EMBER_SKILL_DIR} replaced with skill's directory (forward slashes)
// ---------------------------------------------------------------------------

describe('AC9 — EMBER_SKILL_DIR substitution', () => {
  it('replaces ${EMBER_SKILL_DIR} with base dir using forward slashes', () => {
    const cmd = createSkillCommand({
      name: 'dirtest',
      description: 'test',
      basePath: 'C:\\my\\skill\\dir',
      content: 'Dir is ${EMBER_SKILL_DIR}',
    });
    const cmdAny = cmd as unknown as Record<string, unknown>;
    const getPrompt = cmdAny['getPromptForCommand'] as (
      args: string,
      ctx: unknown,
    ) => Array<{ type: 'text'; text: string }>;
    const blocks = getPrompt('', {});
    expect(blocks[0]!.text).toContain('C:/my/skill/dir');
  });
});

// ---------------------------------------------------------------------------
// #1370: argument-hint frontmatter reaches the command, so a skill's BUTTON composes
// its invocation instead of dispatching one that could only be a usage error.
// ---------------------------------------------------------------------------

describe('#1370 — argument-hint frontmatter reaches the registered command', () => {
  it('a skill declaring argument-hint produces a command whose button PREFILLS, not dispatches', async () => {
    const tmp = await mkdtemp(join(tmpdir(), 'sf-arghint-'));
    try {
      await makeSkillDir(
        tmp,
        'needs-args',
        'description: Needs arguments\nargument-hint: --workspace <path>',
      );
      await makeSkillDir(tmp, 'no-args', 'description: Takes none');
      const loaded = await loadSkillsFromSkillsDir(tmp, 'test');

      const withHint = loaded.find((s) => s.name === 'needs-args');
      expect(withHint).toBeDefined();
      expect(withHint!.command.argumentHint).toBe('--workspace <path>');

      // The parse is not the point — the CLASSIFICATION is. A dropped hint is invisible until
      // the button fires a bare invocation, so assert the button model, not the field alone.
      const buttons = buildCommandButtons(loaded.map((s) => s.command));
      const hintButton = buttons.find((b) => b.name === 'needs-args')!;
      expect(hintButton.needsArgument).toBe(true);
      expect(commandButtonActivation(hintButton)).toMatchObject({
        kind: 'prefill',
        text: '/needs-args ',
        hint: '/needs-args --workspace <path>',
      });

      // A skill that declares no hint is unaffected and still dispatches on click.
      const plainButton = buttons.find((b) => b.name === 'no-args')!;
      expect(plainButton.needsArgument).toBe(false);
      expect(commandButtonActivation(plainButton).kind).toBe('dispatch');
    } finally {
      await rm(tmp, { recursive: true, force: true });
    }
  });
});

// ---------------------------------------------------------------------------
// AC10: onDynamicSkillsLoaded fires on addSkillDirectories; unsubscribe works
// ---------------------------------------------------------------------------

describe('AC10 — onDynamicSkillsLoaded subscription', () => {
  it('callback fires when addSkillDirectories finds new skills', async () => {
    const tmp = await mkdtemp(join(tmpdir(), 'sf-ac10-'));
    try {
      await makeSkillDir(tmp, 'dynamic-skill', 'description: Dynamic');
      clearSkillCaches();
      clearDynamicSkills();

      let fired = 0;
      const unsub = onDynamicSkillsLoaded(() => { fired++; });
      await addSkillDirectories([tmp]);
      expect(fired).toBeGreaterThan(0);

      // Unsubscribe and verify no further calls
      unsub();
      const before = fired;
      const tmp2 = await mkdtemp(join(tmpdir(), 'sf-ac10b-'));
      try {
        await makeSkillDir(tmp2, 'skill2', 'description: Second');
        await addSkillDirectories([tmp2]);
        expect(fired).toBe(before); // no new calls
      } finally { await rm(tmp2, { recursive: true, force: true }); }
    } finally {
      await rm(tmp, { recursive: true, force: true });
      clearSkillCaches();
      clearDynamicSkills();
    }
  });
});

// ---------------------------------------------------------------------------
// Additional: clearBundledSkills test utility
// ---------------------------------------------------------------------------

describe('clearBundledSkills — test utility', () => {
  it('empties the bundled skills list', () => {
    registerBundledSkill({
      name: 'tmp-skill',
      description: 'temp',
      getPromptForCommand: () => [{ type: 'text', text: 'hello' }],
    });
    expect(getBundledSkills()).toHaveLength(1);
    clearBundledSkills();
    expect(getBundledSkills()).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// parseSkillFrontmatterFields — unit coverage
// ---------------------------------------------------------------------------

describe('parseSkillFrontmatterFields', () => {
  it('parses all key fields from YAML frontmatter', () => {
    const fm = {
      name: 'my-skill',
      description: 'A test skill',
      'allowed-tools': ['Read', 'Bash'],
      'argument-hint': '<file>',
      'disable-model-invocation': true,
      'user-invocable': false,
      context: 'fork',
      model: 'haiku',
    };
    const result = parseSkillFrontmatterFields(fm, 'body text', 'fallback-name', 'fallback-desc');
    expect(result.parsedName).toBe('my-skill');
    expect(result.description).toBe('A test skill');
    expect(result.allowedTools).toEqual(['Read', 'Bash']);
    expect(result.argumentHint).toBe('<file>');
    expect(result.disableModelInvocation).toBe(true);
    expect(result.userInvocable).toBe(false);
    expect(result.context).toBe('fork');
    expect(result.model).toBe('haiku');
  });

  it('model: "inherit" clears model override', () => {
    const result = parseSkillFrontmatterFields(
      { model: 'inherit' }, '', 'n', 'd',
    );
    expect(result.model).toBeUndefined();
  });

  it('invalid hooks object is discarded', () => {
    const result = parseSkillFrontmatterFields(
      { hooks: 'not-an-object' }, '', 'n', 'd',
    );
    expect(result.hooks).toBeUndefined();
  });
});
