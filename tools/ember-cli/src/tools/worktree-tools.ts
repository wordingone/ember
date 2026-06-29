// tools/worktree-tools.ts — EnterWorktree and ExitWorktree tools.
//
// EnterWorktree: creates a new git worktree (with a timestamped branch) under
//   .ember/worktrees/<slug>, or switches into an existing known worktree by path.
// ExitWorktree: leaves the active worktree session, optionally removing the
//   worktree + branch. A no-op when no EnterWorktree session is active.
//
// git operations are injectable (gitOps) for unit-test isolation.

import { join } from "path";
import { z } from "zod";
import { buildTool } from "../core/tool-interface.ts";
import type { ToolUseContext } from "../core/tool-interface.ts";

// ---------------------------------------------------------------------------
// Slug validation
// ---------------------------------------------------------------------------

const SLUG_MAX_LENGTH = 64;
const SLUG_SEGMENT_RE = /^[A-Za-z0-9._-]+$/;

function validateWorktreeSlug(name: string): string | null {
  if (name.length > SLUG_MAX_LENGTH) {
    return `Worktree name exceeds maximum length of ${SLUG_MAX_LENGTH} characters.`;
  }
  const segments = name.split("/");
  for (const segment of segments) {
    if (!segment) {
      return `Worktree name has empty path segment.`;
    }
    if (!SLUG_SEGMENT_RE.test(segment)) {
      return `Invalid worktree name segment "${segment}": only letters, digits, dots, underscores, and dashes are allowed.`;
    }
  }
  return null;
}

function generateWorktreeSlug(base?: string): string {
  const timestamp = Date.now();
  if (base) return `${base}-${timestamp}`;
  return `worktree-${timestamp}`;
}

// ---------------------------------------------------------------------------
// Injectable git operations
// ---------------------------------------------------------------------------

export interface GitOps {
  getGitRoot(cwd: string): Promise<string>;
  createWorktree(opts: { gitRoot: string; path: string; branch: string }): Promise<void>;
  isKnownWorktree(opts: { gitRoot: string; path: string }): Promise<boolean>;
  countUncommittedFiles(cwd: string): Promise<number>;
  countAheadCommits(cwd: string, originalBranch: string): Promise<number>;
  removeWorktree(opts: { gitRoot: string; path: string }): Promise<void>;
  deleteWorktreeAndBranch(opts: { path: string; branch?: string | null }): Promise<void>;
  getCurrentBranch(cwd: string): Promise<string | null>;
  isInsideGitRepo(cwd: string): Promise<boolean>;
}

// Bun.spawn interop — Bun runtime provides this globally
type BunSpawn = (
  cmd: string[],
  opts: { cwd: string; stdout: "pipe"; stderr: "pipe" },
) => { exited: Promise<number>; stdout: ReadableStream<Uint8Array>; stderr: ReadableStream<Uint8Array> };

function bunSpawn(
  cmd: string[],
  opts: { cwd: string; stdout: "pipe"; stderr: "pipe" },
): ReturnType<BunSpawn> {
  return (globalThis as unknown as { Bun: { spawn: BunSpawn } }).Bun.spawn(cmd, opts);
}

const defaultGitOps: GitOps = {
  async getGitRoot(cwd) {
    const proc = bunSpawn(["git", "rev-parse", "--show-toplevel"], {
      cwd,
      stdout: "pipe",
      stderr: "pipe",
    });
    const text = await new Response(proc.stdout).text();
    const exitCode = await proc.exited;
    if (exitCode !== 0) throw new Error("Not inside a git repository.");
    return text.trim();
  },

  async createWorktree({ gitRoot, path, branch }) {
    const proc = bunSpawn(["git", "worktree", "add", "-b", branch, path], {
      cwd: gitRoot,
      stdout: "pipe",
      stderr: "pipe",
    });
    const exitCode = await proc.exited;
    if (exitCode !== 0) {
      const err = await new Response(proc.stderr).text();
      throw new Error(`Failed to create worktree: ${err}`);
    }
  },

  async isKnownWorktree({ gitRoot, path }) {
    const proc = bunSpawn(["git", "worktree", "list", "--porcelain"], {
      cwd: gitRoot,
      stdout: "pipe",
      stderr: "pipe",
    });
    const text = await new Response(proc.stdout).text();
    await proc.exited;
    return text.includes(path);
  },

  async countUncommittedFiles(cwd) {
    const proc = bunSpawn(["git", "status", "--porcelain"], {
      cwd,
      stdout: "pipe",
      stderr: "pipe",
    });
    const exitCode = await proc.exited;
    if (exitCode !== 0) throw new Error("git status failed");
    const text = await new Response(proc.stdout).text();
    return text
      .split("\n")
      .filter((l) => l.trim().length > 0).length;
  },

  async countAheadCommits(cwd, originalBranch) {
    const proc = bunSpawn(["git", "rev-list", "--count", `${originalBranch}..HEAD`], {
      cwd,
      stdout: "pipe",
      stderr: "pipe",
    });
    const exitCode = await proc.exited;
    if (exitCode !== 0) throw new Error("git rev-list failed");
    const text = await new Response(proc.stdout).text();
    return parseInt(text.trim(), 10) || 0;
  },

  async removeWorktree({ gitRoot, path }) {
    const proc = bunSpawn(["git", "worktree", "remove", "--force", path], {
      cwd: gitRoot,
      stdout: "pipe",
      stderr: "pipe",
    });
    const exitCode = await proc.exited;
    if (exitCode !== 0) {
      const err = await new Response(proc.stderr).text();
      throw new Error(`Failed to remove worktree: ${err}`);
    }
  },

  async deleteWorktreeAndBranch({ path, branch }) {
    try {
      const { rmSync } = await import("fs");
      rmSync(path, { recursive: true, force: true });
    } catch {
      // best-effort
    }
    if (branch) {
      const proc = bunSpawn(["git", "branch", "-D", branch], {
        cwd: process.cwd(),
        stdout: "pipe",
        stderr: "pipe",
      });
      await proc.exited;
    }
  },

  async getCurrentBranch(cwd) {
    const proc = bunSpawn(["git", "rev-parse", "--abbrev-ref", "HEAD"], {
      cwd,
      stdout: "pipe",
      stderr: "pipe",
    });
    const exitCode = await proc.exited;
    if (exitCode !== 0) return null;
    return (await new Response(proc.stdout).text()).trim() || null;
  },

  async isInsideGitRepo(cwd) {
    const proc = bunSpawn(["git", "rev-parse", "--git-dir"], {
      cwd,
      stdout: "pipe",
      stderr: "pipe",
    });
    const exitCode = await proc.exited;
    return exitCode === 0;
  },
};

// Mutable reference — tests can swap this out.
export let gitOps: GitOps = defaultGitOps;
export function _overrideGitOps(ops: GitOps): void {
  gitOps = ops;
}
export function _resetGitOps(): void {
  gitOps = defaultGitOps;
}

// ---------------------------------------------------------------------------
// CWD change (injectable in tests)
// ---------------------------------------------------------------------------

export let doChangeCwd = (path: string): void => {
  process.chdir(path);
};
export function _overrideChangeCwd(fn: (path: string) => void): void {
  doChangeCwd = fn;
}

// ---------------------------------------------------------------------------
// Active session tracking
// ---------------------------------------------------------------------------

interface WorktreeSession {
  worktreePath: string;
  worktreeBranch: string | null;
  originalCwd: string;
  tmuxSessionName?: string;
}

let _activeWorktreeSession: WorktreeSession | null = null;

export function _getActiveWorktreeSession(): WorktreeSession | null {
  return _activeWorktreeSession;
}

// ---------------------------------------------------------------------------
// EnterWorktree
// ---------------------------------------------------------------------------

const EnterWorktreeInputSchema = z
  .object({
    name: z.string().optional(),
    path: z.string().optional(),
  })
  .strict();

type EnterWorktreeInput = z.infer<typeof EnterWorktreeInputSchema>;

export const EnterWorktreeTool = buildTool<EnterWorktreeInput, unknown>({
  name: "EnterWorktree",
  inputSchema: EnterWorktreeInputSchema,

  validateInput: (rawInput: unknown) => {
    const input = rawInput as EnterWorktreeInput;
    if (input.name !== undefined) {
      const err = validateWorktreeSlug(input.name);
      if (err) {
        return { result: false as const, message: err, errorCode: "INVALID_SLUG" };
      }
    }
    return { result: true as const };
  },

  call: async (rawArgs: unknown, context: ToolUseContext) => {
    const args = rawArgs as EnterWorktreeInput;

    if (_activeWorktreeSession) {
      throw new Error(
        "Already inside a worktree session. Call ExitWorktree before entering another.",
      );
    }

    if (args.name !== undefined) {
      const err = validateWorktreeSlug(args.name);
      if (err) throw new Error(err);
    }

    const state = context.getAppState() as Record<string, unknown>;
    const originalCwd = (state["cwd"] as string | undefined) ?? process.cwd();

    // --- Enter existing worktree by path ---
    if (args.path) {
      const isInsideGit = await gitOps.isInsideGitRepo(originalCwd);
      if (isInsideGit) {
        const gitRoot = await gitOps.getGitRoot(originalCwd);
        const isKnown = await gitOps.isKnownWorktree({ gitRoot, path: args.path });
        if (!isKnown) {
          throw new Error(
            `Path "${args.path}" is not a known worktree for this repository.`,
          );
        }
      }
      doChangeCwd(args.path);
      await context.setAppState((prev) => ({
        ...(prev as Record<string, unknown>),
        cwd: args.path,
      }));
      _activeWorktreeSession = {
        worktreePath: args.path,
        worktreeBranch: null,
        originalCwd,
      };
      return {
        data: {
          worktreePath: args.path,
          message: `Entered existing worktree at \`${args.path}\`. Use ExitWorktree to leave mid-session.`,
        },
      };
    }

    // --- Create new worktree ---
    const isInsideGit = await gitOps.isInsideGitRepo(originalCwd);
    if (!isInsideGit) {
      throw new Error(
        "Not inside a git repository. Cannot create a worktree without an active git repo.",
      );
    }

    const gitRoot = await gitOps.getGitRoot(originalCwd);
    const slug = args.name ? generateWorktreeSlug(args.name) : generateWorktreeSlug();
    const worktreePath = join(gitRoot, ".ember", "worktrees", slug);
    const branchName = `worktree/${slug}`;

    await gitOps.createWorktree({ gitRoot, path: worktreePath, branch: branchName });
    doChangeCwd(worktreePath);
    await context.setAppState((prev) => ({
      ...(prev as Record<string, unknown>),
      cwd: worktreePath,
      _systemPromptCacheInvalidated: true,
      _memoryFileCacheInvalidated: true,
      _planDirCacheInvalidated: true,
    }));

    _activeWorktreeSession = {
      worktreePath,
      worktreeBranch: branchName,
      originalCwd,
    };

    return {
      data: {
        worktreePath,
        worktreeBranch: branchName,
        message: `Created worktree at \`${worktreePath}\` on branch \`${branchName}\`. The session is now working in the worktree. Use ExitWorktree to leave mid-session, or exit the session to be prompted.`,
      },
    };
  },

  description: () =>
    "Create and enter an isolated git worktree on a new branch. Switches the session's working directory into the worktree.",

  prompt: () =>
    `Use EnterWorktree only when the user explicitly requests a worktree ("create a worktree", "work in a worktree"). Do NOT use this for general branch operations. Supply a name for a new worktree, or a path to enter an existing one. After entry, the session's cwd is the worktree. Call ExitWorktree to leave.`,

  mapToolResultToToolResultBlockParam: (content, toolUseId) => ({
    type: "tool_result" as const,
    tool_use_id: toolUseId,
    content: JSON.stringify(content),
  }),
});

// ---------------------------------------------------------------------------
// ExitWorktree
// ---------------------------------------------------------------------------

const ExitWorktreeInputSchema = z
  .object({
    action: z.enum(["keep", "remove"]),
    discard_changes: z.boolean().optional(),
  })
  .strict();

type ExitWorktreeInput = z.infer<typeof ExitWorktreeInputSchema>;

export const ExitWorktreeTool = buildTool<ExitWorktreeInput, unknown>({
  name: "ExitWorktree",
  inputSchema: ExitWorktreeInputSchema,

  isDestructive: (rawInput?: ExitWorktreeInput) => rawInput?.action === "remove",

  call: async (rawArgs: unknown, context: ToolUseContext) => {
    const args = rawArgs as ExitWorktreeInput;

    if (!_activeWorktreeSession) {
      return {
        data: {
          action: args.action,
          noOp: true,
          message:
            "No active EnterWorktree session found. This tool only operates on worktrees created by EnterWorktree in this session.",
        },
      };
    }

    const session = _activeWorktreeSession;
    const { worktreePath, worktreeBranch, originalCwd } = session;

    if (args.action === "remove") {
      let uncommittedFiles = 0;
      let aheadCommits = 0;

      try {
        uncommittedFiles = await gitOps.countUncommittedFiles(worktreePath);
      } catch {
        throw new Error(
          "Cannot determine worktree status (git status failed). Refusing removal to prevent data loss. Set discard_changes: true if you are certain there is nothing to preserve.",
        );
      }

      if (worktreeBranch) {
        try {
          aheadCommits = await gitOps.countAheadCommits(worktreePath, "HEAD~0");
        } catch {
          aheadCommits = 0;
        }
      }

      if ((uncommittedFiles > 0 || aheadCommits > 0) && !args.discard_changes) {
        throw new Error(
          `Worktree has ${uncommittedFiles} uncommitted file(s) and ${aheadCommits} commit(s) not on the original branch. Set discard_changes: true to proceed with removal.`,
        );
      }

      try {
        const isInsideGit = await gitOps.isInsideGitRepo(originalCwd);
        if (isInsideGit) {
          const gitRoot = await gitOps.getGitRoot(originalCwd);
          await gitOps.removeWorktree({ gitRoot, path: worktreePath });
        }
        if (worktreeBranch) {
          await gitOps.deleteWorktreeAndBranch({ path: worktreePath, branch: worktreeBranch });
        }
      } catch {
        // best-effort cleanup; cwd restore is still performed
      }

      doChangeCwd(originalCwd);
      await context.setAppState((prev) => ({
        ...(prev as Record<string, unknown>),
        cwd: originalCwd,
        _systemPromptCacheInvalidated: true,
        _memoryFileCacheInvalidated: true,
        _planDirCacheInvalidated: true,
      }));
      _activeWorktreeSession = null;

      const discardNote =
        uncommittedFiles > 0 || aheadCommits > 0
          ? ` Discarded ${aheadCommits} commit(s) and ${uncommittedFiles} file(s).`
          : "";

      return {
        data: {
          action: "remove" as const,
          originalCwd,
          worktreePath,
          worktreeBranch: worktreeBranch ?? undefined,
          discardedFiles: uncommittedFiles || undefined,
          discardedCommits: aheadCommits || undefined,
          message: `Exited and removed worktree at \`${worktreePath}\`.${discardNote} Session is now back in \`${originalCwd}\`.`,
        },
      };
    }

    // action === "keep"
    doChangeCwd(originalCwd);
    await context.setAppState((prev) => ({
      ...(prev as Record<string, unknown>),
      cwd: originalCwd,
      _systemPromptCacheInvalidated: true,
      _memoryFileCacheInvalidated: true,
      _planDirCacheInvalidated: true,
    }));
    _activeWorktreeSession = null;

    const tmuxNote = session.tmuxSessionName
      ? ` Tmux session \`${session.tmuxSessionName}\` is still running — reattach to continue.`
      : "";

    return {
      data: {
        action: "keep" as const,
        originalCwd,
        worktreePath,
        worktreeBranch: worktreeBranch ?? undefined,
        tmuxSessionName: session.tmuxSessionName,
        message:
          `Exited worktree. Your work is preserved at \`${worktreePath}\`` +
          (worktreeBranch ? ` on branch \`${worktreeBranch}\`` : "") +
          `. Session is now back in \`${originalCwd}\`.${tmuxNote}`,
      },
    };
  },

  description: () =>
    "Exit the current worktree session created by EnterWorktree. Optionally remove the worktree and branch.",

  prompt: () =>
    `Use ExitWorktree to leave the current worktree. action:'keep' preserves the worktree on disk; action:'remove' deletes it. Set discard_changes:true to force-remove when there are uncommitted changes. This tool is a no-op if no EnterWorktree session is active.`,

  mapToolResultToToolResultBlockParam: (content, toolUseId) => ({
    type: "tool_result" as const,
    tool_use_id: toolUseId,
    content: JSON.stringify(content),
  }),
});
