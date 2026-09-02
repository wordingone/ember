// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// skill-tool.ts
// The /skill slash-command tool: registry lookup, permission checks, content
// expansion, fork delegation, and remote catalog integration.
// Contract: src/skill-tool.test.ts (AC1-AC10).

import { buildTool } from './core/tool-interface.ts';
import type { Tool, ToolUseContext, ToolResult } from './core/tool-interface.ts';

// ---------------------------------------------------------------------------
// Exported types
// ---------------------------------------------------------------------------

export interface SkillEntry {
  name: string;
  source: string;
  type: string;
  content?: string;
  description?: string;
  model?: string;
  tools?: string[];
  disableModelInvocation?: boolean;
  executionMode?: string;
}

export interface SkillPermissionRules {
  denyRules: string[];
  allowRules: string[];
}

export interface AgentRunResult {
  agentId: string;
  finalText: string;
  messages: unknown[];
}

export type SkillOutput =
  | { mode: 'inline'; skillName: string; content: string }
  | { mode: 'fork'; skillName: string; agentId: string; result: string }
  | { mode: 'remote'; skillName: string; content: string };

interface CatalogEntry {
  slug: string;
  contentUrl: string;
}

export interface SkillToolDeps {
  getSkillRegistry(): SkillEntry[];
  getPermissionRules(): SkillPermissionRules;
  askPermission(skillName: string, suggestedRule: string): Promise<boolean>;
  expandBangCommands(content: string): Promise<string>;
  runSubAgent(promptContent: string, toolUseId: string): Promise<AgentRunResult>;
  registerInCompactionState(name: string, content: string, toolUseId: string): void;
  fetchRemoteSkill(url: string): Promise<string>;
  getRemoteCatalog(): CatalogEntry[] | null;
  getLocalSkillsDir(): string;
  applyModelOverride(model: string): void;
  applyEffortOverride(effort: string): void;
  applyToolModifier(tools?: string[], disallowedTools?: string[]): void;
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/** Strips YAML frontmatter delimited by `---` from the top of content. */
function stripFrontmatter(content: string): string {
  if (!content.startsWith('---')) return content;
  const end = content.indexOf('---', 3);
  if (end === -1) return content;
  return content.slice(end + 3).trimStart();
}

/** Returns true when `rule` matches `skillName` (exact or `:*` wildcard). */
function matchesDenyRule(rule: string, skillName: string): boolean {
  if (rule.endsWith(':*')) {
    const prefix = rule.slice(0, -1); // e.g. 'internal:*' → 'internal:'
    return skillName.startsWith(prefix);
  }
  return rule === skillName;
}

/** Returns true when the skill has no unsafe properties (no tools list). */
function isSafeSkill(skill: SkillEntry): boolean {
  return !skill.tools || skill.tools.length === 0;
}

// ---------------------------------------------------------------------------
// buildSkillTool
// ---------------------------------------------------------------------------

interface SkillInput {
  skill: string;
  args?: string;
}

export function buildSkillTool(deps: SkillToolDeps): Tool<SkillInput, SkillOutput> {
  return buildTool<SkillInput, SkillOutput>({
    name: 'skill',
    description: () => 'Invoke a registered skill by name',
    mapToolResultToToolResultBlockParam: (content, toolUseId) => ({
      type: 'tool_result',
      tool_use_id: toolUseId,
      content: JSON.stringify(content),
    }),
    async call(
      input: SkillInput,
      context: ToolUseContext,
    ): Promise<ToolResult<SkillOutput>> {
      // AC6: strip leading slash from skill name
      const skillName = input.skill.startsWith('/') ? input.skill.slice(1) : input.skill;
      const argsValue = input.args ?? '';

      // Look up in local registry first
      const registry = deps.getSkillRegistry();
      const localSkill = registry.find((s) => s.name === skillName);

      // Check remote catalog if not in local registry
      const catalog = deps.getRemoteCatalog();
      const remoteCatalogEntry = !localSkill && catalog
        ? catalog.find((c) => c.slug === skillName)
        : undefined;

      if (!localSkill && !remoteCatalogEntry) {
        throw new Error(`Skill "${skillName}" not found in registry or remote catalog`);
      }

      // Determine if this is a remote skill
      const isRemote = !localSkill && remoteCatalogEntry !== undefined;

      // Effective skill properties (local wins; remote gets defaults)
      const skill: SkillEntry = localSkill ?? {
        name: skillName,
        source: 'remote',
        type: 'prompt',
      };

      // AC4: disableModelInvocation guard
      if (skill.disableModelInvocation) {
        throw new Error(`Skill "${skillName}" has model invocation disabled`);
      }

      // AC8: deny rule check
      const rules = deps.getPermissionRules();
      const denied = rules.denyRules.some((rule) => matchesDenyRule(rule, skillName));
      if (denied) {
        throw new Error(`Skill "${skillName}" is blocked by a deny rule`);
      }

      // AC9: permission prompt only when skill has tools
      if (!isSafeSkill(skill)) {
        await deps.askPermission(skillName, skillName);
      }

      // AC7: apply context modifiers
      if (skill.model) {
        deps.applyModelOverride(skill.model);
      }
      if (skill.tools && skill.tools.length > 0) {
        deps.applyToolModifier(skill.tools, undefined);
      }

      // Fetch and process content
      let rawContent: string;
      if (isRemote) {
        // AC10: fetch from remote catalog
        rawContent = await deps.fetchRemoteSkill(remoteCatalogEntry!.contentUrl);
        // Strip frontmatter
        rawContent = stripFrontmatter(rawContent);
        // Substitute ${EMBER_SKILL_DIR}
        const localSkillsDir = deps.getLocalSkillsDir();
        rawContent = rawContent.replace(/\$\{EMBER_SKILL_DIR\}/g, localSkillsDir);
        // AC2: interpolate $ARGUMENTS
        const content = rawContent.replace(/\$ARGUMENTS/g, argsValue);
        deps.registerInCompactionState(skillName, content, context.toolUseId ?? '');
        return {
          data: { mode: 'remote', skillName, content },
        };
      }

      // Local skill
      rawContent = skill.content ?? '';

      // Expand bang commands
      rawContent = await deps.expandBangCommands(rawContent);

      // AC2: interpolate $ARGUMENTS
      const content = rawContent.replace(/\$ARGUMENTS/g, argsValue);

      deps.registerInCompactionState(skillName, content, context.toolUseId ?? '');

      // AC5: fork mode — delegate to sub-agent
      if (skill.executionMode === 'fork') {
        const agentRun = await deps.runSubAgent(content, context.toolUseId ?? '');
        return {
          data: {
            mode: 'fork',
            skillName,
            agentId: agentRun.agentId,
            result: agentRun.finalText,
          },
        };
      }

      // AC1: inline mode
      return {
        data: { mode: 'inline', skillName, content },
      };
    },
  });
}
