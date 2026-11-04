// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// tools/shell-state-note.ts -- tell the model, at the moment it matters, that shell state does not persist.
//
// Blind test S12: every Bash / PowerShell call starts a fresh shell in the project directory, so a
// `cd` or a variable set in one call is gone in the next. The tool prompt says so, but a model
// that ran `cd sub` and got "Command succeeded" back believes it is in `sub`. Design choice: keep
// the tools stateless (a persistent cwd would change what every relative path in Read, Write and
// Edit means, and a persistent shell cannot be killed cleanly per call) and say so in the result
// of exactly the calls whose only effect was lost state. A command that uses its own cd or
// variable in the same call (`cd sub && make`, `X=1; echo $X`) is working as intended and gets no note.

const BASH_STATE_SEGMENT = [
  /^(cd|pushd|popd)(\s|$)/i,
  /^export\s+[A-Za-z_]\w*(=|\s|$)/i,
  /^unset\s/i,
  /^[A-Za-z_]\w*=\S*$/,
];
// cmd.exe: `set X=1`, `cd /d dir`, `chdir`, `pushd`.
const CMD_STATE_SEGMENT = [
  /^(cd|chdir|pushd|popd)(\s|$)/i,
  /^set\s+[^\s=]+=/i,
  /^[A-Za-z]:$/,
];
const POWERSHELL_STATE_SEGMENT = [
  /^(cd|sl|chdir|set-location|pushd|push-location|popd|pop-location)(\s|$)/i,
  /^\$[A-Za-z_][\w:]*\s*=/,
  /^set-variable\s/i,
  /^\[environment\]::setenvironmentvariable\(/i,
];

export type ShellFlavour = "bash" | "cmd" | "powershell";

function segmentsOf(command: string, flavour: ShellFlavour): string[] {
  const splitter = flavour === "powershell" ? /[\r\n;]+/ : /[\r\n;]+|&&|\|\|/;
  return command.split(splitter).map((s) => s.trim()).filter((s) => s !== "" && !s.startsWith("#"));
}

/** True when every statement of `command` only changes shell state (directory or variables). */
export function onlyChangesShellState(command: string, flavour: ShellFlavour): boolean {
  const segments = segmentsOf(command, flavour);
  if (segments.length === 0) return false;
  const patterns = flavour === "bash" ? BASH_STATE_SEGMENT : flavour === "cmd" ? CMD_STATE_SEGMENT : POWERSHELL_STATE_SEGMENT;
  return segments.every((segment) => patterns.some((re) => re.test(segment)));
}

/**
 * The sentence to append to the result of a call that only changed shell state, or null.
 * `projectDir` is where the next call starts.
 */
export function shellStateNote(command: string, flavour: ShellFlavour, projectDir: string): string | null {
  if (!onlyChangesShellState(command, flavour)) return null;
  const chain = flavour === "powershell" ? "; " : " && ";
  return `note: cd and variables set here do NOT carry over; the next call starts again in ${projectDir}. ` +
    `Put dependent steps in one call, for example: cd sub${chain}make`;
}
