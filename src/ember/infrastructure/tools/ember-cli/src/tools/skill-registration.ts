// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// tools/skill-registration.ts — the registered `Skill` tool, backed by
// skill-framework.ts parsing and skill-tool.ts invocation semantics.
//
// Skills are SKILL.md files under <cwd>/.ember/skills/<name>/ and
// <EMBER_HOME or ~/.ember>/skills/<name>/. Project skills shadow home skills
// of the same name. Invoking a skill returns its instructions (with $ARGUMENTS
// and ${EMBER_SKILL_DIR} substituted) as the tool result so the model follows them.

import { existsSync, readdirSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { z } from "zod";
import { toJSONSchema } from "zod/v4";
import { buildSkillTool } from "../skill-tool.ts";
import type { SkillEntry, SkillOutput, SkillToolDeps } from "../skill-tool.ts";
import { parseSkillFrontmatterFields, parseSkillMd } from "../skill-framework.ts";
import type { Tool } from "../core/tool-interface.ts";

// Skill directories contributed by loaded plugins (extensions/plugin-loader.ts).
let extraSkillDirs: string[] = [];

export function setExtraSkillDirs(dirs: string[]): void {
  extraSkillDirs = [...dirs];
}

export function skillSearchDirs(cwd: string = process.cwd()): string[] {
  const home = process.env["EMBER_HOME"] || join(homedir(), ".ember");
  return [join(cwd, ".ember", "skills"), join(home, "skills"), ...extraSkillDirs];
}

/** Synchronous discovery; first directory wins on a name clash. Never throws. */
export function discoverSkills(cwd: string = process.cwd()): SkillEntry[] {
  const found = new Map<string, SkillEntry>();
  for (const dir of skillSearchDirs(cwd)) {
    let entries: string[];
    try {
      entries = readdirSync(dir);
    } catch {
      continue;
    }
    for (const entry of entries.sort()) {
      const skillDir = join(dir, entry);
      const md = join(skillDir, "SKILL.md");
      try {
        if (!existsSync(md)) continue;
        const raw = readFileSync(md, "utf-8").replace(/\r\n/g, "\n");
        const { frontmatter, body, error } = parseSkillMd(raw);
        const f = parseSkillFrontmatterFields(frontmatter, body, entry, entry);
        if (found.has(f.parsedName)) continue;
        found.set(f.parsedName, {
          name: f.parsedName,
          source: dir,
          type: "prompt",
          description: f.description,
          content: body.replace(/\$\{EMBER_SKILL_DIR\}/g, skillDir.replace(/\\/g, "/")),
          disableModelInvocation: f.disableModelInvocation,
          argumentHint: f.argumentHint,
          userInvocable: f.userInvocable,
          ...(error ? { warning: `skill ${f.parsedName}: ${error}` } : {}),
        });
      } catch {
        continue; // unreadable skill: skip, never crash
      }
    }
  }
  return [...found.values()];
}

const SkillInputSchema = z
  .object({
    skill: z.string().describe("Name of the skill to invoke"),
    args: z.string().optional().describe("Optional arguments substituted for $ARGUMENTS"),
  })
  .strict();

type SkillInput = z.infer<typeof SkillInputSchema>;

export function buildRegisteredSkillTool(cwdProvider: () => string = () => process.cwd()): Tool {
  const deps: SkillToolDeps = {
    getSkillRegistry: () => discoverSkills(cwdProvider()),
    getPermissionRules: () => ({ denyRules: [], allowRules: [] }),
    askPermission: async () => true,
    expandBangCommands: async (c) => c,
    runSubAgent: async () => {
      throw new Error("fork-mode skills are not supported; the skill runs inline");
    },
    registerInCompactionState: () => {},
    fetchRemoteSkill: async () => {
      throw new Error("remote skills are not available");
    },
    getRemoteCatalog: () => null,
    getLocalSkillsDir: () => skillSearchDirs(cwdProvider())[0]!,
    applyModelOverride: () => {},
    applyEffortOverride: () => {},
    applyToolModifier: () => {},
  };
  const base = buildSkillTool(deps) as Tool<SkillInput, SkillOutput>;
  const wrapped: Tool<SkillInput, SkillOutput> = {
    ...base,
    name: "Skill",
    inputSchema: SkillInputSchema,
    inputJSONSchema: toJSONSchema(SkillInputSchema) as Record<string, unknown>,
    isReadOnly: () => true,
    isConcurrencySafe: () => true,
    description: () => {
      const skills = discoverSkills(cwdProvider()).filter((s) => !s.disableModelInvocation);
      const list = skills.length
        ? skills.map((s) => `- ${s.name}: ${s.description ?? ""}`).join("\n")
        : "(none installed)";
      return (
        "Invoke a skill by name; its instructions are returned and you must then follow them. " +
        "Skills live in .ember/skills/<name>/SKILL.md. Available skills:\n" +
        list
      );
    },
    call: async (args, context, canUseTool, parent, onEvent) => {
      const name = args.skill.replace(/^\//, "");
      const all = discoverSkills(cwdProvider());
      if (!all.some((s) => s.name === name)) {
        const names = all.map((s) => s.name).join(", ") || "none";
        throw new Error(`Skill "${name}" not found. Available skills: ${names}`);
      }
      return base.call(args, context, canUseTool, parent, onEvent);
    },
    mapToolResultToToolResultBlockParam: (out, toolUseId) => {
      const content =
        out.mode === "fork"
          ? out.result
          : `Skill "${out.skillName}" loaded. Follow these instructions:\n\n${out.content}`;
      return { type: "tool_result", tool_use_id: toolUseId, content };
    },
  };
  return wrapped as unknown as Tool;
}

export const SkillTool: Tool = buildRegisteredSkillTool();
