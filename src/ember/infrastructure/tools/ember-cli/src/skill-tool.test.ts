// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Tests for skill-tool.ts
// Covers AC1-AC10.

import { test, expect, describe } from 'bun:test';
import { buildSkillTool } from './skill-tool.ts';
import type {
  SkillToolDeps,
  SkillEntry,
  SkillPermissionRules,
  AgentRunResult,
  SkillOutput,
} from './skill-tool.ts';

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

function makeCtx(toolUseId = 'test-skill-id'): Parameters<ReturnType<typeof buildSkillTool>['call']>[1] {
  return {
    options: {},
    abortController: new AbortController(),
    getAppState: () => ({}),
    setAppState: async () => {},
    setAppStateForTasks: () => {},
    readFileState: new Map(),
    messages: [],
    appendSystemMessage: () => {},
    nestedMemoryAttachmentTriggers: new Set(),
    loadedNestedMemoryPaths: new Set(),
    dynamicSkillDirTriggers: new Set(),
    discoveredSkillNames: new Set(),
    fileReadingLimits: { maxTokens: 100_000, maxSizeBytes: 10_000_000 },
    globLimits: { maxResults: 1000 },
    toolUseId,
  } as unknown as Parameters<ReturnType<typeof buildSkillTool>['call']>[1];
}

function makeSkill(name: string, overrides: Partial<SkillEntry> = {}): SkillEntry {
  return {
    name,
    source: 'local',
    type: 'prompt',
    content: `Skill content for ${name}: $ARGUMENTS`,
    ...overrides,
  };
}

function makeDeps(
  skills: SkillEntry[] = [],
  rules: SkillPermissionRules = { denyRules: [], allowRules: [] },
  overrides: Partial<SkillToolDeps> = {},
): SkillToolDeps {
  return {
    getSkillRegistry: () => skills,
    getPermissionRules: () => rules,
    async askPermission(_skillName: string, _suggestedRule: string) {
      return true; // auto-approve
    },
    async expandBangCommands(content: string) {
      return content; // no-op expansion
    },
    async runSubAgent(promptContent: string, toolUseId: string): Promise<AgentRunResult> {
      return {
        agentId: `agent-${toolUseId}`,
        finalText: `Agent processed: ${promptContent.slice(0, 30)}`,
        messages: [],
      };
    },
    registerInCompactionState(_name: string, _content: string, _toolUseId: string) {},
    async fetchRemoteSkill(_url: string): Promise<string> {
      return '---\ntitle: Remote Skill\n---\n# Remote Content\nHello from remote.';
    },
    getRemoteCatalog: () => null,
    getLocalSkillsDir: () => '/home/user/.ember/skills',
    applyModelOverride: (_model: string) => {},
    applyEffortOverride: (_effort: string) => {},
    applyToolModifier: (_tools?: string[], _disallowedTools?: string[]) => {},
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// AC1: Invoking a known skill injects its content
// ---------------------------------------------------------------------------

describe('Skill — inline invocation', () => {
  test('AC1: invoking a known skill returns its processed content', async () => {
    const skills = [makeSkill('my-skill', { content: 'Do this important thing.' })];
    const deps = makeDeps(skills);
    const tool = buildSkillTool(deps);
    const result = await tool.call(
      { skill: 'my-skill' },
      makeCtx(),
      async () => true,
      undefined,
    );
    expect((result.data as SkillOutput).mode).toBe('inline');
    expect((result.data as Extract<SkillOutput, { mode: 'inline' }>).content).toBe('Do this important thing.');
  });
});

// ---------------------------------------------------------------------------
// AC2: $ARGUMENTS interpolation
// ---------------------------------------------------------------------------

describe('Skill — arguments interpolation', () => {
  test('AC2: $ARGUMENTS replaced with args value', async () => {
    const skills = [makeSkill('greet', { content: 'Hello, $ARGUMENTS!' })];
    const deps = makeDeps(skills);
    const tool = buildSkillTool(deps);
    const result = await tool.call(
      { skill: 'greet', args: 'World' },
      makeCtx(),
      async () => true,
      undefined,
    );
    const data = result.data as { content: string };
    expect(data.content).toBe('Hello, World!');
  });

  test('$ARGUMENTS replaced with empty string when args not provided', async () => {
    const skills = [makeSkill('noop', { content: 'Args: $ARGUMENTS.' })];
    const deps = makeDeps(skills);
    const tool = buildSkillTool(deps);
    const result = await tool.call(
      { skill: 'noop' },
      makeCtx(),
      async () => true,
      undefined,
    );
    const data = result.data as { content: string };
    expect(data.content).toBe('Args: .');
  });
});

// ---------------------------------------------------------------------------
// AC3: Skill not in registry → validation error
// ---------------------------------------------------------------------------

describe('Skill — registry validation', () => {
  test('AC3: unknown skill throws error', async () => {
    const deps = makeDeps([]);
    const tool = buildSkillTool(deps);
    await expect(
      tool.call({ skill: 'nonexistent' }, makeCtx(), async () => true, undefined),
    ).rejects.toThrow("not found");
  });
});

// ---------------------------------------------------------------------------
// AC4: disableModelInvocation → error
// ---------------------------------------------------------------------------

describe('Skill — disableModelInvocation', () => {
  test('AC4: skill with disableModelInvocation throws', async () => {
    const skills = [makeSkill('disabled', { disableModelInvocation: true })];
    const deps = makeDeps(skills);
    const tool = buildSkillTool(deps);
    await expect(
      tool.call({ skill: 'disabled' }, makeCtx(), async () => true, undefined),
    ).rejects.toThrow('disabled');
  });
});

// ---------------------------------------------------------------------------
// AC5: Forked skill runs in isolated sub-agent
// ---------------------------------------------------------------------------

describe('Skill — forked execution', () => {
  test('AC5: forked skill returns agentId and final text result', async () => {
    const skills = [makeSkill('forked-skill', {
      content: 'Agent task content here.',
      executionMode: 'fork',
    })];
    const deps = makeDeps(skills, { denyRules: [], allowRules: ['forked-skill'] }, {
      async runSubAgent(_content: string, toolUseId: string): Promise<AgentRunResult> {
        return {
          agentId: `agent-${toolUseId}`,
          finalText: 'Task completed successfully.',
          messages: [],
        };
      },
    });
    const tool = buildSkillTool(deps);
    const result = await tool.call(
      { skill: 'forked-skill' },
      makeCtx('fork-tool-id'),
      async () => true,
      undefined,
    );
    expect((result.data as SkillOutput).mode).toBe('fork');
    const data = result.data as { agentId: string; result: string };
    expect(data.agentId).toBe('agent-fork-tool-id');
    expect(data.result).toBe('Task completed successfully.');
  });
});

// ---------------------------------------------------------------------------
// AC6: Leading / stripped from skill name
// ---------------------------------------------------------------------------

describe('Skill — leading slash stripping', () => {
  test('AC6: /my-skill is equivalent to my-skill', async () => {
    const skills = [makeSkill('my-skill', { content: 'Hello from skill' })];
    const deps = makeDeps(skills);
    const tool = buildSkillTool(deps);
    const result = await tool.call(
      { skill: '/my-skill' },
      makeCtx(),
      async () => true,
      undefined,
    );
    expect((result.data as SkillOutput).skillName).toBe('my-skill');
  });
});

// ---------------------------------------------------------------------------
// AC7: Context modifiers applied after skill expansion
// ---------------------------------------------------------------------------

describe('Skill — context modifiers', () => {
  test('AC7: model override applied after skill expansion', async () => {
    let appliedModel: string | undefined;
    const skills = [makeSkill('model-skill', { model: 'qwen-3.6-haiku', content: 'Do thing' })];
    const deps = makeDeps(skills, { denyRules: [], allowRules: [] }, {
      applyModelOverride: (model: string) => { appliedModel = model; },
    });
    const tool = buildSkillTool(deps);
    await tool.call({ skill: 'model-skill' }, makeCtx(), async () => true, undefined);
    expect(appliedModel).toBe('qwen-3.6-haiku');
  });

  test('AC7: tool modifier applied when skill has tools list', async () => {
    let appliedTools: string[] | undefined;
    const skills = [makeSkill('tool-skill', {
      tools: ['Bash', 'Read'],
      content: 'Use only bash and read',
    })];
    const deps = makeDeps(skills, { denyRules: [], allowRules: [] }, {
      applyToolModifier: (tools?: string[], _disallowed?: string[]) => {
        appliedTools = tools;
      },
    });
    const tool = buildSkillTool(deps);
    await tool.call({ skill: 'tool-skill' }, makeCtx(), async () => true, undefined);
    expect(appliedTools).toEqual(['Bash', 'Read']);
  });
});

// ---------------------------------------------------------------------------
// AC8: Deny rule blocks invocation
// ---------------------------------------------------------------------------

describe('Skill — deny rules', () => {
  test('AC8: deny rule matching skill name blocks invocation', async () => {
    const skills = [makeSkill('dangerous-skill', { content: 'Dangerous content' })];
    const rules: SkillPermissionRules = {
      denyRules: ['dangerous-skill'],
      allowRules: [],
    };
    const deps = makeDeps(skills, rules);
    const tool = buildSkillTool(deps);
    await expect(
      tool.call({ skill: 'dangerous-skill' }, makeCtx(), async () => true, undefined),
    ).rejects.toThrow('blocked by a deny rule');
  });

  test('AC8: deny :* prefix pattern blocks matching skills', async () => {
    const skills = [makeSkill('internal:run-all', { content: 'Run everything' })];
    const rules: SkillPermissionRules = {
      denyRules: ['internal:*'],
      allowRules: [],
    };
    const deps = makeDeps(skills, rules);
    const tool = buildSkillTool(deps);
    await expect(
      tool.call({ skill: 'internal:run-all' }, makeCtx(), async () => true, undefined),
    ).rejects.toThrow('blocked by a deny rule');
  });
});

// ---------------------------------------------------------------------------
// AC9: Skills with only safe properties auto-allowed without prompt
// ---------------------------------------------------------------------------

describe('Skill — auto-allow safe skills', () => {
  test('AC9: skill with only safe properties does not prompt for permission', async () => {
    let askCalled = false;
    // Safe: only has name, source, type, content, description, model
    const skills = [makeSkill('safe-skill', {
      description: 'A safe skill',
      model: 'qwen-3.6-haiku',
    })];
    const deps = makeDeps(skills, { denyRules: [], allowRules: [] }, {
      async askPermission(_name: string, _rule: string) {
        askCalled = true;
        return true;
      },
    });
    const tool = buildSkillTool(deps);
    await tool.call({ skill: 'safe-skill' }, makeCtx(), async () => true, undefined);
    expect(askCalled).toBe(false);
  });

  test('AC9: skill with tools property prompts for permission', async () => {
    let askCalled = false;
    const skills = [makeSkill('unsafe-skill', { tools: ['Bash'] })];
    const deps = makeDeps(skills, { denyRules: [], allowRules: [] }, {
      async askPermission(_name: string, _rule: string) {
        askCalled = true;
        return true;
      },
    });
    const tool = buildSkillTool(deps);
    await tool.call({ skill: 'unsafe-skill' }, makeCtx(), async () => true, undefined);
    expect(askCalled).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// AC10: Remote canonical skills fetched, cached, frontmatter stripped
// ---------------------------------------------------------------------------

describe('Skill — remote canonical skills', () => {
  test('AC10: remote skill content is fetched and frontmatter is stripped', async () => {
    let fetchCalled = false;
    const catalog = [{ slug: 'remote-skill', contentUrl: 'https://content.example.com/remote-skill.md' }];
    const deps = makeDeps([], { denyRules: [], allowRules: [] }, {
      getRemoteCatalog: () => catalog,
      async fetchRemoteSkill(_url: string): Promise<string> {
        fetchCalled = true;
        return '---\ntitle: Remote\nauthor: test\n---\n# Remote Skill Content\nDo the remote thing with $ARGUMENTS.';
      },
    });
    const tool = buildSkillTool(deps);
    const result = await tool.call(
      { skill: 'remote-skill', args: 'testarg' },
      makeCtx(),
      async () => true,
      undefined,
    );
    expect(fetchCalled).toBe(true);
    expect((result.data as SkillOutput).mode).toBe('remote');
    const data = result.data as { content: string };
    // Frontmatter should be stripped
    expect(data.content).not.toContain('title: Remote');
    expect(data.content).toContain('Remote Skill Content');
    // $ARGUMENTS interpolated
    expect(data.content).toContain('testarg');
  });

  test('AC10: ${EMBER_SKILL_DIR} substituted with local skills dir', async () => {
    const catalog = [{ slug: 'dir-skill', contentUrl: 'https://example.com/dir.md' }];
    const deps = makeDeps([], { denyRules: [], allowRules: [] }, {
      getRemoteCatalog: () => catalog,
      getLocalSkillsDir: () => '/home/user/.ember/skills',
      async fetchRemoteSkill(_url: string): Promise<string> {
        return 'Skills dir: ${EMBER_SKILL_DIR}/templates';
      },
    });
    const tool = buildSkillTool(deps);
    const result = await tool.call(
      { skill: 'dir-skill' },
      makeCtx(),
      async () => true,
      undefined,
    );
    const data = result.data as { content: string };
    expect(data.content).toContain('/home/user/.ember/skills');
    expect(data.content).not.toContain('${EMBER_SKILL_DIR}');
  });
});
