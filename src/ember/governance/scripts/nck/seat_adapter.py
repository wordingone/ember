#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""sp-6c seat adapter — frozen prompt template + output grammar + parser (#307).

The B3 instrument's seat-facing half: binds ANY text-generation backend into
the replay rig's core interface so both seats (ember core, Gemma E2B) receive
byte-identical prompts per episode and are scored by one deterministic parser.

Contract (frozen; docs/domains/governance/archive/pre-restart/sp6c-seat-adapter-v0.md):
- build_prompt(event, sandbox_dir) -> str: deterministic, machine-invariant.
  Sandbox absolute paths are reverse-substituted to '{root}' so the prompt is
  identical across runs/machines (replay-identical rule, fp33 prereg B3).
  World state = a sorted listing of sandbox files with size, age_s relative
  to REPLAY_EPOCH, and verbatim content (fixtures are {root}-templated on
  disk already).
- parse_actions(text, sandbox_dir) -> list[Action]: closed grammar, one
  action per conforming line; non-conforming lines are IGNORED (silence by
  default); unknown verbs ignored; at most MAX_ACTIONS_PER_EVENT actions.
  '{root}' in arg values is substituted with sandbox_dir so the rig's target
  normalization sees real sandbox paths.
- make_seat_core(generate_fn) -> core(event, registry, sandbox_dir): the
  3-arg core protocol the rig dispatches when the core declares a third
  positional parameter. generate_fn: Callable[[str], str], MUST be
  deterministic (greedy decode) — the model-binding half is the engineer
  lane; this module never loads a model.
- TEMPLATE_HASH: sha256 over every frozen text constant. Recorded in every
  B-run receipt; the selftest pins it, so any template edit is a visible
  diff against the pinned literal (registered-deviation semantics).

Post-freeze edits to the frozen constants are fp-30b-class registered
deviations; after the first B-run they void that run.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Callable

try:
    from nck.event_loop import Event, Action
    from nck.replay_rig import REPLAY_EPOCH
except ImportError:  # direct-script import fallback, same style as the rig
    # issue2015 exact-local-import:src/ember/governance/scripts/nck/event_loop.py
    import importlib.util as _ember_a1f9d0d912b78a85_importlib
    import sys as _ember_a1f9d0d912b78a85_sys
    from pathlib import Path as _ember_a1f9d0d912b78a85_Path
    _ember_a1f9d0d912b78a85_path = _ember_a1f9d0d912b78a85_Path(__file__).resolve().parents[5].joinpath('src', 'ember', 'governance', 'scripts', 'nck', 'event_loop.py')
    if not _ember_a1f9d0d912b78a85_path.is_file():
        raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/nck/event_loop.py')
    _ember_a1f9d0d912b78a85_aliases = ('_ember_issue2015_a1f9d0d912b78a85', 'event_loop', 'scripts.nck.event_loop')
    _ember_a1f9d0d912b78a85_existing = []
    for _ember_a1f9d0d912b78a85_alias in _ember_a1f9d0d912b78a85_aliases:
        _ember_a1f9d0d912b78a85_candidate = _ember_a1f9d0d912b78a85_sys.modules.get(_ember_a1f9d0d912b78a85_alias)
        if _ember_a1f9d0d912b78a85_candidate is not None and all(_ember_a1f9d0d912b78a85_candidate is not item for item in _ember_a1f9d0d912b78a85_existing):
            _ember_a1f9d0d912b78a85_existing.append(_ember_a1f9d0d912b78a85_candidate)
    if len(_ember_a1f9d0d912b78a85_existing) > 1:
        raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/nck/event_loop.py')
    if _ember_a1f9d0d912b78a85_existing:
        _ember_a1f9d0d912b78a85_module = _ember_a1f9d0d912b78a85_existing[0]
        _ember_a1f9d0d912b78a85_observed = getattr(_ember_a1f9d0d912b78a85_module, '__file__', None)
        if _ember_a1f9d0d912b78a85_observed is None or _ember_a1f9d0d912b78a85_Path(_ember_a1f9d0d912b78a85_observed).resolve() != _ember_a1f9d0d912b78a85_path:
            raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/nck/event_loop.py')
    else:
        _ember_a1f9d0d912b78a85_spec = _ember_a1f9d0d912b78a85_importlib.spec_from_file_location('_ember_issue2015_a1f9d0d912b78a85', _ember_a1f9d0d912b78a85_path)
        if _ember_a1f9d0d912b78a85_spec is None or _ember_a1f9d0d912b78a85_spec.loader is None:
            raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/nck/event_loop.py')
        _ember_a1f9d0d912b78a85_module = _ember_a1f9d0d912b78a85_importlib.module_from_spec(_ember_a1f9d0d912b78a85_spec)
        for _ember_a1f9d0d912b78a85_alias in _ember_a1f9d0d912b78a85_aliases:
            _ember_a1f9d0d912b78a85_prior = _ember_a1f9d0d912b78a85_sys.modules.get(_ember_a1f9d0d912b78a85_alias)
            if _ember_a1f9d0d912b78a85_prior is not None and _ember_a1f9d0d912b78a85_prior is not _ember_a1f9d0d912b78a85_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/nck/event_loop.py')
            _ember_a1f9d0d912b78a85_sys.modules[_ember_a1f9d0d912b78a85_alias] = _ember_a1f9d0d912b78a85_module
        try:
            _ember_a1f9d0d912b78a85_spec.loader.exec_module(_ember_a1f9d0d912b78a85_module)
        except BaseException:
            for _ember_a1f9d0d912b78a85_alias in _ember_a1f9d0d912b78a85_aliases:
                if _ember_a1f9d0d912b78a85_sys.modules.get(_ember_a1f9d0d912b78a85_alias) is _ember_a1f9d0d912b78a85_module:
                    _ember_a1f9d0d912b78a85_sys.modules.pop(_ember_a1f9d0d912b78a85_alias, None)
            raise
    for _ember_a1f9d0d912b78a85_alias in _ember_a1f9d0d912b78a85_aliases:
        _ember_a1f9d0d912b78a85_prior = _ember_a1f9d0d912b78a85_sys.modules.get(_ember_a1f9d0d912b78a85_alias)
        if _ember_a1f9d0d912b78a85_prior is not None and _ember_a1f9d0d912b78a85_prior is not _ember_a1f9d0d912b78a85_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/nck/event_loop.py')
        _ember_a1f9d0d912b78a85_sys.modules[_ember_a1f9d0d912b78a85_alias] = _ember_a1f9d0d912b78a85_module
    Event = getattr(_ember_a1f9d0d912b78a85_module, 'Event')
    Action = getattr(_ember_a1f9d0d912b78a85_module, 'Action')
    # issue2015 exact-local-import-end:src/ember/governance/scripts/nck/event_loop.py  # type: ignore[no-redef]
    # issue2015 exact-local-import:src/ember/governance/scripts/nck/replay_rig.py
    import importlib.util as _ember_3f61c7f9cf27fed5_importlib
    import sys as _ember_3f61c7f9cf27fed5_sys
    from pathlib import Path as _ember_3f61c7f9cf27fed5_Path
    _ember_3f61c7f9cf27fed5_path = _ember_3f61c7f9cf27fed5_Path(__file__).resolve().parents[5].joinpath('src', 'ember', 'governance', 'scripts', 'nck', 'replay_rig.py')
    if not _ember_3f61c7f9cf27fed5_path.is_file():
        raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/nck/replay_rig.py')
    _ember_3f61c7f9cf27fed5_aliases = ('_ember_issue2015_3f61c7f9cf27fed5', 'replay_rig', 'scripts.nck.replay_rig')
    _ember_3f61c7f9cf27fed5_existing = []
    for _ember_3f61c7f9cf27fed5_alias in _ember_3f61c7f9cf27fed5_aliases:
        _ember_3f61c7f9cf27fed5_candidate = _ember_3f61c7f9cf27fed5_sys.modules.get(_ember_3f61c7f9cf27fed5_alias)
        if _ember_3f61c7f9cf27fed5_candidate is not None and all(_ember_3f61c7f9cf27fed5_candidate is not item for item in _ember_3f61c7f9cf27fed5_existing):
            _ember_3f61c7f9cf27fed5_existing.append(_ember_3f61c7f9cf27fed5_candidate)
    if len(_ember_3f61c7f9cf27fed5_existing) > 1:
        raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/nck/replay_rig.py')
    if _ember_3f61c7f9cf27fed5_existing:
        _ember_3f61c7f9cf27fed5_module = _ember_3f61c7f9cf27fed5_existing[0]
        _ember_3f61c7f9cf27fed5_observed = getattr(_ember_3f61c7f9cf27fed5_module, '__file__', None)
        if _ember_3f61c7f9cf27fed5_observed is None or _ember_3f61c7f9cf27fed5_Path(_ember_3f61c7f9cf27fed5_observed).resolve() != _ember_3f61c7f9cf27fed5_path:
            raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/nck/replay_rig.py')
    else:
        _ember_3f61c7f9cf27fed5_spec = _ember_3f61c7f9cf27fed5_importlib.spec_from_file_location('_ember_issue2015_3f61c7f9cf27fed5', _ember_3f61c7f9cf27fed5_path)
        if _ember_3f61c7f9cf27fed5_spec is None or _ember_3f61c7f9cf27fed5_spec.loader is None:
            raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/nck/replay_rig.py')
        _ember_3f61c7f9cf27fed5_module = _ember_3f61c7f9cf27fed5_importlib.module_from_spec(_ember_3f61c7f9cf27fed5_spec)
        for _ember_3f61c7f9cf27fed5_alias in _ember_3f61c7f9cf27fed5_aliases:
            _ember_3f61c7f9cf27fed5_prior = _ember_3f61c7f9cf27fed5_sys.modules.get(_ember_3f61c7f9cf27fed5_alias)
            if _ember_3f61c7f9cf27fed5_prior is not None and _ember_3f61c7f9cf27fed5_prior is not _ember_3f61c7f9cf27fed5_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/nck/replay_rig.py')
            _ember_3f61c7f9cf27fed5_sys.modules[_ember_3f61c7f9cf27fed5_alias] = _ember_3f61c7f9cf27fed5_module
        try:
            _ember_3f61c7f9cf27fed5_spec.loader.exec_module(_ember_3f61c7f9cf27fed5_module)
        except BaseException:
            for _ember_3f61c7f9cf27fed5_alias in _ember_3f61c7f9cf27fed5_aliases:
                if _ember_3f61c7f9cf27fed5_sys.modules.get(_ember_3f61c7f9cf27fed5_alias) is _ember_3f61c7f9cf27fed5_module:
                    _ember_3f61c7f9cf27fed5_sys.modules.pop(_ember_3f61c7f9cf27fed5_alias, None)
            raise
    for _ember_3f61c7f9cf27fed5_alias in _ember_3f61c7f9cf27fed5_aliases:
        _ember_3f61c7f9cf27fed5_prior = _ember_3f61c7f9cf27fed5_sys.modules.get(_ember_3f61c7f9cf27fed5_alias)
        if _ember_3f61c7f9cf27fed5_prior is not None and _ember_3f61c7f9cf27fed5_prior is not _ember_3f61c7f9cf27fed5_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/nck/replay_rig.py')
        _ember_3f61c7f9cf27fed5_sys.modules[_ember_3f61c7f9cf27fed5_alias] = _ember_3f61c7f9cf27fed5_module
    REPLAY_EPOCH = getattr(_ember_3f61c7f9cf27fed5_module, 'REPLAY_EPOCH')
    # issue2015 exact-local-import-end:src/ember/governance/scripts/nck/replay_rig.py  # type: ignore[no-redef]


class SeatRefuse(Exception):
    """Raised when the adapter detects a contract violation."""


# ---------------------------------------------------------------------------
# Frozen constants — every byte below feeds TEMPLATE_HASH
# ---------------------------------------------------------------------------

PROMPT_VERSION = "nck-seat-prompt-v1"

# The 18-verb closed enum (sp-6 battery contract).
VERB_ENUM: frozenset[str] = frozenset({
    "reply", "ack-begin", "challenge", "no-action", "clarify",
    "gate-pass", "gate-fail", "dedup", "escalate",
    "execute-due", "heartbeat-only", "monitor", "gate-then-next",
    "clear-lock", "repair-escalate", "flag-missing", "report", "clean",
})

# Identity + norms only. Deliberately NO per-family decision table: the
# grammar makes every action EXPRESSIBLE for both seats; knowing WHEN to act
# is the measured variable (founder-likeness), not given away in the prompt.
SYSTEM_PREAMBLE = """\
You are the resident duty core of an autonomous agent harness (NC-K).
Events arrive from four sources: mail, schedule, job_receipt, file_watch.
For each event you decide what duty, if any, it creates — then act, or stay
silent.

Operating norms:
- Receipts-only truth: claims are checked against world state, never taken
  from prose.
- Fail-closed: missing or unparseable load-bearing state is surfaced, never
  papered over.
- Cost discipline: outward messages only when a duty requires one. Silence
  is a valid and often correct response.
- Policy bars, when applicable, live in config/replay-policy.json in world
  state.
"""

# Verb table: WHAT each verb is, not WHEN to use it. to= verbs are
# mail-directed; path= verbs are file-directed; silence verbs are expressed
# by emitting no ACTION lines at all.
GRAMMAR_SPEC = """\
Emit zero or more action lines, one action per line, exactly:
ACTION: <verb> | to=<recipient>
ACTION: <verb> | path=<path>
Any line not conforming to this grammar is ignored. No conforming ACTION
line means silence.

Mail-directed verbs (use to=<the sender's name from the event payload>, or
to=owner for the harness owner):
  reply            answer a mail
  ack-begin        acknowledge an assignment and begin it
  challenge        dispute a claim
  clarify          surface a conflict and ask which instruction holds
  escalate         raise a blocker to the owner (to=owner)
  report           send a measured number to the owner (to=owner)
  flag-missing     report an absent artifact to the owner (to=owner)
  repair-escalate  report corrupt/unrepairable state to the owner (to=owner)

File-directed verbs (use path=<{root}-templated or sandbox path>):
  gate-pass        record a passing gate verdict for a receipt
  gate-fail        record a failing gate verdict for a receipt
  execute-due      execute the due scheduled item (path=its target)
  monitor          record status of a running job (path=its status file)
  clear-lock       remove a stale lock file
  gate-then-next   gate a terminal receipt and launch its named successor

Silence verbs (correct expression is NO action line): no-action,
heartbeat-only, dedup, clean.
"""

# Frame skeleton — placeholders filled by build_prompt. Part of the hash.
PROMPT_FRAME = """\
{version}

{preamble}
WORLD STATE ({{root}} = harness root):
{world}

EVENT:
source: {source}
kind: {kind}
ts: {ts}
payload:
{payload}

OUTPUT GRAMMAR:
{grammar}
Respond now.
"""

# Per-file world-state block format. Part of the hash.
FILE_BLOCK_FMT = "file: {relpath} | size={size} | age_s={age_s}\n{content}\n---"

EMPTY_WORLD = "(empty)"

# Content over this many characters is truncated (no battery fixture is
# anywhere near it; guard against pathological sandboxes).
MAX_CONTENT_CHARS = 2048

# Anti-spray cap: at most this many actions parsed per event.
MAX_ACTIONS_PER_EVENT = 4

_TEMPLATE_PARTS = (
    PROMPT_VERSION,
    SYSTEM_PREAMBLE,
    GRAMMAR_SPEC,
    PROMPT_FRAME,
    FILE_BLOCK_FMT,
    EMPTY_WORLD,
    str(MAX_CONTENT_CHARS),
    str(MAX_ACTIONS_PER_EVENT),
    "|".join(sorted(VERB_ENUM)),
)

TEMPLATE_HASH = hashlib.sha256("\x00".join(_TEMPLATE_PARTS).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def _unsubstitute_root(value: Any, sandbox_dir: str) -> Any:
    """Recursively replace sandbox_dir with the literal '{root}' in all
    string values — the exact inverse of the rig's _substitute_root, so the
    rendered prompt is machine-invariant."""
    if isinstance(value, str):
        return value.replace(sandbox_dir, "{root}") if sandbox_dir else value
    if isinstance(value, dict):
        return {k: _unsubstitute_root(v, sandbox_dir) for k, v in value.items()}
    if isinstance(value, list):
        return [_unsubstitute_root(v, sandbox_dir) for v in value]
    return value


def _render_world(sandbox_dir: str) -> str:
    """Deterministic world-state block: sorted relpaths, size, age_s vs
    REPLAY_EPOCH, verbatim content (on-disk fixtures are {root}-templated
    already). Requires the rig's pinned-mtime materialization for
    deterministic age_s."""
    if not sandbox_dir or not os.path.isdir(sandbox_dir):
        return EMPTY_WORLD
    blocks: list[str] = []
    root = Path(sandbox_dir)
    paths = sorted(
        (p for p in root.rglob("*") if p.is_file()),
        key=lambda p: p.relative_to(root).as_posix(),
    )
    for p in paths:
        rel = p.relative_to(root).as_posix()
        stat = p.stat()
        age_s = int(round(REPLAY_EPOCH - stat.st_mtime))
        content = p.read_text(encoding="utf-8", errors="replace")
        if len(content) > MAX_CONTENT_CHARS:
            content = content[:MAX_CONTENT_CHARS] + "...[truncated]"
        blocks.append(FILE_BLOCK_FMT.format(
            relpath=rel, size=stat.st_size, age_s=age_s, content=content,
        ))
    return "\n".join(blocks) if blocks else EMPTY_WORLD


def build_prompt(event: Event, sandbox_dir: str = "") -> str:
    """Render the frozen prompt for one event. Deterministic and
    machine-invariant: same episode -> byte-identical prompt regardless of
    the sandbox tempdir path or host machine."""
    payload = _unsubstitute_root(event.payload, sandbox_dir)
    payload_json = json.dumps(payload, sort_keys=True, indent=1)
    return PROMPT_FRAME.format(
        version=PROMPT_VERSION,
        preamble=SYSTEM_PREAMBLE,
        world=_render_world(sandbox_dir),
        source=event.source,
        kind=event.kind,
        ts=event.ts,
        payload=payload_json,
        grammar=GRAMMAR_SPEC,
    )


# ---------------------------------------------------------------------------
# Output parsing
# ---------------------------------------------------------------------------

_ACTION_LINE_RE = re.compile(r"^\s*ACTION:\s*([a-z][a-z-]*)\s*(\|.*)?$")
_ARG_KEY_RE = re.compile(r"^[a-z_]+$")


def parse_actions(
    text: str,
    sandbox_dir: str = "",
    event_ref: Event | None = None,
) -> list[Action]:
    """Deterministic model-text -> Action stream.

    - One action per line matching the ACTION grammar; everything else is
      ignored (unparseable text => zero actions => silence).
    - Verb must be in VERB_ENUM; non-enum verbs are ignored.
    - Args are '| key=value' segments; keys must match [a-z_]+; values are
      stripped; '{root}' in values is substituted with sandbox_dir so the
      rig's target normalization sees real sandbox paths.
    - At most MAX_ACTIONS_PER_EVENT actions; further lines are ignored.
    """
    if not isinstance(text, str):
        raise SeatRefuse(f"SEAT_PARSE_INPUT: expected str, got {type(text).__name__}")
    actions: list[Action] = []
    for line in text.splitlines():
        if len(actions) >= MAX_ACTIONS_PER_EVENT:
            break
        m = _ACTION_LINE_RE.match(line)
        if not m:
            continue
        verb = m.group(1)
        if verb not in VERB_ENUM:
            continue
        args: dict[str, Any] = {}
        rest = m.group(2) or ""
        for seg in rest.split("|"):
            seg = seg.strip()
            if not seg or "=" not in seg:
                continue
            key, val = seg.split("=", 1)
            key = key.strip()
            if not _ARG_KEY_RE.match(key):
                continue
            val = val.strip()
            if sandbox_dir:
                val = val.replace("{root}", sandbox_dir)
            args[key] = val
        actions.append(Action(verb=verb, args=args, event_ref=event_ref))
    return actions


# ---------------------------------------------------------------------------
# Seat core factory
# ---------------------------------------------------------------------------


def make_seat_core(
    generate_fn: Callable[[str], str],
) -> Callable[[Event, Any, str], list[Action]]:
    """Bind a text-generation backend into the rig's 3-arg core protocol.

    generate_fn(prompt) -> completion text. MUST be deterministic (greedy
    decode); the B-run receipt records the backend identity + decode params
    + TEMPLATE_HASH. The registry argument is accepted for protocol
    compatibility and unused: scoring is on emitted actions, not dispatch.
    """
    def seat_core(event: Event, registry: Any, sandbox_dir: str = "") -> list[Action]:
        prompt = build_prompt(event, sandbox_dir)
        completion = generate_fn(prompt)
        if not isinstance(completion, str):
            raise SeatRefuse(
                f"SEAT_GENERATE: generate_fn must return str, got "
                f"{type(completion).__name__}"
            )
        return parse_actions(completion, sandbox_dir, event_ref=event)

    return seat_core


if __name__ == "__main__":
    print(f"TEMPLATE_HASH: {TEMPLATE_HASH}")
