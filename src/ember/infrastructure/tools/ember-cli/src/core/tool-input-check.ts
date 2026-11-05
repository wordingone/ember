// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// tool-input-check — reject a malformed tool call with a message the model can act on, before
// the tool runs. Blind test FO-38: a Write call cut off by the output token limit arrived as {},
// the tool crashed with "undefined is not an object (evaluating 'p.startsWith')", and the model
// retried the same oversized call for 30 minutes.

/** Set by the response parser on a tool call whose arguments were not valid JSON. */
export const BAD_TOOL_ARGUMENTS_KEY = "__ember_bad_tool_arguments";

interface SchemaLike {
  safeParse?: (v: unknown) => { success: boolean; error?: { issues?: Array<{ path: PropertyKey[]; message: string }> } };
}

/** An error text for the model, or null when the input is usable. */
export function badToolArgumentsMessage(
  tool: { name: string; inputSchema?: unknown },
  input: unknown,
): string | null {
  if (input && typeof input === "object" && BAD_TOOL_ARGUMENTS_KEY in (input as object)) {
    const info = (input as Record<string, { receivedChars?: number }>)[BAD_TOOL_ARGUMENTS_KEY];
    return (
      `The ${tool.name} call's arguments were not valid JSON (${info?.receivedChars ?? 0} characters received). ` +
      `The reply was most likely cut off by the output length limit. Do not repeat the same call: ` +
      `split the work into smaller calls (for a large file, Write the first part, then add the rest with Edit or more writes).`
    );
  }
  const schema = tool.inputSchema as SchemaLike | undefined;
  if (!schema || typeof schema.safeParse !== "function") return null;
  const parsed = schema.safeParse(input ?? {});
  if (parsed.success) return null;
  // Only MISSING fields are rejected here; a present-but-loose value (a number sent as a string)
  // stays the tool's own business, as before this check existed.
  const valueAt = (path: PropertyKey[]): unknown =>
    path.reduce<unknown>((v, k) => (v && typeof v === "object" ? (v as Record<PropertyKey, unknown>)[k] : undefined), input);
  const missing = (parsed.error?.issues ?? []).filter((i) => i.path.length > 0 && valueAt(i.path) === undefined);
  if (missing.length === 0) return null;
  const issues = missing
    .slice(0, 5)
    .map((i) => `${i.path.length ? i.path.map(String).join(".") : "(input)"}: ${i.message}`)
    .join("; ");
  const empty = !input || (typeof input === "object" && Object.keys(input as object).length === 0);
  return (
    `Invalid ${tool.name} call: ${issues || "input does not match the tool's parameters"}.` +
    (empty ? " The call had no arguments at all; if it was large, it was probably cut off, so split it into smaller calls." : "")
  );
}
