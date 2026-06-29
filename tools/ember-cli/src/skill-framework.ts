// skill-framework.ts
// Skill discovery, registration, caching, conditional path-gating, bundled
// skills, and MCP skill builder registry.
// Contract: src/skill-framework.test.ts (AC1-AC10).

import { readdir, readFile } from 'fs/promises';
import { join, resolve } from 'path';
import { tmpdir } from 'os';
import type { RegistryCommand, CommandContext, CommandResult } from './types/command-types.ts';

// ---------------------------------------------------------------------------
// Skill framework settings
// ---------------------------------------------------------------------------

interface SkillFrameworkSettings {
  skillsDir?: string;
}

let _settings: SkillFrameworkSettings = {};

export function setSkillFrameworkSettings(settings: SkillFrameworkSettings): void {
  _settings = { ..._settings, ...settings };
}

// ---------------------------------------------------------------------------
// Simple YAML frontmatter parser (no library dependency)
// ---------------------------------------------------------------------------

function parseSimpleYamlValue(raw: string): unknown {
  const s = raw.trim();
  if (s === 'true') return true;
  if (s === 'false') return false;
  if (s.startsWith('[')) {
    try { return JSON.parse(s); } catch { return s; }
  }
  if (s.startsWith('{')) {
    try { return JSON.parse(s); } catch { return s; }
  }
  // Quoted string
  if ((s.startsWith('"') && s.endsWith('"')) || (s.startsWith("'") && s.endsWith("'"))) {
    return s.slice(1, -1);
  }
  return s;
}

function parseSimpleYaml(yaml: string): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const line of yaml.split('\n')) {
    const colonIdx = line.indexOf(':');
    if (colonIdx === -1) continue;
    const key = line.slice(0, colonIdx).trim();
    if (!key) continue;
    const value = line.slice(colonIdx + 1).trim();
    if (value === '') continue;
    result[key] = parseSimpleYamlValue(value);
  }
  return result;
}

function parseSkillMd(content: string): { frontmatter: Record<string, unknown>; body: string } {
  if (!content.startsWith('---\n')) {
    return { frontmatter: {}, body: content };
  }
  const end = content.indexOf('\n---\n', 4);
  if (end === -1) {
    return { frontmatter: {}, body: content };
  }
  const yamlStr = content.slice(4, end);
  const body = content.slice(end + 5);
  return { frontmatter: parseSimpleYaml(yamlStr), body };
}

// ---------------------------------------------------------------------------
// parseSkillFrontmatterFields — unit-testable field extraction
// ---------------------------------------------------------------------------

export interface ParsedSkillFrontmatter {
  parsedName: string;
  description: string;
  allowedTools?: string[];
  argumentHint?: string;
  disableModelInvocation?: boolean;
  userInvocable?: boolean;
  context?: string;
  model?: string;
  paths?: string[];
  hooks?: Record<string, unknown>;
}

export function parseSkillFrontmatterFields(
  fm: Record<string, unknown>,
  _body: string,
  fallbackName: string,
  fallbackDesc: string,
): ParsedSkillFrontmatter {
  const result: ParsedSkillFrontmatter = {
    parsedName: typeof fm['name'] === 'string' ? fm['name'] : fallbackName,
    description: typeof fm['description'] === 'string' ? fm['description'] : fallbackDesc,
  };

  if (Array.isArray(fm['allowed-tools'])) {
    result.allowedTools = fm['allowed-tools'] as string[];
  }
  if (typeof fm['argument-hint'] === 'string') {
    result.argumentHint = fm['argument-hint'];
  }
  if (fm['disable-model-invocation'] === true) {
    result.disableModelInvocation = true;
  }
  if (fm['user-invocable'] === false) {
    result.userInvocable = false;
  }
  if (typeof fm['context'] === 'string') {
    result.context = fm['context'];
  }
  // model: 'inherit' → undefined (clear override)
  if (typeof fm['model'] === 'string' && fm['model'] !== 'inherit') {
    result.model = fm['model'];
  }
  if (Array.isArray(fm['paths'])) {
    result.paths = fm['paths'] as string[];
  }
  // hooks must be a non-null object (not string/array)
  if (
    fm['hooks'] !== null &&
    fm['hooks'] !== undefined &&
    typeof fm['hooks'] === 'object' &&
    !Array.isArray(fm['hooks'])
  ) {
    result.hooks = fm['hooks'] as Record<string, unknown>;
  }

  return result;
}

// ---------------------------------------------------------------------------
// Glob matching for conditional skill paths
// ---------------------------------------------------------------------------

function globToRegex(pattern: string): RegExp {
  let s = pattern.replace(/\\/g, '/');
  // Escape regex special chars except * and ?
  s = s.replace(/[.+^${}()|[\]]/g, '\\$&');
  // Handle ** before *
  s = s.replace(/\*\*/g, '__EMBER_DSTAR__');
  s = s.replace(/\*/g, '[^/]*');
  s = s.replace(/__EMBER_DSTAR__/g, '.*');
  return new RegExp(`^${s}$`);
}

function matchesGlob(filePath: string, pattern: string): boolean {
  const normalizedPath = filePath.replace(/\\/g, '/');
  const regex = globToRegex(pattern);
  return regex.test(normalizedPath);
}

function pathMatchesAnyPattern(filePath: string, patterns: string[]): boolean {
  return patterns.some((p) => matchesGlob(filePath, p));
}

// ---------------------------------------------------------------------------
// Skill command type (RegistryCommand + extra fields)
// ---------------------------------------------------------------------------

type SkillCommand = RegistryCommand & {
  isHidden?: boolean;
  context?: string;
  getPromptForCommand?: (args: string, ctx: unknown) => Array<{ type: 'text'; text: string }>;
};

// ---------------------------------------------------------------------------
// createSkillCommand — AC9
// ---------------------------------------------------------------------------

interface CreateSkillCommandOptions {
  name: string;
  description: string;
  basePath: string;
  content: string;
  isHidden?: boolean;
  context?: string;
  aliases?: string[];
  disableModelInvocation?: boolean;
}

export function createSkillCommand(opts: CreateSkillCommandOptions): SkillCommand {
  const baseFwdSlash = opts.basePath.replace(/\\/g, '/');

  function getPromptForCommand(
    _args: string,
    _ctx: unknown,
  ): Array<{ type: 'text'; text: string }> {
    const expanded = opts.content.replace(/\$\{EMBER_SKILL_DIR\}/g, baseFwdSlash);
    return [{ type: 'text', text: expanded }];
  }

  return {
    name: opts.name,
    description: opts.description,
    isHidden: opts.isHidden ?? false,
    context: opts.context,
    aliases: opts.aliases,
    disableModelInvocation: opts.disableModelInvocation,
    isEnabled: () => true,
    async execute(_args: string, _ctx: CommandContext): Promise<CommandResult | void> {
      return undefined;
    },
    getPromptForCommand,
  };
}

// ---------------------------------------------------------------------------
// Loaded skill shape returned by loadSkillsFromSkillsDir
// ---------------------------------------------------------------------------

export interface LoadedSkill {
  name: string;
  command: SkillCommand;
  isConditional: boolean;
  paths?: string[];
}

// ---------------------------------------------------------------------------
// loadSkillsFromSkillsDir — scans a directory for subdirs with SKILL.md
// ---------------------------------------------------------------------------

export async function loadSkillsFromSkillsDir(
  dir: string,
  _source: string,
): Promise<LoadedSkill[]> {
  let entries: string[];
  try {
    entries = await readdir(dir);
  } catch {
    return [];
  }

  const results: LoadedSkill[] = [];

  for (const entry of entries) {
    const skillDir = join(dir, entry);
    const skillMdPath = join(skillDir, 'SKILL.md');

    let raw: string;
    try {
      raw = await readFile(skillMdPath, 'utf-8');
    } catch {
      continue; // not a skill directory
    }

    const { frontmatter, body } = parseSkillMd(raw);
    const parsed = parseSkillFrontmatterFields(frontmatter, body, entry, entry);

    const isConditional = Array.isArray(parsed.paths) && (parsed.paths as string[]).length > 0;

    const cmd = createSkillCommand({
      name: parsed.parsedName,
      description: parsed.description,
      basePath: skillDir,
      content: body,
      isHidden: parsed.userInvocable === false,
      context: parsed.context,
      aliases: [],
      disableModelInvocation: parsed.disableModelInvocation,
    });

    results.push({
      name: parsed.parsedName,
      command: cmd,
      isConditional,
      paths: parsed.paths as string[] | undefined,
    });
  }

  return results;
}

// ---------------------------------------------------------------------------
// Module-level caches and state
// ---------------------------------------------------------------------------

const _skillDirCache = new Map<string, SkillCommand[]>();
const _dynamicActiveCommands: SkillCommand[] = [];
const _conditionalSkills: Array<{ skill: LoadedSkill; baseDir: string }> = [];
const _listeners = new Set<() => void>();

// ---------------------------------------------------------------------------
// clearSkillCaches — AC4
// ---------------------------------------------------------------------------

export function clearSkillCaches(): void {
  _skillDirCache.clear();
}

// ---------------------------------------------------------------------------
// clearDynamicSkills
// ---------------------------------------------------------------------------

export function clearDynamicSkills(): void {
  _dynamicActiveCommands.length = 0;
  _conditionalSkills.length = 0;
}

// ---------------------------------------------------------------------------
// getSkillDirCommands — AC3, AC4 (memoized per cwd)
// ---------------------------------------------------------------------------

export async function getSkillDirCommands(cwd: string): Promise<SkillCommand[]> {
  const resolvedCwd = resolve(cwd);
  if (_skillDirCache.has(resolvedCwd)) {
    return _skillDirCache.get(resolvedCwd)!;
  }

  const skillsDir = join(resolvedCwd, '.ember', 'skills');
  let loaded: LoadedSkill[] = [];
  try {
    loaded = await loadSkillsFromSkillsDir(skillsDir, 'projectSettings');
  } catch {
    // No skills dir — return empty
  }

  const commands = loaded
    .filter((s) => !s.isConditional)
    .map((s) => s.command);

  _skillDirCache.set(resolvedCwd, commands);
  return commands;
}

// ---------------------------------------------------------------------------
// addSkillDirectories — AC5, AC10
// ---------------------------------------------------------------------------

export async function addSkillDirectories(dirs: string[]): Promise<void> {
  let anyNew = false;

  for (const dir of dirs) {
    const skills = await loadSkillsFromSkillsDir(dir, 'dynamic');
    for (const skill of skills) {
      if (skill.isConditional) {
        _conditionalSkills.push({ skill, baseDir: dir });
      } else {
        _dynamicActiveCommands.push(skill.command);
      }
      anyNew = true;
    }
  }

  if (anyNew) {
    for (const listener of _listeners) {
      listener();
    }
  }
}

// ---------------------------------------------------------------------------
// Conditional skills — AC5
// ---------------------------------------------------------------------------

export function getConditionalSkillCount(): number {
  return _conditionalSkills.length;
}

export function activateConditionalSkillsForPaths(
  filePaths: string[],
  _cwd: string,
): string[] {
  const activated: string[] = [];
  const toRemove: number[] = [];

  for (let i = 0; i < _conditionalSkills.length; i++) {
    const { skill } = _conditionalSkills[i]!;
    const patterns = skill.paths ?? [];
    const matches = filePaths.some((fp) => pathMatchesAnyPattern(fp, patterns));
    if (matches) {
      _dynamicActiveCommands.push(skill.command);
      activated.push(skill.name);
      toRemove.push(i);
    }
  }

  // Remove activated skills from conditional pool (in reverse order)
  for (let i = toRemove.length - 1; i >= 0; i--) {
    _conditionalSkills.splice(toRemove[i]!, 1);
  }

  return activated;
}

// ---------------------------------------------------------------------------
// onDynamicSkillsLoaded — AC10
// ---------------------------------------------------------------------------

export function onDynamicSkillsLoaded(callback: () => void): () => void {
  _listeners.add(callback);
  return () => {
    _listeners.delete(callback);
  };
}

// ---------------------------------------------------------------------------
// Bundled skills — AC6
// ---------------------------------------------------------------------------

export interface BundledSkillDefinition {
  name: string;
  description: string;
  files?: Record<string, string>;
  getPromptForCommand: (args?: string, ctx?: unknown) => Array<{ type: 'text'; text: string }>;
}

interface StoredBundledSkill extends Omit<BundledSkillDefinition, 'getPromptForCommand'> {
  getPromptForCommand: (args: string, ctx: unknown) => Promise<Array<{ type: 'text'; text: string }>>;
}

const _bundledSkills: StoredBundledSkill[] = [];

export function registerBundledSkill(def: BundledSkillDefinition): void {
  const files = def.files ?? {};

  // Wrap getPromptForCommand to validate file paths before executing
  async function wrappedGetPromptForCommand(
    args: string,
    ctx: unknown,
  ): Promise<Array<{ type: 'text'; text: string }>> {
    for (const filePath of Object.keys(files)) {
      if (filePath.includes('..')) {
        throw new Error(`Bundled skill "${def.name}": path traversal detected in file path "${filePath}"`);
      }
    }
    return def.getPromptForCommand(args, ctx);
  }

  _bundledSkills.push({
    ...def,
    getPromptForCommand: wrappedGetPromptForCommand,
  });
}

export function getBundledSkills(): typeof _bundledSkills {
  return [..._bundledSkills];
}

export function clearBundledSkills(): void {
  _bundledSkills.length = 0;
}

export function getBundledSkillExtractDir(): string {
  return join(tmpdir(), 'ember-bundled-skills');
}

// ---------------------------------------------------------------------------
// MCP skill builders registry — AC7
// ---------------------------------------------------------------------------

interface MCPSkillBuilders {
  createSkillCommand: typeof createSkillCommand;
  parseSkillFrontmatterFields: typeof parseSkillFrontmatterFields;
}

let _mcpSkillBuilders: MCPSkillBuilders | null = null;

export function registerMCPSkillBuilders(builders: MCPSkillBuilders): void {
  _mcpSkillBuilders = builders;
}

export function getMCPSkillBuilders(): MCPSkillBuilders {
  if (_mcpSkillBuilders === null) {
    throw new Error('MCP skill builders have not been registered yet. Call registerMCPSkillBuilders first.');
  }
  return _mcpSkillBuilders;
}

// ---------------------------------------------------------------------------
// fetchMcpSkillsForClient — AC8 (always returns [])
// ---------------------------------------------------------------------------

// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function fetchMcpSkillsForClient(_client: unknown): never[] {
  return [];
}
