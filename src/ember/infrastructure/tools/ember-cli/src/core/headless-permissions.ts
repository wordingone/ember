// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// core/headless-permissions.ts — what `ember -p "<task>"` may do without anyone to ask.
//
// Interactive sessions ask before a call a tool flags ("ask") and before every non-read-only call
// in the default mode. A headless run has nobody to ask. It used to approve everything, so a -p run
// executed `rm -f`, a curl to 127.0.0.1 and a write outside the working directory without a word
// (blind tests S38, W28). Now, by default:
//
//   allowed   exactly what the interactive default mode runs without asking: calls a tool allows
//             AND reports read-only (reads, searches, web fetches, read-only shell commands)
//   refused   everything else: any write or edit, any shell command that is not read-only (curl, a
//             file download, rm -rf, git reset --hard ...), a write outside the working directory, a
//             shell command that connects to a loopback/private address, and so on
//             (blind test W31: with the old "inside the working directory is fine" rule a -p run
//             wrote a file and ran a curl download without a word.)
//
// A refusal reaches the model as an error that names the reason and the flag, so it tells the
// operator instead of retrying. `--dangerously-skip-permissions` restores the old behaviour:
// everything a tool does not deny outright is allowed.

import type { CanUseToolFn, ToolRefusal } from "./query-engine.ts";
import { isDeletionCommand } from "./destructive-command.ts";

export const BYPASS_PERMISSIONS_FLAG = "--dangerously-skip-permissions";

const SHELL_TOOLS = new Set(["Bash", "PowerShell"]);

/** Why a headless run without the bypass flag may not make this call, or null when it may. */
export function headlessRefusalReason(
  toolName: string,
  input: unknown,
  behavior: "allow" | "deny" | "ask",
  message?: string,
  readOnly = false,
): string | null {
  if (behavior === "ask") return message ?? `${toolName} asked for approval`;
  if (SHELL_TOOLS.has(toolName)) {
    const command = (input as { command?: unknown } | null)?.command;
    if (typeof command === "string" && isDeletionCommand(command)) {
      return "the command deletes files (rm, del, rd, rmdir, Remove-Item or find -delete)";
    }
  }
  // The interactive default mode asks before every call that is not read-only (authorizeReplTool).
  if (!readOnly) return `${toolName} is not read-only, so the interactive default mode would ask for approval`;
  return null;
}

export function headlessRefusalText(reason: string): string {
  return `${reason}. This is a headless run (-p), so there is nobody to ask, and it is refused. To allow it, run again with ${BYPASS_PERMISSIONS_FLAG}.`;
}

/** The canUseTool for a headless run that was not given the bypass flag. */
export const headlessCanUseTool: CanUseToolFn = async (tool, input, behavior, message): Promise<boolean | ToolRefusal> => {
  let readOnly = false;
  try { readOnly = typeof tool.isReadOnly === "function" && tool.isReadOnly(input) === true; } catch { readOnly = false; }
  const reason = headlessRefusalReason(tool.name, input, behavior, message, readOnly);
  if (reason === null) return true;
  const text = headlessRefusalText(reason);
  process.stderr.write(`[ember] ${tool.name} refused: ${text}\n`);
  return { allowed: false, reason: text };
};
