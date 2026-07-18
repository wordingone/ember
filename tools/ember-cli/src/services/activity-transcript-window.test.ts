import { describe, expect, it } from "bun:test";

import {
  ACTIVITY_TRANSCRIPT_CAP,
  advanceActivityTranscript,
} from "./activity-transcript-window.ts";

type FeedLine = {
  sequence: number;
  ts: string;
  source: "receipt";
  text: string;
};

function line(sequence: number): FeedLine {
  return {
    sequence,
    ts: `2026-07-18T00:00:${String(sequence).padStart(2, "0")}Z`,
    source: "receipt",
    text: `event-${sequence}`,
  };
}

describe("activity transcript retention window", () => {
  it("bounds identical and new feed replay while retaining the newest ordered window and a durable-history cursor", () => {
    const initial = [{ id: "user-1", type: "user", content: "keep me" }];
    const firstFeed = Array.from({ length: ACTIVITY_TRANSCRIPT_CAP + 25 }, (_, index) => line(index + 1));

    const first = advanceActivityTranscript(initial, 0, firstFeed);
    const activities = first.messages.filter((message) => message.type === "activity");
    const cursor = first.messages.find((message) => message.type === "activity_compacted");

    expect(first.cursor).toBe(ACTIVITY_TRANSCRIPT_CAP + 25);
    expect(first.messages.find((message) => message.id === "user-1")).toEqual(initial[0]);
    expect(activities).toHaveLength(ACTIVITY_TRANSCRIPT_CAP);
    expect(first.messages.length).toBeLessThanOrEqual(ACTIVITY_TRANSCRIPT_CAP + 2);
    expect(activities.map((message) => message.text)).toEqual(
      firstFeed.slice(-ACTIVITY_TRANSCRIPT_CAP).map((event) => event.text),
    );
    expect(cursor?.droppedCount).toBe(25);

    const replay = advanceActivityTranscript(first.messages, first.cursor, firstFeed);
    expect(replay).toEqual(first);

    const secondFeed = Array.from({ length: ACTIVITY_TRANSCRIPT_CAP }, (_, index) => line(index + 226));
    const second = advanceActivityTranscript(replay.messages, replay.cursor, secondFeed);
    const secondActivities = second.messages.filter((message) => message.type === "activity");

    expect(secondActivities).toHaveLength(ACTIVITY_TRANSCRIPT_CAP);
    expect(second.messages.length).toBeLessThanOrEqual(ACTIVITY_TRANSCRIPT_CAP + 2);
    expect(secondActivities.map((message) => message.text)).toEqual(secondFeed.map((event) => event.text));
    expect(second.messages.find((message) => message.type === "activity_compacted")?.droppedCount).toBe(225);
  });
});

  it("converges to the preregistered 201-message state ceiling over 50,000 new events and a repeated snapshot", () => {
    let state = advanceActivityTranscript([], 0, []);
    let maxMessages = 0;
    let lastFeed: FeedLine[] = [];

    for (let batch = 0; batch < 250; batch += 1) {
      const start = batch * ACTIVITY_TRANSCRIPT_CAP + 1;
      lastFeed = Array.from({ length: ACTIVITY_TRANSCRIPT_CAP }, (_, index) => line(start + index));
      state = advanceActivityTranscript(state.messages, state.cursor, lastFeed);
      maxMessages = Math.max(maxMessages, state.messages.length);
    }

    expect(state.cursor).toBe(50_000);
    expect(maxMessages).toBeLessThanOrEqual(ACTIVITY_TRANSCRIPT_CAP + 1);
    expect(state.messages.filter((message) => message.type === "activity")).toHaveLength(ACTIVITY_TRANSCRIPT_CAP);
    expect(advanceActivityTranscript(state.messages, state.cursor, lastFeed)).toEqual(state);
  });
