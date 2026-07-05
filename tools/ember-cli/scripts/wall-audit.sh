#!/usr/bin/env bash
# wall-audit.sh — clean-room wall enforcement for ember-cli implementers.
#
# A WALLED implementer must NEVER read avir-cli source. This script greps an agent's
# transcript for ACTUAL source-file tool-reads (Read/Grep/Glob/Bash inputs whose path
# references avir-cli/src) — NOT mere text mentions (so an implementer's own
# "do not read avir-cli/src" instruction does not false-positive).
#
# Validated 2026-06-26: across 17 prior subagents, exposed mappers showed 43-74 reads,
# every specs-only scrub agent showed 0. The metric separates the two cleanly.
#
# Usage:
#   wall-audit.sh <agent-name>        # globs the session subagents/ dir by name
#   wall-audit.sh --file <path.jsonl> # audits a specific transcript
#   wall-audit.sh --all               # audits every transcript, prints a table
#
# Exit: 0 = clean (0 src reads), 2 = TAINTED (>0 src reads). Non-zero on a walled
# implementer means discard that module and re-implement with a fresh walled agent.

SESSION_SUBAGENTS="${EMBER_SUBAGENTS_DIR:?EMBER_SUBAGENTS_DIR must be set — point it at your Claude Code session's subagents/ directory}"

# Count tool-input fields whose value references avir-cli/src (actual source access).
src_reads() {
  grep -oE '"(file_path|pattern|path|command|glob)"[[:space:]]*:[[:space:]]*"[^"]*avir-cli[\\/]+src[^"]*"' "$1" 2>/dev/null | wc -l
}
# Broader: any avir-cli path (src or otherwise) — informational.
any_avir() {
  grep -oE '"(file_path|pattern|path|command|glob)"[[:space:]]*:[[:space:]]*"[^"]*avir-cli[^"]*"' "$1" 2>/dev/null | wc -l
}

audit_one() {
  local f="$1" name="$2"
  local s a; s=$(src_reads "$f"); a=$(any_avir "$f")
  printf "%-28s src-reads=%-5s any-avir=%-5s %s\n" "$name" "$s" "$a" \
    "$( [ "$s" -eq 0 ] && echo 'CLEAN' || echo 'TAINTED <<<' )"
  [ "$s" -eq 0 ]
}

case "${1:-}" in
  --all)
    rc=0
    for f in "$SESSION_SUBAGENTS"/agent-a*.jsonl; do
      n=$(basename "$f" | sed -E 's/^agent-a//; s/-[0-9a-f]{16}\.jsonl$//')
      audit_one "$f" "$n" || rc=2
    done
    exit $rc ;;
  --file)
    audit_one "$2" "$(basename "$2")"; exit $? ;;
  "")
    echo "usage: wall-audit.sh <agent-name> | --file <path> | --all" >&2; exit 1 ;;
  *)
    f=$(ls "$SESSION_SUBAGENTS"/agent-a"$1"-*.jsonl 2>/dev/null | head -1)
    [ -z "$f" ] && { echo "no transcript for agent '$1' in $SESSION_SUBAGENTS" >&2; exit 1; }
    audit_one "$f" "$1"; exit $? ;;
esac
