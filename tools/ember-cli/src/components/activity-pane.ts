// components/activity-pane.ts — Activity stream render (live organism observation)

import { promises as fs } from "fs";
import * as path from "path";
import type { INullAdapter } from "ink";

export interface ActivityEvent {
  ts: string; // ISO8601Z
  actor: string;
  kind: "tool_use" | "reasoning" | "output" | "status" | "error";
  title: string;
  body?: string;
  run_id?: string;
}

/**
 * Load today's activity log (JSONL format).
 * Returns events in chronological order, or empty array if no file.
 */
export async function loadActivityLog(repoRoot: string): Promise<ActivityEvent[]> {
  const now = new Date();
  const dateStr = now.toISOString().slice(0, 10).replace(/-/g, "");
  const logPath = path.join(repoRoot, "state/activity", `activity-${dateStr}.jsonl`);

  try {
    const content = await fs.readFile(logPath, "utf-8");
    const events: ActivityEvent[] = [];
    for (const line of content.trim().split("\n")) {
      if (line) {
        events.push(JSON.parse(line));
      }
    }
    return events;
  } catch {
    // File doesn't exist yet or can't be read
    return [];
  }
}

/**
 * Format activity events for terminal display.
 *   - Empty state: "organism quiet — no live activity"
 *   - Each event: relative-time + kind glyph + actor + title (truncated to cols)
 *   - Relative time: "now" | "Nm ago" | "Nh ago"
 */
export function formatActivityPane(events: ActivityEvent[], cols: number = 80): string {
  if (events.length === 0) {
    return "organism quiet — no live activity";
  }

  const now = new Date();
  const lines: string[] = [];

  for (const event of events) {
    const ts = new Date(event.ts);
    const deltaMs = now.getTime() - ts.getTime();
    const deltaSec = deltaMs / 1000;

    let relTime: string;
    if (deltaSec < 60) {
      relTime = "now";
    } else if (deltaSec < 3600) {
      relTime = `${Math.floor(deltaSec / 60)}m ago`;
    } else {
      relTime = `${Math.floor(deltaSec / 3600)}h ago`;
    }

    const kindGlyph: Record<string, string> = {
      tool_use: "🔧",
      reasoning: "🧠",
      output: "📤",
      status: "⚙",
      error: "⚠️",
    };
    const glyph = kindGlyph[event.kind] || "?";

    const prefix = `${relTime} ${glyph} ${event.actor}: `;
    const maxTitleWidth = cols - prefix.length;

    let title = event.title;
    if (title.length > maxTitleWidth && maxTitleWidth > 3) {
      title = title.slice(0, maxTitleWidth - 3) + "...";
    }

    lines.push(prefix + title);
  }

  return lines.join("\n");
}

/**
 * Watch activity log file and call callback on changes.
 * Falls back to polling every 2s if fs.watch is unavailable.
 */
export async function watchActivityLog(
  repoRoot: string,
  onChange: (events: ActivityEvent[]) => void
): Promise<() => void> {
  const now = new Date();
  const dateStr = now.toISOString().slice(0, 10).replace(/-/g, "");
  const logPath = path.join(repoRoot, "state/activity", `activity-${dateStr}.jsonl`);

  let lastContent = "";

  const checkFile = async () => {
    try {
      const content = await fs.readFile(logPath, "utf-8");
      if (content !== lastContent) {
        lastContent = content;
        const events: ActivityEvent[] = [];
        for (const line of content.trim().split("\n")) {
          if (line) {
            events.push(JSON.parse(line));
          }
        }
        onChange(events);
      }
    } catch {
      // File doesn't exist yet
    }
  };

  // Try fs.watch first
  let watcher: ReturnType<typeof fs.watch> | null = null;
  try {
    const dir = path.dirname(logPath);
    watcher = fs.watch(dir, async () => {
      await checkFile();
    });
  } catch {
    // fs.watch not available or failed, fall back to polling
  }

  // Also set up polling fallback (2s interval)
  const pollInterval = setInterval(async () => {
    await checkFile();
  }, 2000);

  // Initial check
  await checkFile();

  return () => {
    clearInterval(pollInterval);
    if (watcher) {
      watcher.close().catch(() => {});
    }
  };
}
