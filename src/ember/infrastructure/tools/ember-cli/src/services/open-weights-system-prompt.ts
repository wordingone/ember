// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// services/open-weights-system-prompt.ts -- the base system prompt for OPEN_WEIGHTS seats.
//
// The interactive REPL's base prompt is empty (the Ember reference seat is trained
// without one). A general open-weights model otherwise starts each session not
// knowing where it is: which directory its file tools resolve against, which OS and
// shell its Bash tool runs, or today's date. Keep this short; every token is prefilled
// on every turn.

export interface OpenWeightsPromptFacts {
  cwd: string;
  platform: NodeJS.Platform;
  date: Date;
}

export function buildOpenWeightsSystemPrompt(f: OpenWeightsPromptFacts): string {
  const shell = f.platform === "win32"
    ? "Windows. The Bash tool runs commands through cmd.exe (use cmd syntax, or the PowerShell tool for PowerShell)."
    : `${f.platform}.`;
  return [
    "You are ember, an agent working in the operator's terminal. Use the provided tools to read, search, edit and run things instead of guessing, and keep replies short.",
    `Working directory: ${f.cwd}. Relative paths resolve against it.`,
    `Operating system: ${shell}`,
    `Today's date: ${f.date.toISOString().slice(0, 10)}.`,
    "If a tool call fails, read the error and change the call; do not repeat an identical failing call. If a tool call is declined, ask the operator how to proceed.",
  ].join("\n");
}
