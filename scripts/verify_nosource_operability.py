# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
#!/usr/bin/env python3
"""Executable acceptance harness for the no-source operability gate.

The pre-training gate requires the spine to be operable through ember-cli by
a person who has read no source file: every control a visible affordance, a
mouse click or a single keystroke -- no flags, no script paths, no knowledge
of which file to invoke. Until now that bar was judged per-capture by a
human. This harness MEASURES the statically-measurable half and names the
half it cannot measure.

DESIGN RULE - HONESTY OVER GREEN (same rule as verify_ember01_completion.py).
Every check carries one of:

    resolved-true    measured and holds
    resolved-false   measured and fails
    weak             the capability exists but is undiscoverable to a reader
                     with no source (implemented in a module body, absent from
                     the command's name and declared description), OR the
                     harness genuinely cannot resolve an invocation statically
                     (a runtime-computed path, an unreadable/binary hop).
                     This FAILS the gate: under a no-source bar an unfindable
                     or unconfirmable control is not a control.
    undecidable      cannot be decided statically; the receipt names exactly
                     what a human must look at
    ambiguous        (L3 spine rows only, added 2026-07-25) more than one
                     registered, named+described module satisfies the same
                     row's keywords. Never resolved by picking a winner --
                     alphabetical dict-iteration first-match previously did
                     this silently and once actually reassigned a spine row
                     to a command that does not implement it (a one-line
                     description edit made custody.ts win checkpoint_save_load
                     over the module that actually implements save/load,
                     caught by the editing lane's own re-run before it
                     shipped). The evidence names EVERY matching module so a
                     reviewer sees the competition; this FAILS the gate like
                     weak/undecidable -- an instrument that cannot tell which
                     module implements a row has not confirmed the row.

Overall verdict is FAIL unless every gating check is resolved-true. An
undecidable or ambiguous check never silently passes; each is reported and
excluded from the PASS claim, which is therefore explicitly partial.

WHAT IS MEASURED, AND HOW EVIDENCE IS BOUND (rework 2026-07-25; the previous
version let the artifact under measurement supply its own evidence -- a root
script counted as a launcher because of its FILE EXTENSION, and a module
counted as a registered command because of a KEYWORD IN ITS OWN TEXT. The
reviewer's exact-head hostile fixture at bcf1057 (a root `unrelated-maintenance.ps1`
containing only `Write-Host not-ember`, named once in the README, plus one
unregistered `all.ts` holding a keyword-bearing return object with no
registry import anywhere) produced verdict PASS, L1 resolved-true, all six
spine rows resolved-true. See
state/failure-classes/semantic-validation-without-bytes-2026-07-25.md,
"Fourth instance". Both L1 and L3 are rebuilt below to bind evidence to
bytes the artifact does not control):

  L1  `resolved-true` is granted ONLY by actually executing the candidate
      root launcher, for real, under a bounded timeout, in a scratch copy
      that never touches the real tree, with an owned SENTINEL substituted
      at the CLI entry -- and observing that the sentinel fires (round 4,
      2026-07-25). No reading of the launcher's text can grant true. This
      followed three text-based cures each defeated by the next unenumerated
      shape: extension (bcf1057) -> keyword mention (round 3, `dc6dcf3`) ->
      comment/print/dead-code-filtered mention (round 3 cure) ->
      "invocation position" grammar (round 3.1) -> defeated by `type
      "tools\ember-cli\src\main.ts"` (round 4's own probe): printing a
      path is neither a comment, a print-statement argument, nor dead code,
      so it is not any exclusion written so far, and is not the recognised
      grammar either -- it fell through to `ambiguous`/`weak` under round
      3.1, one static miss short of a false PASS. `findstr`, `copy`,
      `more`, `fc`, a redirection target are the same family: the set of
      non-invoking uses of a path is open-ended, and no exclusion list has
      a boundary. The runtime probe stops enumerating that set.

      Mechanism, round 6 (2026-07-25) shape. Round 5 tried to close round
      4's own defect (one shared marker for two substituted sentinels) by
      splitting into two markers and matching the runtime marker's OWN
      RECORDED ARGV against the declared entry -- and that argv-substring
      test was itself defeated on the first attempt: `--version
      entrypoints/main.ts` names the entry as an ARGUMENT TO --VERSION,
      never runs it, and `norm_entry in norm_argv` could not tell the two
      apart. Round 2's original defeat, "a mention anywhere in the bytes",
      recurring one layer deeper in the runtime's arguments instead of the
      launcher's text. The root cause was structural: the substituted
      runtime was an INERT marker-writer, so a genuine chain (which
      replaces bun, the thing that would have run the entry) could NEVER
      reach the entry directly -- that forced a text-based rescue, and
      every text-based rescue over an open-ended argument space has an open
      set of ways to satisfy it without doing the thing.

      Round 6 removes the proxy at its root: the substituted runtime is now
      a FAITHFUL minimal proxy that implements the actual contract it
      stands in for. Given `run <file>` as its first two tokens, it
      DELEGATES to the real `bun` to execute `<file>`, for real. Given
      anything else -- `--version`, `--help`, a bare flag, the entry path
      handed to a flag that isn't `run` -- it executes nothing, exactly as
      the real bun would not run a script it was never asked to run.
      `resolved-true` for L1 now comes from EXACTLY ONE observation: the
      ENTRY marker (written by code substituted directly into the CLI entry
      file) firing because that file's own bytes actually executed. There
      is no second path to true anymore -- the runtime marker and its
      recorded argv are still captured in the receipt, explicitly labelled
      `..._DIAGNOSTIC_ONLY_NOT_VERDICT_BEARING`, purely so a human reading
      the receipt can see what the runtime was invoked with, but the
      harness itself no longer reasons about that text at all.

      The CLI entry file (package.json's `bin` target -- the one
      spec-declared location, never a string a candidate happens to
      mention) is overwritten in the scratch copy with the entry stub.
      `EMBER_LAUNCH_TEST_MODE=1` substitutes the faithful runtime proxy for
      `bun` at this repository's own `& $bun run entrypoints/main.ts` call
      site -- the hook exists in `launch-ember-cli.ps1` precisely for this,
      letting the probe avoid the real production path's git-identity and
      built-desktop-app requirements, neither of which a bounded probe can
      safely exercise, while still genuinely reaching the entry through
      real delegation. Any launcher that does not read these env vars
      (every hostile/synthetic fixture) simply ignores them.

      Verdict: a probe that could not even be STARTED (no interpreter for
      the candidate's extension, the scratch stage failed, the OS refused
      to launch it) is `weak` -- the environment told us nothing. Every
      other outcome without the entry marker firing is `resolved-false` --
      a definite negative, not an absence of information, whether the
      runtime was invoked with an unrelated command, invoked with `run` on
      a different file, or never invoked at all. The receipt binds both
      stub byte sets, the launcher bytes, cwd, argv, timeout, exit code,
      the entry marker's content when it fired, and the runtime's
      diagnostic-only argv when it fired, so the verdict is reproducible
      without rerunning it.

      The round-3/3.1 static machinery (`resolve_invocation`,
      `_matches_known_launcher_grammar`, comment/print/dead-code exclusion)
      is KEPT but DEMOTED: it may narrow candidates or refuse outright as a
      pre-filter, and its evidence is still included for diagnostic value,
      but it may never independently grant `resolved-true` -- that
      authority belongs to the entry marker alone.

      Round 7 (2026-07-25) amendment. Round 6's own defeat: a launcher that
      COPIES the CLI entry's substituted bytes out of the tree (`copy
      tools\ember-cli\src\entrypoints\main.ts %TEMP%\stolen-entry.ts`) and
      then genuinely delegates `run` on the COPY. The entry marker fires --
      the bytes really did execute, that observation is not false -- but it
      answers the wrong question: L1 asks whether the launcher invokes the
      CLI *from where it lives*, and a copy run from `%TEMP%` (or any other
      directory, in-tree or not) never does. "The bytes fired" and "the
      bytes fired in place" are different claims, and round 6 only checked
      the first one. The fix is not another exclusion list on the launcher's
      text -- it is the SAME category of evidence as the fire itself: the
      executing process reporting its own identity. Every entry stub now
      writes its own resolved execution path into the marker -- `__filename`
      for the JS-family stubs (never `process.argv[1]`, which is only the
      string a caller happened to type and could name any path),
      `os.path.abspath(__file__)` for Python, `$PSCommandPath` for
      PowerShell, `%~f0` for cmd/bat, a `realpath`/`readlink -f` resolution
      chain for sh -- always the interpreter's own report of what it is
      currently running, never a caller-supplied value. `resolved-true` now
      requires BOTH the entry marker firing AND that recorded path resolving
      to the scratch tree's actual CLI entry (`entry_marker_path_matches_
      declared_entry` in the receipt). Fired from anywhere else --
      including a different directory still inside the tree -- is
      `resolved-false`, with evidence naming the mismatch: the entry's bytes
      executed, but not from where the CLI actually lives, so the launcher
      did not invoke it in place.
  L2  Launcher is documented: README.md or docs/START-HERE.md names a
      launcher that itself resolved-true, so a no-source reader can find a
      real one (documenting a decoy does not count).
  L3  Spine-function surface: each gate-named function (custody+identity,
      data/tokenizer lineage, checkpoint save/load, owned serving,
      benchmarking, 3B training launch) is exposed as a NAMED command with a
      DESCRIPTION inside a module `command-registry.ts` actually imports and
      calls from its builtin-command list. A module's own text is never
      evidence of its own registration -- only the registry's import graph
      is. A function whose only match is an unregistered module has that
      row stay unsatisfied. Combined concepts (two nouns in one function
      name) require BOTH keywords present -- one alone is `weak`, never a
      match.

FAIL-CLOSED: a missing file, unreadable directory, unparseable package.json,
unparseable command-registry.ts, or an empty command registry is
resolved-false, never a silent pass.

WHAT IS NOT MEASURED (permanently undecidable here, human capture required):
  - whether the command actually appears as a visible affordance in the
    running UI (menu/palette rendering);
  - whether operating it takes one click/keystroke rather than typed flags;
  - whether the launched process reaches a usable first pixel.
  - round 3 (2026-07-25) closed the comment/print/dead-code-after-exit
    forms of "a string that never executes still counts". Round 3.1
    narrowed acceptance to one exact grammar, defeated by `type
    "tools\ember-cli\src\main.ts"`. Round 4 replaced static text-reasoning
    with actual execution, and shipped its own proxy (one shared marker for
    two substituted sentinels). Round 5 split the markers but tried to
    rescue the genuine-chain case with an argv-substring match, defeated by
    `--version entrypoints/main.ts` -- the entry named as an argument to a
    flag that never runs it. Round 6 (2026-07-25) removes the proxy at its
    structural root: the substituted runtime is now a faithful minimal
    proxy that genuinely delegates `run <file>` to real `bun` and refuses
    everything else, so `resolved-true` needs exactly one observation (the
    entry marker) and no text-matching rescue is needed for the genuine
    chain to reach it. Round 7 (2026-07-25) closed the remaining gap round 6
    disclosed openly above (the entry marker firing was necessary but not
    sufficient -- a launcher could copy the entry's substituted bytes
    elsewhere and run the copy, firing the marker from the wrong place): the
    entry stub now records its own resolved execution path from inside the
    executing process, and `resolved-true` requires that path to equal the
    scratch tree's actual CLI entry location, not merely that entry-shaped
    bytes fired somewhere. What remains OPEN, disclosed rather than silently
    passed: (a) a launcher whose real invocation depends on interactive
    input, a specific OS/shell the probe's runner table does not cover, or
    state outside the scratch copy (a required system service, a mapped
    network drive) -- the probe reads as `weak` for these; (b) a launcher
    that behaves differently when actually invoked by a human than under
    the probe's non-interactive, env-overridden, timeout-bounded execution
    -- the probe proves the CLI entry is REACHABLE, not that the human
    experience is identical; (c) the probe substitutes bytes at one
    well-defined location (package.json's `bin` target) and one named
    env-var hook -- a launcher reaching a genuinely different, undeclared
    entry point through a path this harness cannot discover would not be
    instrumented at all; (d) THE BYTES THAT EXECUTE AT THE ENTRY, when the
    entry marker fires, ARE THE PROBE'S OWN STUB, never the real
    `main.ts`/`main.js` -- this is inherent and by design (L1 asks whether
    control reaches the entry, not what the entry then does; L3 and the
    undecidable UI-affordance items below cover what happens once code is
    running), but it means a chain that reaches the entry through some
    mechanism our stub's own syntax cannot execute (a shell form outside
    the extension table, an entry file whose real content matters to
    whether *later* code in the same file would also run) is outside this
    check's reach. None of these is a text-shape guess any longer; each is
    a scope boundary of what one bounded, sandboxed execution, with a
    faithful runtime proxy, can observe.

Usage:  python scripts/verify_nosource_operability.py [--root PATH] [--json]
Exit 0 = PASS (of the measurable half), 1 = FAIL, 2 = harness error.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import deque
from pathlib import Path

LAUNCHER_CANDIDATE_SUFFIXES = {".cmd", ".bat", ".ps1", ".exe", ".sh"}
LAUNCHER_NAME_HINT = re.compile(r"^(ember|launch|start|run)", re.IGNORECASE)
DOC_FILES = ("README.md", "docs/START-HERE.md")
COMMANDS_DIR = "tools/ember-cli/src/commands"
PACKAGE_JSON = "tools/ember-cli/src/package.json"
COMMAND_REGISTRY = "tools/ember-cli/src/command-registry.ts"

# What "lands inside the repo's CLI entry" means for L1: a resolved
# invocation target (or any string literal encountered along the chain,
# however it was constructed -- e.g. PowerShell Join-Path arguments) whose
# normalized, slash-forward, lower-cased text contains this substring.
CLI_ENTRY_MARKER = "tools/ember-cli"

MAX_INVOCATION_DEPTH = 6

# Gate-named spine functions -> keywords that must appear in a NAMED,
# REGISTERED command module (module name or declared description for the
# STRONG pass; module body for the WEAK pass). Keywords are lowercase WORD
# STEMS, not bare substrings (2026-07-25): a keyword matches only where it
# begins at a word boundary (not preceded by a letter or digit), with any
# suffix allowed -- "train" matches "train"/"training"/"trainer", never the
# interior of "constraint"/"retrain"/"restraint"; "serv" matches
# "serving"/"serve"/"server", never the interior of "observatory". Why: the
# ambiguity check below only fires on a COLLISION between two matching
# modules, so a row with exactly ONE matching module still resolved true
# when that single match was a coincidental interior-substring hit -- a lone
# registered module whose description merely mentioned a *constraint*
# satisfied training_launch_3b, the row that certifies the operator can
# launch a 3B training run, with no collision to catch it (same family as
# the "seat"/owned_serving_path and checkpoint_save_load near-misses, one
# guard-gap over). Suffixes stay allowed on purpose: the stems are chosen as
# the concept's own root, and forcing whole-word-only would over-close
# ("serv" never appears as a whole word; "training" is how train.ts's
# description names the concept). DISCLOSED RESIDUE, not covered: a genuine
# word-prefix collision ("service" begins with "serv"; a hyphenated
# "re-train" puts "train" at a boundary) is still a match -- boundary
# anchoring kills the interior-substring class both incidents belong to, not
# every coincidence expressible in English; a collision of that kind still
# lands in the ambiguity check when a real competitor exists.
SPINE_FUNCTIONS = {
    "custody_and_identity_manifest": ["custody", "identity"],
    "data_tokenizer_lineage": ["tokenizer", "lineage"],
    "checkpoint_save_load": ["checkpoint"],
    # "seat" was dropped 2026-07-25: it is custody.ts's OWN classification
    # noun and its declared alias, not a serving-path noun, so keeping it in
    # an OR-of-three row let custody.ts win this row permanently on
    # unrelated prose ("model seat classification") -- the live instance of
    # the ambiguity-fix incident, caught by this file's over-closure check
    # against real origin/master. There is no disjunctive slot in
    # CONJUNCTION_FUNCTIONS ((owned AND (serve OR seat)) is not
    # expressible), so the row is narrowed to the goal clause's own two
    # nouns, both required: "owned" + "serv" (not "serve" -- "serving" does
    # not contain the substring "serve", but does contain "serv").
    "owned_serving_path": ["owned", "serv"],
    "benchmarking": ["benchmark"],
    "training_launch_3b": ["train"],
}

# Functions whose name carries two distinct required nouns: BOTH keywords
# must be present, never just one ("custody alone" must not satisfy
# custody_and_identity_manifest -- that was the second half of the bcf1057
# defect, independent of the registration-graph half). owned_serving_path
# joined this set 2026-07-25 for the same reason (see the SPINE_FUNCTIONS
# comment above): a single OR'd keyword let an unrelated module win the row.
CONJUNCTION_FUNCTIONS = {
    "custody_and_identity_manifest",
    "data_tokenizer_lineage",
    "owned_serving_path",
}

# Word-stem matching for spine keywords (see the SPINE_FUNCTIONS comment):
# the keyword must begin at a word boundary -- not preceded by [a-z0-9] --
# with any suffix allowed. Compiled once per keyword.
_KEYWORD_RE_CACHE: dict[str, re.Pattern] = {}


def _keyword_re(keyword: str) -> re.Pattern:
    pat = _KEYWORD_RE_CACHE.get(keyword)
    if pat is None:
        pat = re.compile(r"(?<![a-z0-9])" + re.escape(keyword))
        _KEYWORD_RE_CACHE[keyword] = pat
    return pat


def keyword_in(keyword: str, hay_lower: str) -> bool:
    return bool(_keyword_re(keyword).search(hay_lower))


def keyword_count(keyword: str, hay_lower: str) -> int:
    return len(_keyword_re(keyword).findall(hay_lower))


NAME_RE = re.compile(r'name:\s*"([a-z0-9-]+)"')
DESC_RE = re.compile(r"description:")
# The declared description text itself -- for a reader with no source, the
# description IS the discoverability surface, so a keyword that appears only in
# the module body is NOT reachable knowledge.
DESC_TEXT_RE = re.compile(r'description:\s*(?:\n\s*)?"((?:[^"\\]|\\.)*)"')

# Files that must exist for a directory to be the ember repository. The harness
# resolves its root as parent-of-script-dir, which silently judges whatever tree
# a stray copy lands in: on 2026-07-24 a misplaced copy resolved to a user home
# directory and reported three unrelated PowerShell scripts as "ember's root
# launchers", which would have passed L1. Absence of every marker is a harness
# error, not a verdict about ember.
ROOT_MARKERS = ("INVARIANT.md", "GOAL.md", COMMANDS_DIR, PACKAGE_JSON)

# --- L1 static invocation resolution -----------------------------------

# A quoted string literal, single- or double-quoted, no embedded newline.
_STRING_LIT_RE = re.compile(r'"([^"\n]{1,300})"|\'([^\'\n]{1,300})\'')
# A literal counts as "path-like" only if it carries a path separator or a
# recognised script/binary extension -- this keeps plain messages
# ("Ember does not accept arguments.") from being treated as invocations.
_PATH_LIKE_RE = re.compile(
    r"[\\/]|\.(?:ts|js|mjs|cjs|ps1|cmd|bat|sh|exe|py)$", re.IGNORECASE
)
# A variable sigil the harness cannot evaluate statically. The one exception
# is the deterministic batch macro %~dp0 (script's own directory), which
# normalize_literal() strips before this check runs.
_VAR_MARKER_RE = re.compile(r"\$|%")
_ABS_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]|^/")


def check(state: str, evidence: str) -> dict:
    return {"state": state, "evidence": evidence}


def assert_ember_root(root: Path) -> None:
    """Fail closed unless `root` is recognisably the ember repository."""
    present = [m for m in ROOT_MARKERS if (root / m).exists()]
    if not present:
        raise RuntimeError(
            f"{root} carries none of the ember root markers {list(ROOT_MARKERS)}; "
            "refusing to report a verdict about a tree that is not ember. Run "
            "this harness from the repository root (scripts/ is its home) or "
            "pass --root explicitly."
        )


def find_root_launcher_candidates(root: Path) -> list[Path]:
    """Files at repo root worth OPENING to check what they invoke. Extension
    and name-hint decide candidacy only -- never the verdict itself."""
    found = []
    try:
        entries = sorted(p for p in root.iterdir() if p.is_file())
    except OSError as exc:
        raise RuntimeError(f"repo root unreadable: {exc}") from exc
    for p in entries:
        if p.suffix.lower() in LAUNCHER_CANDIDATE_SUFFIXES:
            found.append(p)
        elif p.suffix == "" and LAUNCHER_NAME_HINT.match(p.name):
            found.append(p)
    return found


# A batch comment line (REM / ::) or a shell/PowerShell comment line (#).
# Comment text never executes, so a literal inside one is not evidence of
# anything -- it is excluded before extraction, not scored as ambiguous.
_BATCH_COMMENT_RE = re.compile(r"^(rem\b|::)", re.IGNORECASE)
_HASH_COMMENT_RE = re.compile(r"^#")

# A print statement's argument is text the script DISPLAYS, never a target it
# invokes -- "tools/ember-cli/src" inside an echo/Write-Host string proves
# only that the string exists, the same shape as a comment.
_PRINT_LINE_RE = re.compile(
    r"write-host|write-output|write-warning|write-verbose|^\s*(echo\b|printf\b)",
    re.IGNORECASE,
)

# A bare, unconditional terminator at the CURRENT nesting depth ends
# reachability for the rest of the file. This is a narrow, disclosed
# heuristic -- it catches the plain "dead code after an unconditional exit"
# shape, not general control-flow reachability (an `if (0) ( ... )` block,
# for example, is not specially detected; see the module docstring).
_UNCONDITIONAL_EXIT_RE = re.compile(r"^(exit(\s*/b)?(\s+\S+)?|return)$", re.IGNORECASE)


def _reachable_lines(text: str, suffix: str) -> list[str]:
    """The left-stripped text of every line bytes can actually reach and
    act on: comment lines, print-statement arguments, and code after an
    unconditional top-level terminator are excluded before extraction,
    never merely deprioritized. Depth is tracked with the block delimiter
    each shell form actually uses -- parens for batch `if (...)`/`for (...)`
    bodies, braces for PowerShell/shell `{ ... }` bodies -- so an
    unconditional exit INSIDE a conditional block (depth > 0) is correctly
    read as conditional, not as ending the file's reachability. A line that
    is itself a print statement (its whole line is excluded, not just its
    trailing argument) is still walked for depth so a `Write-Host "... ) ..."`
    line doesn't desynchronize the counter."""
    is_batch = suffix.lower() in (".cmd", ".bat")
    open_char, close_char = ("(", ")") if is_batch else ("{", "}")
    out: list[str] = []
    depth = 0
    dead = False
    for raw_line in text.splitlines():
        if dead:
            continue
        stripped = raw_line.strip()
        is_comment = (
            bool(_BATCH_COMMENT_RE.match(stripped))
            if is_batch
            else bool(_HASH_COMMENT_RE.match(stripped))
        )
        if is_comment:
            continue
        pre_depth = depth
        if pre_depth == 0 and _UNCONDITIONAL_EXIT_RE.match(stripped):
            dead = True
            continue
        depth += raw_line.count(open_char) - raw_line.count(close_char)
        if _PRINT_LINE_RE.search(raw_line):
            continue
        out.append(stripped)
    return out


def extract_invoking_literals(text: str, suffix: str) -> list[str]:
    """Path-like quoted literals drawn only from reachable lines (see
    `_reachable_lines`)."""
    out: list[str] = []
    for line in _reachable_lines(text, suffix):
        for m in _STRING_LIT_RE.finditer(line):
            s = m.group(1) if m.group(1) is not None else m.group(2)
            if s and _PATH_LIKE_RE.search(s):
                out.append(s)
    return out


# --- Round 3.1: exact grammar for the launcher shape we actually generate --
#
# Round 3's "does this literal sit in an invocation position" check is
# itself a text-presence proxy one level in from the extension/keyword
# proxies this rework already closed twice: a better guess about which
# token position means "invoking", still not evidence about what the
# script does. Rather than generalize that guess further, this narrows the
# FINAL acceptance test to the exact two-statement shape our own build
# emits: a variable bound via `Join-Path` to a path landing inside
# `tools/ember-cli`, that SAME variable later used in a `Push-Location`/
# `Set-Location` statement, and a call-operator invocation (`& $x ...`)
# appearing after that. A literal that merely CONTAINS the CLI-entry
# substring, without this causal shape around it, no longer resolves true
# on its own -- it is `weak`, not reasoned about further. Everything outside
# this exact grammar -- a different launcher pattern this repo has never
# generated, an indirect binding, a computed path -- is refused as weak.
#
# A bounded runtime probe (substitute a sentinel at the CLI entry, execute
# the launcher under a timeout in a scratch copy, observe whether control
# reaches the sentinel) is the stronger form and was not taken this round;
# see rework-harness-r3-1-report.md for why.
_JOIN_PATH_ASSIGN_RE = re.compile(
    r'^\$(\w+)\s*=\s*Join-Path\s+\$\w+\s+"([^"]*)"', re.IGNORECASE
)
_CALL_OPERATOR_RE = re.compile(r"^&\s*\$\w+\b")


def _matches_known_launcher_grammar(text: str, suffix: str) -> bool:
    lines = _reachable_lines(text, suffix)
    for i, line in enumerate(lines):
        m = _JOIN_PATH_ASSIGN_RE.match(line)
        if not m:
            continue
        varname, path_lit = m.group(1), m.group(2)
        if CLI_ENTRY_MARKER not in path_lit.replace("\\", "/").lower():
            continue
        push_re = re.compile(
            rf"^(push-location|set-location)\s+\${re.escape(varname)}\b", re.IGNORECASE
        )
        saw_push = False
        for later in lines[i + 1 :]:
            if not saw_push:
                if push_re.match(later):
                    saw_push = True
                continue
            if _CALL_OPERATOR_RE.match(later):
                return True
    return False


def normalize_literal(lit: str) -> str:
    s = lit
    if s.lower().startswith("%~dp0"):
        s = s[len("%~dp0"):]
    return s.replace("\\", "/")


def _within(target: Path, root: Path) -> bool:
    try:
        target.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def resolve_invocation(entry: Path, root: Path) -> dict:
    """Statically walk what `entry`'s bytes invoke, hop by hop, and decide
    whether the chain lands inside the repo's owned CLI entry. Never trusts
    the candidate's own extension or name -- only bytes it references, and
    the files those references resolve to."""
    depth_of: dict[str, int] = {str(entry): 0}
    queue: deque[Path] = deque([entry])
    visited: set[str] = set()

    saw_literal_at_entry = False
    confident_misses: list[str] = []  # fully resolved, but not the CLI entry
    ambiguous: list[str] = []  # cannot be pinned down statically

    while queue:
        current = queue.popleft()
        key = str(current)
        if key in visited:
            continue
        visited.add(key)
        depth = depth_of[key]

        if current.suffix.lower() == ".exe":
            norm = str(current).replace("\\", "/").lower()
            if CLI_ENTRY_MARKER in norm:
                return check(
                    "resolved-true",
                    f"{entry.name}: invocation chain reaches a binary target "
                    f"under {CLI_ENTRY_MARKER}: {current}",
                )
            ambiguous.append(f"{current.name}: binary target, cannot inspect further")
            continue

        try:
            text = current.read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeError) as exc:
            ambiguous.append(f"{current.name}: unreadable ({exc})")
            continue

        literals = extract_invoking_literals(text, current.suffix)
        if current == entry:
            saw_literal_at_entry = bool(literals)

        if _matches_known_launcher_grammar(text, current.suffix):
            return check(
                "resolved-true",
                f"{entry.name}: invocation chain reaches {current.name}, whose "
                f"reachable code binds a variable via Join-Path to a path "
                f"inside {CLI_ENTRY_MARKER}, Push-Location's into it, and "
                f"invokes via the call operator -- the exact launcher grammar "
                f"this repository generates",
            )

        for lit in literals:
            norm = normalize_literal(lit)
            if CLI_ENTRY_MARKER in norm.lower():
                # The literal names the CLI entry, but this file's reachable
                # code does not match the known launcher grammar around it --
                # a mention is not, on its own, evidence of invocation
                # (round 3.1: text presence deciding the verdict is exactly
                # the class this rework exists to close). Undecided, not
                # false: something else might legitimately invoke this
                # differently than the one grammar this harness recognises.
                ambiguous.append(
                    f'{current.name}: "{lit}" names {CLI_ENTRY_MARKER} but does '
                    "not match the known launcher grammar (no Join-Path-bound "
                    "variable Push-Location'd and then invoked) -- cannot "
                    "confirm invocation from text alone"
                )
                continue
            if _VAR_MARKER_RE.search(norm):
                ambiguous.append(
                    f'{current.name}: "{lit}" is a runtime-computed path, '
                    "cannot resolve statically"
                )
                continue
            candidates = [root / norm, current.parent / norm]
            if _ABS_PATH_RE.match(lit):
                candidates.append(Path(lit))
            target = None
            for cand in candidates:
                try:
                    if cand.exists() and cand.is_file():
                        target = cand
                        break
                except OSError:
                    continue
            if target is None:
                confident_misses.append(f'{current.name}: "{lit}" does not exist')
                continue
            if not _within(target, root):
                confident_misses.append(
                    f'{current.name}: "{lit}" resolves to {target}, outside the repository'
                )
                continue
            if depth + 1 > MAX_INVOCATION_DEPTH:
                ambiguous.append(
                    f'{current.name}: "{lit}" -> {target.name} exceeds max hop depth'
                )
                continue
            tkey = str(target)
            if tkey not in depth_of:
                depth_of[tkey] = depth + 1
                queue.append(target)

    if not saw_literal_at_entry and not confident_misses and not ambiguous:
        return check(
            "resolved-false",
            f"{entry.name}: no path-like string literal found; nothing in its "
            "bytes references another file, so it invokes nothing statically "
            "resolvable -- not a launcher",
        )
    if ambiguous and not confident_misses:
        return check(
            "weak",
            f"{entry.name}: invocation cannot be resolved statically: "
            + "; ".join(ambiguous[:5]),
        )
    evidence_bits = confident_misses + ambiguous
    return check(
        "resolved-false",
        f"{entry.name}: references resolve, but none land inside "
        f"{CLI_ENTRY_MARKER}: " + "; ".join(evidence_bits[:5]),
    )


# --- Round 4: bounded runtime sentinel probe -----------------------------
#
# Round 3.1's exact grammar was itself defeated: `type "tools\ember-cli\src\
# main.ts"` (or `findstr`/`copy`/`more`/`fc`/a redirection target -- any of
# the open-ended non-invoking uses of a path) sits outside every exclusion
# written so far and is not the causal grammar either, so it slipped past
# both as an unrecognised-but-present literal. The reviewer's point: the set
# of ways a string can appear without acting is open-ended, and no static
# exclusion list has a boundary. Every static guess in this file -- about
# extension, then mention, then position, then grammar -- has been a better
# guess about what characters MEAN. This round stops guessing.
#
# The static machinery above (`resolve_invocation`, `_matches_known_launcher_
# grammar`, comment/print/dead-code exclusion) is KEPT, but is no longer the
# grantor of `resolved-true`. It may only narrow candidates or refuse
# outright. `resolved-true` for L1 is reserved for one thing: an owned
# sentinel, substituted for the real CLI entry, that is OBSERVED TO FIRE when
# the candidate launcher is actually executed, for real, under a bounded
# timeout, in a scratch copy that never touches the real tree.
#
# Two substitution points, both exercised on every probe:
#   1. The CLI entry FILE itself (package.json's `bin` target, the one
#      spec-declared location -- not any string a candidate launcher happens
#      to mention) is overwritten with a tiny, extension-appropriate stub
#      that writes a marker file when its bytes are actually executed. This
#      catches any launcher shape, hostile or genuine, that does not know
#      about this repository's own test-mode hook.
#   2. `EMBER_LAUNCH_TEST_MODE=1` / `EMBER_LAUNCH_TEST_RUNTIME=<owned
#      sentinel executable>` are set in the probe's environment. This
#      repository's own `launch-ember-cli.ps1` carries this hook precisely
#      so a substitute runtime can stand in for bun at the exact call site
#      `& $bun run entrypoints/main.ts`, without requiring a real git
#      identity or a built desktop app -- both of which the genuine
#      production path needs and neither of which a bounded probe can
#      safely exercise. For any launcher that does not read this env var
#      (every hostile/synthetic fixture), it is inert.
#
# Verdict: a probe that could not even be started (no interpreter for this
# extension available, the scratch stage failed, the OS refused to launch
# it) is WEAK -- the environment told us nothing about the launcher. Every
# other outcome is judged by ONE thing: did the ENTRY marker fire. Nothing
# else grants resolved-true.
#
# Round 5 (2026-07-25) tried a second instrument -- the substituted runtime's
# own recorded argv -- to rescue the case where a genuine chain replaces the
# real runtime (bun) and so can never reach the entry stub directly. That
# rescue was itself defeated in one attempt: `--version entrypoints/main.ts`
# passes the entry path as an ARGUMENT to a flag that never runs it, and
# `norm_entry in norm_argv` -- a substring test -- could not tell "the entry
# is what got run" from "the entry is merely present somewhere in the
# argument list". Round 2's defeat ("a mention anywhere in the bytes"),
# recurring one layer deeper, in the runtime's arguments instead of the
# launcher's text. Seven rounds, and every one of them bound to TEXT about
# execution rather than to execution.
#
# Round 6 (2026-07-25) removes the proxy at its root instead of patching it
# again: the reason the argv rule was ever reachable is that the substituted
# runtime was an INERT marker-writer, so a genuine chain could never actually
# reach the entry through it -- that absence is what forced a text-based
# rescue in the first place, and every text-based rescue has an open set of
# ways to satisfy it without doing the thing. The runtime stub now
# implements the actual contract it stands in for: given `run <file>`, it
# DELEGATES to the real `bun` to execute `<file>`, for real. Given anything
# else (`--version`, `--help`, a bare flag, an unrelated subcommand, `<file>`
# passed to a flag that isn't `run`), it does nothing -- exactly as the real
# bun would not execute a script it was never asked to run.
#
# `resolved-true` for L1 now comes from EXACTLY ONE observation: the ENTRY
# marker, written by code substituted directly into the CLI entry file,
# fired because that file's own bytes executed. On a genuine chain this now
# happens through real delegation -- the substituted runtime is faithful, so
# `& $bun run entrypoints/main.ts` genuinely reaches the sentinel-substituted
# main.ts, for real, under bun. There is no second, weaker path to true
# anymore. The runtime marker (and its recorded argv) is kept in the receipt
# as diagnostic colour only -- explicitly labelled NOT verdict-bearing --
# because a human reading the receipt still benefits from seeing what the
# runtime was invoked with, even though the harness itself no longer reasons
# about it.

ENTRY_MARKER_NAME = "EMBER_PROBE_ENTRY_FIRED.txt"
RUNTIME_MARKER_NAME = "EMBER_PROBE_RUNTIME_INVOKED.txt"
SENTINEL_TIMEOUT_SECONDS = 25

# Extension-appropriate stub written INTO the package.json-declared CLI entry
# file inside the scratch copy. Each writes the ENTRY marker only if the env
# var naming it is actually set (so accidentally running the unmodified repo
# tree some other way never fires it) and does nothing else -- no network,
# no other side effects.
_ENTRY_STUB_BY_SUFFIX = {
    # Round 7: every JS-family stub reports __filename (or its ESM
    # equivalent) -- Node/bun's OWN resolution of what file is currently
    # executing -- never process.argv[1], which is only the string the
    # caller happened to type on the command line and could name any path
    # regardless of what actually ran.
    ".ts": (
        "if (process.env.EMBER_PROBE_ENTRY_MARKER) {\n"
        "  require('fs').writeFileSync(process.env.EMBER_PROBE_ENTRY_MARKER, __filename);\n"
        "}\n"
    ),
    ".js": (
        "if (process.env.EMBER_PROBE_ENTRY_MARKER) {\n"
        "  require('fs').writeFileSync(process.env.EMBER_PROBE_ENTRY_MARKER, __filename);\n"
        "}\n"
    ),
    ".mjs": (
        "if (process.env.EMBER_PROBE_ENTRY_MARKER) {\n"
        "  await import('url').then(u => import('fs').then(fs => "
        "fs.writeFileSync(process.env.EMBER_PROBE_ENTRY_MARKER, u.fileURLToPath(import.meta.url))));\n"
        "}\n"
    ),
    ".cjs": (
        "if (process.env.EMBER_PROBE_ENTRY_MARKER) {\n"
        "  require('fs').writeFileSync(process.env.EMBER_PROBE_ENTRY_MARKER, __filename);\n"
        "}\n"
    ),
    ".py": (
        "import os\n"
        "if os.environ.get('EMBER_PROBE_ENTRY_MARKER'):\n"
        "    open(os.environ['EMBER_PROBE_ENTRY_MARKER'], 'w').write(os.path.abspath(__file__))\n"
    ),
    ".ps1": (
        'if ($env:EMBER_PROBE_ENTRY_MARKER) { Set-Content -LiteralPath $env:EMBER_PROBE_ENTRY_MARKER -Value $PSCommandPath }\n'
    ),
    ".cmd": (
        "@echo off\r\n"
        'if defined EMBER_PROBE_ENTRY_MARKER echo %~f0>"%EMBER_PROBE_ENTRY_MARKER%"\r\n'
    ),
    ".bat": (
        "@echo off\r\n"
        'if defined EMBER_PROBE_ENTRY_MARKER echo %~f0>"%EMBER_PROBE_ENTRY_MARKER%"\r\n'
    ),
    ".sh": (
        "#!/bin/sh\n"
        'if [ -n "$EMBER_PROBE_ENTRY_MARKER" ]; then\n'
        '  P=$(realpath "$0" 2>/dev/null || readlink -f "$0" 2>/dev/null || echo "$0")\n'
        '  echo "$P" > "$EMBER_PROBE_ENTRY_MARKER"\n'
        "fi\n"
    ),
}

# Standalone runtime executable substituted for `bun` via
# EMBER_LAUNCH_TEST_RUNTIME (round 6). ALWAYS records its own argv (`%*`,
# verbatim) to the runtime marker -- diagnostic colour only, never
# verdict-bearing. Then implements the actual contract it stands in for:
# `run <file>` DELEGATES to the real `bun` to execute `<file>`, for real, so
# a genuine chain's entry stub is genuinely reached. Anything else (a bare
# flag, an unrelated subcommand, the entry path handed to a flag that isn't
# `run`) executes nothing -- exactly as the real bun would not run a script
# it was never asked to run. This is what makes the argv-substring rescue
# from round 5 unnecessary: the entry marker can now fire on its own, for
# real, through this proxy.
_SENTINEL_RUNTIME_STUB = (
    "@echo off\r\n"
    'if defined EMBER_PROBE_RUNTIME_MARKER echo %*>"%EMBER_PROBE_RUNTIME_MARKER%"\r\n'
    'if /I not "%~1"=="run" exit /b 0\r\n'
    'if "%~2"=="" exit /b 0\r\n'
    'bun "%~2"\r\n'
    "exit /b %ERRORLEVEL%\r\n"
)

_LAUNCHER_RUNNERS = {
    ".cmd": lambda p: ["cmd.exe", "/c", str(p)],
    ".bat": lambda p: ["cmd.exe", "/c", str(p)],
    ".ps1": lambda p: [
        "powershell.exe",
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(p),
    ],
    ".sh": lambda p: [shutil.which("bash") or shutil.which("sh") or "sh", str(p)],
}

# Directories never worth copying into a probe's scratch tree -- version
# control, dependency caches, and this harness's own prior-round scratch
# extractions (which would otherwise recurse into themselves).
_PROBE_COPY_SKIP_NAMES = {".git", "node_modules", ".ember", "receipts", "models", "data"}
_PROBE_COPY_SKIP_PREFIX_RE = re.compile(r"^_(wr|r3|r4|pr|fixture|master)")


def _resolve_cli_entry(root: Path) -> tuple[Path, str] | None:
    """The one spec-declared CLI entry: package.json's `bin` target. Not any
    string a candidate launcher happens to mention -- the sentinel always
    substitutes this exact, well-defined location. Returns (file, raw_rel)
    where raw_rel is the bin field's own string (e.g. "./entrypoints/
    main.ts"), needed verbatim to judge a runtime stub's recorded argv --
    that argv is exactly what the real launcher passes, which is this raw
    value, not a path re-derived some other way."""
    pkg_path = root / PACKAGE_JSON
    try:
        pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    bin_entry = pkg.get("bin")
    if not isinstance(bin_entry, dict) or not bin_entry:
        return None
    rel = next(iter(bin_entry.values()), None)
    if not isinstance(rel, str) or not rel:
        return None
    stripped = rel.lstrip("./").lstrip(".\\")
    return pkg_path.parent / stripped, stripped


def _probe_copy_ignore(_dirpath: str, names: list[str]) -> list[str]:
    return [
        n
        for n in names
        if n in _PROBE_COPY_SKIP_NAMES or _PROBE_COPY_SKIP_PREFIX_RE.match(n)
    ]


def run_sentinel_probe(launcher: Path, root: Path) -> dict:
    """Execute `launcher` for real, under a timeout, in a scratch copy that
    never touches `root`, with the CLI entry substituted for an owned
    sentinel and the runtime substituted for a FAITHFUL minimal proxy that
    delegates `run <file>` to the real interpreter and refuses everything
    else. `resolved-true` requires the ENTRY marker, and ONLY the entry
    marker -- nothing about the launcher's own text, nor the runtime's argv,
    is consulted for this verdict (round 6, after round 5's argv-substring
    rescue was itself defeated by an entry path passed to an unrelated
    flag)."""
    suffix = launcher.suffix.lower()
    runner_fn = _LAUNCHER_RUNNERS.get(suffix)
    if runner_fn is None:
        return check(
            "weak",
            f"{launcher.name}: no known way to execute a {suffix or '(no extension)'} "
            "file for the runtime probe -- an environment that cannot run this "
            "candidate has not told us the launcher is bad",
        )

    resolved = _resolve_cli_entry(root)
    if resolved is None:
        return check(
            "weak",
            f"{launcher.name}: cannot resolve a CLI entry target from "
            f"{PACKAGE_JSON}'s bin field -- nothing to instrument",
        )
    entry_file, entry_bin_rel = resolved
    entry_suffix = entry_file.suffix.lower()
    stub = _ENTRY_STUB_BY_SUFFIX.get(entry_suffix)
    if stub is None:
        return check(
            "weak",
            f"{launcher.name}: CLI entry {entry_file.name} has an unsupported "
            f"extension {entry_suffix!r} for textual sentinel instrumentation",
        )

    scratch: Path | None = None
    try:
        scratch = Path(tempfile.mkdtemp(prefix="ember-sentinel-probe-"))
        scratch_root = scratch / "repo"
        shutil.copytree(root, scratch_root, ignore=_probe_copy_ignore)
    except OSError as exc:
        if scratch is not None:
            shutil.rmtree(scratch, ignore_errors=True)
        return check(
            "weak",
            f"{launcher.name}: could not stage a scratch copy for the probe "
            f"({exc}) -- an environment that cannot run this candidate has "
            "not told us the launcher is bad",
        )

    try:
        rel_launcher = launcher.relative_to(root)
        rel_entry = entry_file.relative_to(root)
    except ValueError as exc:
        shutil.rmtree(scratch, ignore_errors=True)
        return check("weak", f"{launcher.name}: {exc}")

    scratch_launcher = scratch_root / rel_launcher
    scratch_entry = scratch_root / rel_entry
    sentinel_runtime = scratch / "_sentinel_runtime.cmd"
    entry_marker = scratch / ENTRY_MARKER_NAME
    runtime_marker = scratch / RUNTIME_MARKER_NAME

    try:
        scratch_entry.parent.mkdir(parents=True, exist_ok=True)
        scratch_entry.write_text(stub, encoding="utf-8")
        sentinel_runtime.write_text(_SENTINEL_RUNTIME_STUB, encoding="utf-8")
        # Skip any real dependency install a genuine launcher chain might
        # attempt -- a network-touching probe is refused by the rails
        # regardless of what it would have found.
        dummy_react = scratch_root / "tools/ember-cli/src/node_modules/react/package.json"
        dummy_react.parent.mkdir(parents=True, exist_ok=True)
        dummy_react.write_text('{"name":"react","version":"0.0.0-probe-stub"}\n', encoding="utf-8")
    except OSError as exc:
        shutil.rmtree(scratch, ignore_errors=True)
        return check(
            "weak",
            f"{launcher.name}: could not write the sentinel stub ({exc}) -- "
            "an environment that cannot run this candidate has not told us "
            "the launcher is bad",
        )

    argv = runner_fn(scratch_launcher)
    env = dict(os.environ)
    env["EMBER_PROBE_ENTRY_MARKER"] = str(entry_marker)
    env["EMBER_PROBE_RUNTIME_MARKER"] = str(runtime_marker)
    env["EMBER_LAUNCH_NONINTERACTIVE"] = "1"
    env["EMBER_LAUNCH_TEST_MODE"] = "1"
    env["EMBER_LAUNCH_TEST_RUNTIME"] = str(sentinel_runtime)
    # Blackhole any accidental outbound call rather than trust every launcher
    # shape to skip it -- "no network" is a hard rail on the probe itself,
    # not just an expectation of what the dependency short-circuit prevents.
    env["HTTP_PROXY"] = "http://127.0.0.1:1"
    env["HTTPS_PROXY"] = "http://127.0.0.1:1"
    env["NO_COLOR"] = "1"

    receipt: dict = {
        "launcher": str(rel_launcher),
        "cli_entry": str(rel_entry),
        "cli_entry_bin_rel": entry_bin_rel,
        "entry_sentinel_stub_bytes": stub,
        "runtime_sentinel_stub_bytes": _SENTINEL_RUNTIME_STUB,
        "cwd": str(scratch_root),
        "argv": argv,
        "timeout_s": SENTINEL_TIMEOUT_SECONDS,
    }

    try:
        proc = subprocess.run(
            argv,
            cwd=str(scratch_root),
            env=env,
            capture_output=True,
            timeout=SENTINEL_TIMEOUT_SECONDS,
            text=True,
            errors="replace",
        )
        receipt["exit_code"] = proc.returncode
        receipt["timed_out"] = False
        receipt["stdout_tail"] = (proc.stdout or "")[-400:]
        receipt["stderr_tail"] = (proc.stderr or "")[-400:]
    except subprocess.TimeoutExpired as exc:
        receipt["exit_code"] = None
        receipt["timed_out"] = True
        receipt["stdout_tail"] = (exc.stdout or "")[-400:] if exc.stdout else ""
        receipt["stderr_tail"] = (exc.stderr or "")[-400:] if exc.stderr else ""
    except OSError as exc:
        shutil.rmtree(scratch, ignore_errors=True)
        return check(
            "weak",
            f"{launcher.name}: probe could not execute -- {argv[0]} unavailable "
            f"or launch failed in this environment ({exc}); an environment "
            "that could not run it has not told us the launcher is bad",
        )

    entry_fired = entry_marker.exists()
    # Diagnostic colour only, from here down -- read and recorded for a
    # human's benefit, never consulted for the verdict.
    runtime_argv_line: str | None = None
    if runtime_marker.exists():
        try:
            runtime_argv_line = runtime_marker.read_text(
                encoding="utf-8", errors="replace"
            ).strip()
        except OSError:
            runtime_argv_line = "(unreadable)"

    # Round 7: firing is not enough -- the entry stub also reports its OWN
    # resolved path, from inside the executing process (never a value
    # supplied by the caller), and the verdict requires that path to match
    # the scratch tree's actual CLI entry. This is the same category of
    # evidence as the fire itself (the process reporting its own identity),
    # not a text rule about the launcher.
    entry_marker_path_matches = False
    expected_entry_resolved = str(scratch_entry.resolve())
    if entry_fired:
        try:
            receipt["entry_marker_content"] = entry_marker.read_text(
                encoding="utf-8", errors="replace"
            ).strip()
        except OSError:
            receipt["entry_marker_content"] = "(unreadable)"
        recorded = receipt.get("entry_marker_content", "")
        try:
            entry_marker_path_matches = (
                bool(recorded) and str(Path(recorded).resolve()) == expected_entry_resolved
            )
        except (OSError, ValueError):
            entry_marker_path_matches = False
        receipt["entry_marker_path_matches_declared_entry"] = entry_marker_path_matches
        receipt["expected_entry_path"] = expected_entry_resolved
    if runtime_argv_line is not None:
        receipt["runtime_marker_argv_DIAGNOSTIC_ONLY_NOT_VERDICT_BEARING"] = runtime_argv_line

    shutil.rmtree(scratch, ignore_errors=True)

    if entry_fired and entry_marker_path_matches:
        return {
            "state": "resolved-true",
            "evidence": (
                f"{launcher.name}: executed for real under a {SENTINEL_TIMEOUT_SECONDS}s "
                f"timeout in a scratch copy; the CLI entry's OWN substituted "
                f"bytes ({rel_entry}) executed FROM THEIR OWN DECLARED LOCATION "
                "(the executing process's own reported path matches the scratch "
                "tree's actual CLI entry) and wrote the entry marker -- direct "
                "execution, in place, observed"
            ),
            "receipt": receipt,
        }

    if entry_fired and not entry_marker_path_matches:
        return {
            "state": "resolved-false",
            "evidence": (
                f"{launcher.name}: executed for real under a {SENTINEL_TIMEOUT_SECONDS}s "
                f"timeout in a scratch copy; the entry marker fired, but the "
                f"executing process reported its own path as "
                f"{receipt.get('entry_marker_content')!r}, which does not resolve "
                f"to the CLI entry's declared location ({expected_entry_resolved}) "
                "-- the entry's bytes executed from a different location (e.g. "
                "copied out of the tree and run from there), so the launcher did "
                "not invoke the CLI in place"
            ),
            "receipt": receipt,
        }

    kind = "timed out" if receipt["timed_out"] else f"exited {receipt['exit_code']}"
    runtime_note = (
        f"the substituted runtime WAS invoked (recorded argv: {runtime_argv_line!r}, "
        "diagnostic only) but never executed the CLI entry's own bytes"
        if runtime_argv_line is not None
        else "the substituted runtime was never invoked at all"
    )
    return {
        "state": "resolved-false",
        "evidence": (
            f"{launcher.name}: executed for real under a {SENTINEL_TIMEOUT_SECONDS}s "
            f"timeout in a scratch copy; the probe {kind}, and the entry marker "
            f"never fired -- {runtime_note}"
        ),
        "receipt": receipt,
    }


# --- L3 command-registry import-graph resolution ------------------------


def _extract_bracket_body(text: str, anchor: str) -> str | None:
    idx = text.find(anchor)
    if idx == -1:
        return None
    start = idx + len(anchor) - 1  # position of the '[' itself
    if text[start] != "[":
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "[":
            depth += 1
        elif text[i] == "]":
            depth -= 1
            if depth == 0:
                return text[start + 1 : i]
    return None


def load_registered_stems(root: Path) -> tuple[set[str], list[str]]:
    """Walk command-registry.ts's own import graph to find which command
    modules are ACTUALLY imported and called from getBuiltinCommands(). A
    module's own text is never evidence of its own registration -- only
    this graph is."""
    errors: list[str] = []
    reg_path = root / COMMAND_REGISTRY
    try:
        text = reg_path.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeError) as exc:
        errors.append(f"command registry unreadable: {COMMAND_REGISTRY} ({exc})")
        return set(), errors

    import_re = re.compile(
        r"^import\s+(type\s+)?\{([^}]+)\}\s+from\s+['\"](\.[^'\"]+)['\"]",
        re.MULTILINE,
    )
    # Local identifier -> every rel_path it is bound to. A local name bound
    # to more than one DISTINCT path is a duplicate import binding, which is
    # invalid TypeScript and would fail to compile as-shipped -- but the
    # harness reads bytes, not a build result, so it does not get to assume
    # that. Round-3 probe finding: last-write-wins credited a later decoy
    # import over the real one for the same call site. Round-3 fix: any
    # identifier with more than one distinct binding is excluded entirely --
    # neither path is credited, rather than guessing which one a compiler
    # would have picked.
    ident_bindings: dict[str, set[str]] = {}
    for m in import_re.finditer(text):
        is_type_only = bool(m.group(1))
        if is_type_only:
            continue
        rel_path = m.group(3)
        for raw_ident in m.group(2).split(","):
            raw_ident = raw_ident.strip()
            if not raw_ident:
                continue
            local_name = raw_ident.split(" as ")[-1].strip()
            if local_name:
                ident_bindings.setdefault(local_name, set()).add(rel_path)

    ident_to_path: dict[str, str] = {}
    for local_name, paths in ident_bindings.items():
        if len(paths) == 1:
            ident_to_path[local_name] = next(iter(paths))
        else:
            errors.append(
                f"{local_name} is imported from {len(paths)} distinct paths in "
                f"{COMMAND_REGISTRY} ({sorted(paths)}) -- invalid as shipped "
                "TypeScript, so neither binding is credited"
            )

    array_body = _extract_bracket_body(text, "getBuiltinCommands: () => [")
    if array_body is None:
        errors.append(
            f"command registry has no getBuiltinCommands: () => [ ... ] array "
            f"in {COMMAND_REGISTRY}; treating the registered set as empty"
        )
        return set(), errors

    called_idents = set(re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", array_body))

    registered_stems: set[str] = set()
    for ident in called_idents:
        rel_path = ident_to_path.get(ident)
        if not rel_path:
            continue
        norm_rel = rel_path.replace("\\", "/")
        # Only stems under COMMANDS_DIR are meaningful to the SPINE_FUNCTIONS
        # scan below, which only globs that directory.
        if "/commands/" in ("/" + norm_rel):
            registered_stems.add(Path(rel_path).stem)

    if not registered_stems:
        errors.append(
            f"getBuiltinCommands() in {COMMAND_REGISTRY} calls no import that "
            f"resolves under {COMMANDS_DIR}; registered set is empty"
        )
    return registered_stems, errors


def load_commands(root: Path) -> tuple[dict[str, dict], list[str]]:
    """Return {module_stem: {names:[], has_description:bool, body:str}}, errors."""
    errors: list[str] = []
    cmd_dir = root / COMMANDS_DIR
    if not cmd_dir.is_dir():
        errors.append(f"command registry missing: {COMMANDS_DIR}")
        return {}, errors
    modules: dict[str, dict] = {}
    for f in sorted(cmd_dir.glob("*.ts")):
        if f.name.endswith(".test.ts"):
            continue
        try:
            body = f.read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeError) as exc:
            errors.append(f"unreadable command module {f.name}: {exc}")
            continue
        names = NAME_RE.findall(body)
        modules[f.stem] = {
            "names": names,
            "has_description": bool(DESC_RE.search(body)),
            "desc_lower": " ".join(DESC_TEXT_RE.findall(body)).lower(),
            "body_lower": body.lower(),
        }
    if not modules:
        errors.append(f"command registry empty: {COMMANDS_DIR}")
    return modules, errors


def run(root: Path) -> dict:
    report: dict = {"root": str(root), "checks": {}, "spine": {}, "undecidable": []}
    checks = report["checks"]

    # L1 root launcher -- runtime-sentinel-bound, never text-bound ---------
    # Round 4: the static walk below (`resolve_invocation`) is kept as a
    # pre-filter/diagnostic ONLY. It may narrow or refuse; it may never grant
    # resolved-true on its own -- that authority belongs to
    # `run_sentinel_probe` alone, which actually executes the candidate and
    # observes whether an owned sentinel fires. See the "Round 4" block above
    # `run_sentinel_probe` for why (an independent probe defeated round
    # 3.1's grammar with `type "tools\ember-cli\src\main.ts"`, one instance
    # of the open-ended "non-invoking mention" class -- exclusion lists over
    # that class have no boundary).
    candidates = find_root_launcher_candidates(root)
    static_resolutions = {c: resolve_invocation(c, root) for c in candidates}
    probes = {c: run_sentinel_probe(c, root) for c in candidates}

    def _final_state(c: Path) -> str:
        p = probes[c]["state"]
        return p if p in ("resolved-true", "weak") else "resolved-false"

    launchers_true = [c for c in candidates if _final_state(c) == "resolved-true"]
    launchers_weak = [c for c in candidates if _final_state(c) == "weak"]

    def _combined_evidence(c: Path) -> str:
        return (
            f"static pre-filter: {static_resolutions[c]['evidence']} || "
            f"RUNTIME PROBE (authoritative): {probes[c]['evidence']}"
        )

    if launchers_true:
        checks["L1_root_launcher"] = check(
            "resolved-true", "; ".join(_combined_evidence(c) for c in launchers_true)
        )
        checks["L1_root_launcher"]["receipts"] = {
            str(c.name): probes[c]["receipt"] for c in launchers_true
        }
    elif launchers_weak:
        checks["L1_root_launcher"] = check(
            "weak",
            "candidate root launcher(s) exist but the runtime probe could not "
            "resolve them: " + "; ".join(_combined_evidence(c) for c in launchers_weak),
        )
    elif candidates:
        checks["L1_root_launcher"] = check(
            "resolved-false", "; ".join(_combined_evidence(c) for c in candidates)
        )
    else:
        checks["L1_root_launcher"] = check(
            "resolved-false",
            "no .cmd/.bat/.ps1/.exe/.sh or executable-named file at repo root",
        )

    # package.json fail-closed parse (evidence for the L1 verdict) --------
    pkg_path = root / PACKAGE_JSON
    try:
        pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
        bin_entry = pkg.get("bin")
        if not isinstance(bin_entry, dict) or not bin_entry:
            checks["L1b_package_bin"] = check(
                "resolved-false", f"{PACKAGE_JSON}: bin entry missing/empty"
            )
        else:
            checks["L1b_package_bin"] = check(
                "resolved-true", f"bin = {bin_entry} (informational; a .ts bin "
                "target is NOT a no-source launcher)"
            )
    except (OSError, json.JSONDecodeError, UnicodeError) as exc:
        checks["L1b_package_bin"] = check(
            "resolved-false", f"{PACKAGE_JSON} missing/unparseable: {exc}"
        )

    # L2 launcher documented -- only a REAL (resolved-true) launcher counts
    if launchers_true:
        doc_hits = []
        for rel in DOC_FILES:
            fp = root / rel
            try:
                text = fp.read_text(encoding="utf-8", errors="strict")
            except (OSError, UnicodeError):
                continue
            for launcher in launchers_true:
                if launcher.name in text:
                    doc_hits.append(f"{rel} mentions {launcher.name}")
        if doc_hits:
            checks["L2_launcher_documented"] = check("resolved-true", "; ".join(doc_hits))
        else:
            checks["L2_launcher_documented"] = check(
                "resolved-false",
                f"resolved launcher(s) {[c.name for c in launchers_true]} named in "
                "neither " + " nor ".join(DOC_FILES)
                + " -- an undocumented launcher is undiscoverable",
            )
    else:
        checks["L2_launcher_documented"] = check(
            "resolved-false", "no launcher resolved to the CLI entry (see L1)"
        )

    # L3 spine-function command surface -- registry-graph bound -----------
    modules, cmd_errors = load_commands(root)
    registered_stems, registry_errors = load_registered_stems(root)
    for err in cmd_errors + registry_errors:
        checks.setdefault("L3_registry_errors", check("resolved-false", err))
    launch_ok = checks["L1_root_launcher"]["state"] == "resolved-true"
    registered_modules = {
        stem: m for stem, m in modules.items() if stem in registered_stems
    }
    unregistered_stems = sorted(set(modules) - registered_stems)

    for func, keywords in SPINE_FUNCTIONS.items():
        require_all = func in CONJUNCTION_FUNCTIONS
        hit = None
        weak = False
        ambiguous = False
        orphan_note = ""
        # Pass 1 (STRONG): keyword(s) in the command NAME or its declared
        # DESCRIPTION -- the two things a reader with no source can actually
        # see -- of a module command-registry.ts actually registers.
        #
        # Ambiguity fix (2026-07-25, near-miss incident: a one-line
        # description edit made custody.ts win the checkpoint_save_load row
        # on alphabetical dict-iteration first-match, reassigning the row to
        # a command that only displays identity read-only). Every satisfying
        # registered module is collected, not just the first one iteration
        # order happens to reach. More than one match is a DEFECT, not a
        # tiebreak: the STRONG pass has no scoring signal at all (a keyword
        # either appears in a module's name+description or it does not), so
        # there is no principled "strongest evidence" to credit here --
        # inventing one would just be a different arbitrary guess replacing
        # the alphabetical one. The row refuses resolved-true and names
        # every competing module until the collision is resolved by hand
        # (narrowing the keyword, or rewording the losing description).
        strong_matches: list[str] = []
        for stem, m in registered_modules.items():
            if not m["names"] or not m["has_description"]:
                continue
            hay = " ".join(m["names"]) + " " + m["desc_lower"]
            matched = [k for k in keywords if keyword_in(k, hay)]
            satisfied = (len(matched) == len(keywords)) if require_all else bool(matched)
            if satisfied:
                strong_matches.append(stem)
        if len(strong_matches) > 1:
            ambiguous = True
            named = ", ".join(f"{s}.ts" for s in sorted(strong_matches))
            hit = (
                f"AMBIGUOUS: {len(strong_matches)} registered, named+described "
                f"modules all match {keywords}: [{named}] -- refusing to "
                "resolve true; narrow the keyword or reword the losing "
                "module's name/description so only one module matches"
            )
        elif len(strong_matches) == 1:
            stem = strong_matches[0]
            m = registered_modules[stem]
            hit = f"command {m['names']} in {stem}.ts (named + described, registered)"
        if hit is None:
            # WEAK pass. Report EVERY registered module whose body mentions a
            # keyword, ranked by hit count -- never an arbitrary first match.
            ranked: list[tuple[int, str, list[str]]] = []
            for stem, m in registered_modules.items():
                if not m["names"] or not m["has_description"]:
                    continue
                hay = stem.lower() + " " + m["body_lower"]
                matched = [k for k in keywords if keyword_in(k, hay)]
                if matched:
                    n = sum(keyword_count(k, hay) for k in matched)
                    label = ""
                    if require_all and len(matched) < len(keywords):
                        missing = [k for k in keywords if k not in matched]
                        label = f" [half-concept, missing {missing}]"
                    ranked.append((n, f"{stem}.ts ({m['names']}){label}", matched))
            orphan_note = ""
            if unregistered_stems:
                orphan_hits = [
                    s
                    for s in unregistered_stems
                    if any(keyword_in(k, modules[s]["body_lower"]) for k in keywords)
                ]
                if orphan_hits:
                    orphan_note = (
                        f"; {len(orphan_hits)} unregistered module(s) also match by "
                        f"keyword but carry no evidence (not imported by "
                        f"{COMMAND_REGISTRY}): {orphan_hits[:4]}"
                    )
            if ranked:
                ranked.sort(key=lambda r: (-r[0], r[1]))
                where = "; ".join(f"{name} x{n} {ks}" for n, name, ks in ranked[:4])
                hit = (
                    f"implemented in registered module bodies [{where}] but no "
                    f"registered command's name or declared description says so "
                    f"-- undiscoverable without reading the source. Clears when a "
                    f"declared description names it." + orphan_note
                )
                weak = True
            elif orphan_note:
                # No registered module matches at all -- only unregistered
                # ones do. That is not "weak" (a registered-but-undiscoverable
                # capability); it is a row an unregistered module can never
                # satisfy. Report it as a plain miss, with the orphan noted
                # as diagnostic evidence only -- never as a match.
                hit = None
        if ambiguous:
            report["spine"][func] = check("ambiguous", hit)
        elif weak:
            report["spine"][func] = check("weak", hit)
        elif hit is None:
            report["spine"][func] = check(
                "resolved-false",
                f"no registered, named+described command module matches {keywords}"
                + orphan_note,
            )
        elif not launch_ok:
            report["spine"][func] = check(
                "resolved-false",
                f"{hit} -- exists in the body, but the body itself is "
                "unreachable without source knowledge (L1 failed), so a "
                "no-source operator cannot reach it",
            )
        else:
            report["spine"][func] = check("resolved-true", hit)

    # Permanently undecidable half ----------------------------------------
    report["undecidable"] = [
        "UI affordance visibility: does each command render as a visible "
        "menu/palette item in the running cockpit? (human capture required)",
        "Interaction cost: is each control one click / one keystroke, with "
        "no typed flags? (human capture required)",
        "Launch experience: does the launcher reach a usable first pixel "
        "without prompts for paths/flags? (human capture required)",
    ]

    gating = list(checks.values()) + list(report["spine"].values())
    report["verdict"] = (
        "PASS (measurable half only; undecidable items remain human-judged)"
        if all(c["state"] == "resolved-true" for c in gating)
        else "FAIL"
    )
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--json", action="store_true", help="emit machine JSON only")
    args = ap.parse_args()
    root = Path(args.root)
    if not root.is_dir():
        print(f"FAIL: root not a directory: {root}", file=sys.stderr)
        return 1
    try:
        assert_ember_root(root)
        report = run(root)
    except RuntimeError as exc:
        # Exit 2, not 1: a harness that cannot identify its target has produced
        # no verdict about ember at all, and must not be mistaken for a FAIL.
        print(f"HARNESS ERROR (fail-closed): {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"no-source operability verdict: {report['verdict']}")
        for k, c in report["checks"].items():
            print(f"  [{c['state']:>14}] {k}: {c['evidence']}")
        print("  spine functions:")
        for k, c in report["spine"].items():
            print(f"  [{c['state']:>14}] {k}: {c['evidence']}")
        print("  undecidable (human capture required):")
        for u in report["undecidable"]:
            print(f"    - {u}")
    return 0 if report["verdict"].startswith("PASS") else 1


if __name__ == "__main__":
    sys.exit(main())
