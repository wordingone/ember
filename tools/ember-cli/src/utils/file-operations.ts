// File I/O and path utilities for Ember CLI.
// L1 leaf: no intra-ember dependencies.

import {
  readFile,
  writeFile,
  appendFile,
  rm,
  mkdir,
  readdir,
  stat,
} from "fs/promises";
import { dirname, join } from "path";

// ---------------------------------------------------------------------------
// File reading
// ---------------------------------------------------------------------------

/**
 * Strips a leading UTF-8 BOM (U+FEFF) if present. Windows PowerShell 5.1's
 * `-Encoding utf8` (used throughout this repo's .ps1 scripts, e.g. the liveness-watchdog's
 * planned-outage.json contract, issue #464/#475) writes a byte-order-mark by default;
 * Node's `fs.readFile(path, "utf-8")` does NOT strip it, so a PS-written JSON state file
 * fails `JSON.parse` with a leading-character syntax error even though the content is
 * otherwise valid. Pure, idempotent (no-op on a file with no BOM), never throws.
 */
export function stripBom(text: string): string {
  return text.charCodeAt(0) === 0xfeff ? text.slice(1) : text;
}

/**
 * Reads a file as a UTF-8 string.
 * Returns null if the file does not exist.
 */
export async function readFileAsString(filePath: string): Promise<string | null> {
  try {
    return await readFile(filePath, "utf-8");
  } catch (err) {
    const code = (err as NodeJS.ErrnoException)?.code;
    if (code === "ENOENT") return null;
    throw err;
  }
}

/**
 * Reads a file as JSON.
 * Returns null if the file does not exist.
 * Throws if the file exists but is not valid JSON.
 */
export async function readFileAsJSON<T = unknown>(filePath: string): Promise<T | null> {
  const content = await readFileAsString(filePath);
  if (content === null) return null;
  return JSON.parse(content);
}

// ---------------------------------------------------------------------------
// File writing (with parent directory creation)
// ---------------------------------------------------------------------------

/**
 * Writes a string to a file, creating parent directories if needed.
 */
export async function writeFileWithDirs(
  filePath: string,
  content: string,
  encoding: BufferEncoding = "utf-8",
): Promise<void> {
  const dir = dirname(filePath);
  if (dir !== ".") {
    await mkdir(dir, { recursive: true });
  }
  await writeFile(filePath, content, encoding);
}

/**
 * Writes JSON to a file, creating parent directories if needed.
 */
export async function writeJSONWithDirs(
  filePath: string,
  data: unknown,
  indent: number | null = 2,
): Promise<void> {
  const content = JSON.stringify(data, null, indent ?? undefined);
  await writeFileWithDirs(filePath, content, "utf-8");
}

/**
 * Appends a line to a file (with newline), creating parent directories and the file if needed.
 */
export async function appendLineWithDirs(filePath: string, line: string): Promise<void> {
  const dir = dirname(filePath);
  if (dir !== ".") {
    await mkdir(dir, { recursive: true });
  }
  await appendFile(filePath, line + "\n", "utf-8");
}

// ---------------------------------------------------------------------------
// Directory operations
// ---------------------------------------------------------------------------

/**
 * Ensures a directory exists, creating it if needed.
 */
export async function ensureDir(dirPath: string): Promise<void> {
  await mkdir(dirPath, { recursive: true });
}

/**
 * Lists entries in a directory.
 * Returns an empty array if the directory does not exist.
 */
export async function listDir(dirPath: string): Promise<string[]> {
  try {
    return await readdir(dirPath);
  } catch (err) {
    const code = (err as NodeJS.ErrnoException)?.code;
    if (code === "ENOENT") return [];
    throw err;
  }
}

// ---------------------------------------------------------------------------
// File/directory metadata
// ---------------------------------------------------------------------------

/**
 * Checks whether a file or directory exists.
 */
export async function pathExists(filePath: string): Promise<boolean> {
  try {
    await stat(filePath);
    return true;
  } catch (err) {
    const code = (err as NodeJS.ErrnoException)?.code;
    if (code === "ENOENT") return false;
    throw err;
  }
}

/**
 * Checks whether a path is a directory.
 */
export async function isDirectory(filePath: string): Promise<boolean> {
  try {
    const s = await stat(filePath);
    return s.isDirectory();
  } catch {
    return false;
  }
}

/**
 * Checks whether a path is a file.
 */
export async function isFile(filePath: string): Promise<boolean> {
  try {
    const s = await stat(filePath);
    return s.isFile();
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Deletion
// ---------------------------------------------------------------------------

/**
 * Deletes a file or directory recursively.
 * Does not throw if the path does not exist.
 */
export async function deletePathRecursive(filePath: string): Promise<void> {
  try {
    await rm(filePath, { recursive: true, force: true });
  } catch (err) {
    const code = (err as NodeJS.ErrnoException)?.code;
    if (code !== "ENOENT") throw err;
  }
}
