#!/usr/bin/env bash
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
# One cross-platform Python process boundary for Git hooks and repo-guard.

set -u

if [ "${OS:-}" = "Windows_NT" ]; then
  # Windows PowerShell's -File boundary can reject worktree scripts when the
  # host enforces ConstrainedLanguage. Keep the trusted code inline, use only
  # native invocation, and single-quote every Python argument for PowerShell.
  export EMBER_HIDDEN_PY_ARGC="$#"
  argument_index=0
  for argument in "$@"; do
    printf -v argument_name 'EMBER_HIDDEN_PY_ARG_%d' "$argument_index"
    export "$argument_name=$argument"
    argument_index=$((argument_index + 1))
  done
  python_bootstrap='import os, runpy, sys
args = [os.environ[f"EMBER_HIDDEN_PY_ARG_{index}"] for index in range(int(os.environ["EMBER_HIDDEN_PY_ARGC"]))]
if not args:
    raise SystemExit("run-python-hidden: missing Python entrypoint")
entry = args[0]
if entry == "-c":
    sys.argv = ["-c", *args[2:]]
    exec(compile(args[1], "<string>", "exec"), {"__name__": "__main__"})
elif entry == "-m":
    sys.argv = [args[1], *args[2:]]
    runpy.run_module(args[1], run_name="__main__", alter_sys=True)
elif entry == "-":
    sys.argv = ["-", *args[1:]]
    exec(compile(sys.stdin.read(), "<stdin>", "exec"), {"__name__": "__main__"})
else:
    sys.argv = args
    sys.path[0] = os.path.dirname(os.path.abspath(entry))
    runpy.run_path(entry, run_name="__main__")'
  bootstrap_base64="$(printf '%s' "$python_bootstrap" | base64 -w 0)" || exit 2
  command='$python = if ($env:EMBER_PYTHON_BIN) { $env:EMBER_PYTHON_BIN } else { (Get-Command python.exe -ErrorAction Stop).Source }; & $python'
  command+=" '-c' 'import sys,base64;exec(base64.b64decode(sys.argv[1]))' '$bootstrap_base64'; exit \$LASTEXITCODE"
  encoded_command="$(printf '%s' "$command" | iconv -f UTF-8 -t UTF-16LE | base64 -w 0)" || exit 2
  exec powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden \
    -EncodedCommand "$encoded_command"
fi

exec python "$@"
