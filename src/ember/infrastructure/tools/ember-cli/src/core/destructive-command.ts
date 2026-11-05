// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// Commands that delete or rewrite data in bulk. Blind test S31: after "a" (always allow Bash), an
// `rd /s /q` ran with no prompt; S38: headless -p ran it with no approval at all. A command matched
// here always asks: "always allow" does not cover it, and with nobody to ask it is refused.

const DESTRUCTIVE: RegExp[] = [
  /(^|[\s;&|(])rm\s+(-[a-z]*[rf][a-z]*\s+|--recursive|--force)/i, // rm -rf, rm -r, rm -f
  /(^|[\s;&|(])(rd|rmdir)\s+\/s\b/i,                              // rd /s
  /(^|[\s;&|(])del\s+.*\/[sq]\b/i,                                // del /s, del /q
  /(^|[\s;&|(])erase\s+.*\/[sq]\b/i,
  /\bRemove-Item\b[^|;]*-Recurse/i,
  /\b(ri|rm|del|rmdir)\b[^|;]*-Recurse/i,                         // PowerShell aliases
  /\bgit\s+reset\s+--hard\b/i,
  /\bgit\s+clean\s+-[a-z]*f/i,
  /\bgit\s+push\b[^|;]*(--force\b|-f\b)/i,
  /\bgit\s+checkout\s+--\s/i,
  /(^|[\s;&|(])format\s+[a-z]:/i,
  /\bmkfs(\.\w+)?\b/i,
  /\bdd\s+[^|;]*\bof=/i,
  /\b(Format-Volume|Clear-Disk|Remove-Partition)\b/i,
  /\b(shutdown|Stop-Computer|Restart-Computer)\b/i,
];

export function isDestructiveCommand(command: string): boolean {
  return DESTRUCTIVE.some((re) => re.test(command));
}

export const DESTRUCTIVE_ASK_MESSAGE =
  "This command deletes or rewrites data in bulk, so it needs explicit approval every time.";

// Any command that deletes files, the single-file `rm notes.txt` included. isDestructiveCommand
// leaves that alone on purpose (an interactive session approves it like any other command); a
// headless run with nobody to ask refuses it unless --dangerously-skip-permissions is given
// (blind test W28: a headless run executed `rm -f` with no approval).
const DELETION: RegExp[] = [
  /(?:^|[;&|(\n]\s*|\bthen\s+|\bdo\s+|\/c\s+["']?|\s-c(?:ommand)?\s+["']?|\bxargs\s+(?:-\S+\s+)*)(?:sudo\s+)?(?:command\s+)?(?:rm|del|erase|rd|rmdir|unlink|shred|remove-item|ri)(?=\s|$)/i,
  /\bfind\b[^|;]*\s-delete\b/i,
];

export function isDeletionCommand(command: string): boolean {
  return DELETION.some((re) => re.test(command));
}
