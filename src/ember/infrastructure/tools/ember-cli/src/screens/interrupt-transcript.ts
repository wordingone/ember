// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Transcript update for an interrupted turn (blind test T12). The turn's first assistant message sits
// ABOVE every tool call and result the turn produced, so marking that message put "Interrupted by user."
// above the subagent's last result and the "● Agent(...)" line. The notice now goes at the END of the
// transcript, and tool calls that never got a result are marked interrupted.

type Msg = Record<string, unknown> & { id: string };

export function applyInterrupt<T extends Msg>(prev: T[], assistantId: string): T[] {
  const marked = prev.map((m) =>
    m["type"] === "tool_call" && m["status"] === "running" ? ({ ...m, status: "interrupted" } as T) : m,
  );
  const last = marked[marked.length - 1];
  // The turn ends in assistant text (its own, or text streamed after the last tool): annotate that text in place, as before.
  if (last && (last.id === assistantId || last["type"] === "assistant")) {
    const partial = String(last["content"] ?? "");
    return [...marked.slice(0, -1), { ...last, content: partial.trim() ? `${partial}\n\n(interrupted)` : "__user_abort__" } as T];
  }
  return [...marked, { id: crypto.randomUUID(), type: "assistant", content: "__user_abort__" } as unknown as T];
}
