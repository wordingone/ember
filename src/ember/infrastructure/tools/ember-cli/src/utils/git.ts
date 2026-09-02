// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Git utilities for repository operations.
// L1 leaf: no intra-ember dependencies.

import { spawn } from "child_process";
import { dirname } from "path";
import { cwd } from "process";

// ---------------------------------------------------------------------------
// Git command execution
// ---------------------------------------------------------------------------

/**
 * Executes a git command and returns stdout as a trimmed string.
 * Rejects if git command fails or is not available.
 */
export async function executeGitCommand(args: string[], cwd?: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const proc = spawn("git", args, {
      cwd: cwd,
      stdio: ["ignore", "pipe", "pipe"],
    });

    let stdout = "";
    let stderr = "";

    proc.stdout?.on("data", (data: Buffer) => {
      stdout += data.toString("utf-8");
    });

    proc.stderr?.on("data", (data: Buffer) => {
      stderr += data.toString("utf-8");
    });

    proc.on("error", (err) => {
      reject(new Error(`Git command failed: ${err.message}`));
    });

    proc.on("close", (code) => {
      if (code !== 0) {
        reject(new Error(`Git command failed with code ${code}: ${stderr.trim()}`));
      } else {
        resolve(stdout.trim());
      }
    });
  });
}

// ---------------------------------------------------------------------------
// Repository detection and info
// ---------------------------------------------------------------------------

/**
 * Finds the git repository root by walking up from the given directory.
 * Returns null if not in a git repository.
 */
export async function getGitRepositoryRoot(fromDir?: string): Promise<string | null> {
  try {
    const root = await executeGitCommand(["rev-parse", "--show-toplevel"], fromDir);
    return root || null;
  } catch {
    return null;
  }
}

/**
 * Checks whether the given directory (or cwd) is within a git repository.
 */
export async function isInGitRepository(dir?: string): Promise<boolean> {
  const root = await getGitRepositoryRoot(dir);
  return root !== null;
}

/**
 * Gets the current HEAD commit hash (SHA-1).
 */
export async function getCurrentCommitHash(repoRoot?: string): Promise<string | null> {
  try {
    return await executeGitCommand(["rev-parse", "HEAD"], repoRoot);
  } catch {
    return null;
  }
}

/**
 * Gets the current branch name.
 */
export async function getCurrentBranch(repoRoot?: string): Promise<string | null> {
  try {
    return await executeGitCommand(["rev-parse", "--abbrev-ref", "HEAD"], repoRoot);
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Repository status
// ---------------------------------------------------------------------------

/**
 * Checks whether the working tree has uncommitted changes.
 */
export async function hasUncommittedChanges(repoRoot?: string): Promise<boolean> {
  try {
    const output = await executeGitCommand(["status", "--porcelain"], repoRoot);
    return output.length > 0;
  } catch {
    return false;
  }
}

/**
 * Gets the git status output (--porcelain format).
 */
export async function getGitStatus(repoRoot?: string): Promise<string | null> {
  try {
    return await executeGitCommand(["status", "--porcelain"], repoRoot);
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Branch and commit operations
// ---------------------------------------------------------------------------

/**
 * Lists all local branches.
 */
export async function listLocalBranches(repoRoot?: string): Promise<string[]> {
  try {
    const output = await executeGitCommand(["branch", "--list"], repoRoot);
    return output.split("\n").map((line) => line.replace(/^\*\s+/, "").trim()).filter(Boolean);
  } catch {
    return [];
  }
}

/**
 * Gets the remote URL for the given remote name (default: origin).
 */
export async function getRemoteUrl(
  remoteName: string = "origin",
  repoRoot?: string,
): Promise<string | null> {
  try {
    return await executeGitCommand(["config", "--get", `remote.${remoteName}.url`], repoRoot);
  } catch {
    return null;
  }
}

/**
 * Gets the commit message for a specific commit (default: HEAD).
 */
export async function getCommitMessage(ref: string = "HEAD", repoRoot?: string): Promise<string | null> {
  try {
    return await executeGitCommand(["log", "-1", "--pretty=%B", ref], repoRoot);
  } catch {
    return null;
  }
}

/**
 * Checks whether a specific ref exists.
 */
export async function refExists(ref: string, repoRoot?: string): Promise<boolean> {
  try {
    await executeGitCommand(["cat-file", "-e", ref], repoRoot);
    return true;
  } catch {
    return false;
  }
}
