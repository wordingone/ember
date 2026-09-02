// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// memory-ui.ts — memory file selector and update notification.

import React from "react";
import { Box, Text } from "./ink/components.ts";
import { join } from "path";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const FOLDER_QUICK_LINK_PREFIX = "__open_folder__";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type MemoryFileScope = "user" | "project" | "agent";

export interface MemoryFile {
  path:  string;
  scope: MemoryFileScope;
}

// ---------------------------------------------------------------------------
// AC1/AC2: getRelativeMemoryPath — picks shortest representation
// ---------------------------------------------------------------------------

/**
 * Compute POSIX-style relative path from `from` to `to` using forward-slash
 * semantics only, so the result is correct even when running on Windows where
 * `path.relative` would produce backslash-separated paths.
 */
function posixRelative(from: string, to: string): string {
  const normalize = (p: string): string[] =>
    p.replace(/\\/g, "/").split("/").filter(Boolean);
  const fromParts = normalize(from);
  const toParts   = normalize(to);
  let common = 0;
  while (
    common < fromParts.length &&
    common < toParts.length &&
    fromParts[common] === toParts[common]
  ) {
    common++;
  }
  const ups  = fromParts.length - common;
  const rest = toParts.slice(common);
  const rel  = [...Array(ups).fill(".."), ...rest];
  return rel.length === 0 ? "." : rel.join("/");
}

export function getRelativeMemoryPath(
  filePath: string,
  homeDir:  string,
  cwd:      string,
): string {
  // Build tilde-relative path
  const tildePath  = filePath.startsWith(homeDir + "/")
    ? "~" + filePath.slice(homeDir.length)
    : null;

  // Build dot-relative path (POSIX-aware so Windows backslashes don't sneak in)
  const relFromCwd = posixRelative(cwd, filePath);
  const dotPath    = relFromCwd.startsWith("../") ? null : "./" + relFromCwd;

  const candidates: string[] = [];
  if (tildePath) candidates.push(tildePath);
  if (dotPath)   candidates.push(dotPath);

  if (candidates.length === 0) return filePath;

  // Return shortest
  return candidates.reduce((best, c) =>
    c.length < best.length ? c : best,
  );
}

// ---------------------------------------------------------------------------
// AC3: Folder quick-link detection
// ---------------------------------------------------------------------------

export function isFolderQuickLink(item: string): boolean {
  return item.startsWith(FOLDER_QUICK_LINK_PREFIX);
}

export function folderQuickLinkPath(item: string): string {
  return item.slice(FOLDER_QUICK_LINK_PREFIX.length);
}

// ---------------------------------------------------------------------------
// AC6: formatMemoryNotification
// ---------------------------------------------------------------------------

export function formatMemoryNotification(path: string): string {
  return `Memory updated in ${path} · /memory to edit`;
}

// ---------------------------------------------------------------------------
// AC7: groupMemoryFilesByScope
// ---------------------------------------------------------------------------

export function groupMemoryFilesByScope(
  files: MemoryFile[],
): Map<MemoryFileScope, MemoryFile[]> {
  const groups = new Map<MemoryFileScope, MemoryFile[]>();
  for (const file of files) {
    const existing = groups.get(file.scope) ?? [];
    existing.push(file);
    groups.set(file.scope, existing);
  }
  return groups;
}

// ---------------------------------------------------------------------------
// React components (structural)
// ---------------------------------------------------------------------------

export interface MemoryFileSelectorProps {
  files?:             MemoryFile[];
  homeDir?:           string;
  cwd?:               string;
  autoDreamEnabled?:  boolean;
  lastDreamAt?:       string;
  lastSelectedPath?:  string;
  onSelect?:          (path: string) => void;
  onOpenFolder?:      (dir: string) => void;
  onDismiss?:         () => void;
}

export function MemoryFileSelector(
  props: MemoryFileSelectorProps,
): React.ReactElement {
  const { files = [] } = props;
  return React.createElement(
    Box, { flexDirection: "column", borderStyle: "single", padding: 1 },
    React.createElement(Text, { bold: true }, "Memory files"),
    ...files.map((f) =>
      React.createElement(Text, { key: f.path }, `[${f.scope}] ${f.path}`),
    ),
    props.autoDreamEnabled && props.lastDreamAt
      ? React.createElement(
          Text, { key: "dream", dimColor: true },
          `Last dream: ${props.lastDreamAt}`,
        )
      : null,
  );
}

export interface MemoryUpdateNotificationProps {
  path:      string;
  onDismiss?: () => void;
}

export function MemoryUpdateNotification(
  props: MemoryUpdateNotificationProps,
): React.ReactElement {
  return React.createElement(
    Box, { flexDirection: "row" },
    React.createElement(Text, null, formatMemoryNotification(props.path)),
  );
}
