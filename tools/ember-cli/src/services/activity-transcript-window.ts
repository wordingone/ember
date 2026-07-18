// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/activity-transcript-window.ts — bounded REPL projection of the durable activity ledger.

export const ACTIVITY_TRANSCRIPT_CAP = 200;

export interface TranscriptMessage {
  id: string;
  type: string;
  [key: string]: unknown;
}

export interface SequencedActivityLine {
  sequence: number;
  ts: string;
  source: string;
  text: string;
  path?: string;
}

export interface ActivityTranscriptAdvance {
  messages: TranscriptMessage[];
  cursor: number;
}

function compactedCount(message: TranscriptMessage): number {
  return message.type === "activity_compacted" && typeof message.droppedCount === "number"
    ? message.droppedCount
    : 0;
}

function activityMessage(line: SequencedActivityLine): TranscriptMessage {
  return {
    id: `activity-${line.sequence}`,
    type: "activity",
    ts: line.ts,
    source: line.source,
    text: line.text,
    path: line.path,
  };
}

/** Projects newly observed feed lines into the bounded REPL activity window. */
export function advanceActivityTranscript(
  messages: TranscriptMessage[],
  cursor: number,
  feed: SequencedActivityLine[],
): ActivityTranscriptAdvance {
  const fresh = feed
    .filter((line) => line.sequence > cursor)
    .sort((left, right) => left.sequence - right.sequence);
  if (fresh.length === 0) return { messages, cursor };

  const nextCursor = fresh[fresh.length - 1]!.sequence;
  const combined = [...messages, ...fresh.map(activityMessage)];
  const activityIndexes = combined
    .map((message, index) => (message.type === "activity" ? index : -1))
    .filter((index) => index >= 0);
  const overflow = Math.max(0, activityIndexes.length - ACTIVITY_TRANSCRIPT_CAP);
  const sequenceGap = Math.max(0, fresh[0]!.sequence - cursor - 1);
  if (overflow === 0 && sequenceGap === 0) return { messages: combined, cursor: nextCursor };

  const oldCursorIndex = combined.findIndex((message) => message.type === "activity_compacted");
  const removedActivityIndexes = new Set(activityIndexes.slice(0, overflow));
  const insertAt = Math.min(
    oldCursorIndex >= 0 ? oldCursorIndex : Number.POSITIVE_INFINITY,
    activityIndexes[0]!,
  );
  const droppedCount =
    combined.reduce((count, message) => count + compactedCount(message), 0) + sequenceGap + overflow;
  const nextMessages: TranscriptMessage[] = [];

  for (let index = 0; index < combined.length; index += 1) {
    if (index === insertAt) {
      nextMessages.push({
        id: "activity-compacted-history",
        type: "activity_compacted",
        droppedCount,
        content: `${droppedCount} earlier activity events are durable in activity-ledger.jsonl`,
      });
    }
    if (index === oldCursorIndex || removedActivityIndexes.has(index)) continue;
    nextMessages.push(combined[index]!);
  }

  return { messages: nextMessages, cursor: nextCursor };
}
