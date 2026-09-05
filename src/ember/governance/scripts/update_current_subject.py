#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Durable writer for manifests/ember-current-subject-v1.json (issue #2119).

``ember-current-subject-v1`` already exists as a closed-schema authority --
``gen_readme_status.load_current_subject`` reads and validates it, and
``docs/domains/governance/authority/CONTINUITY.md`` renders it -- but nothing
in this tree writes it. Every publish today requires a hand edit. This module
is the minimal extension issue #2119 asks for: a writer that reuses the
existing checkpoint identity, closed-schema validation, and atomic small-file
replace mechanisms rather than inventing a second format or a locking
primitive.

Three mechanisms, in order, on every call:

1. **Verify immutable checkpoint bytes.** ``checkpoint_manifest_sha256`` is
   never taken as the caller's claim -- it is always re-derived from the
   published checkpoint root's actual on-disk manifest bytes via
   ``checkpoint_artifacts.published_checkpoint_receipt`` (the existing
   streaming sha256, not a new one).
2. **Compare-and-swap parent pin.** The caller declares which checkpoint it
   believed was the current selected continuation head when its training run
   started (``--expected-parent-checkpoint-manifest-sha256``). If the durable
   record's own ``subject.checkpoint_manifest_sha256`` no longer equals that
   value, a newer continuation head has already been selected and this write
   is stale by construction -- it is refused before anything is touched on
   disk. This is a compare-and-swap, not a lock: matches the durable_io
   module's own stated discipline (atomicity of the final rename is the only
   concurrency primitive this tree has for small files).
3. **Pre-write round-trip validation.** The candidate payload is written to a
   temp file beside the target and validated through the reader's own
   ``gen_readme_status.load_current_subject`` before the atomic replace. A
   payload that would fail the reader's own checks is refused pre-write, and
   the target file is provably unchanged (the temp file is never promoted).

Deliberately NOT derived here: ``active_route``, ``evidence_paths``,
``checkpoint_custody``, ``disposition``, ``capability_credit``,
``sufficient_pretraining_proven``, and the ``parameters``/``token_cursor``
counts. ``load_current_subject``'s own checks pin these to specific literal
values and relationships (e.g. ``disposition`` must be exactly
``"CHECKPOINT_CANDIDATE_NOT_ADMITTED"``, ``predecessor.relationship`` must be
exactly ``"historical_step1_predecessor"``) that this script has no principled
way to derive from checkpoint bytes alone -- they are declarations the caller
makes about the run, not measurements this script can take. Real-path-closure
boundary honesty: inventing a derivation for them here, unproven against a
real training-loop consumer, would be a bigger and riskier change than issue
#2119's sections 1/2/5 ask for; the caller supplies the full candidate
payload and this script's value is exactly the three mechanisms above.

One correction to the issue's own worked example is load-bearing enough to
call out explicitly: ``load_current_subject`` pins ``subject.predecessor`` to
a FIXED historical anchor (``relationship`` is always the single literal
``"historical_step1_predecessor"``, and its own checked value never equals
the current subject's own checkpoint identity) -- it names the clean-genesis
lineage's step-1 checkpoint, not "whatever the current subject was before
this write". Setting it to the outgoing subject's identity on every update,
as a naive reading of "predecessor" might suggest, would make every second
call fail the reader's own closed check. This writer therefore PRESERVES
``predecessor`` verbatim from the prior record on every non-bootstrap write,
and requires the caller to declare it explicitly only on the very first
(bootstrap) write, when there is no prior record to copy it from.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any


_SCRIPT_DIR = Path(__file__).resolve().parent
# src/ember/governance/scripts/<this file> -> repo root is four parents up. Stated in
# the closed self-location grammar (scripts/check_self_location_roots.py) rather than
# by a pyproject walk, so the gate can evaluate it.
_REPO_ROOT_DEFAULT = Path(__file__).resolve().parents[4]

GENESIS_SENTINEL = "GENESIS"
CURRENT_SUBJECT_RELATIVE_PATH = Path("manifests") / "ember-current-subject-v1.json"


class StaleParentError(ValueError):
    """The caller's declared parent no longer matches the durable record."""


def _import_siblings(repo_root: Path):
    """Import the three existing authorities this writer reuses.

    checkpoint_artifacts.py has its own sibling imports (checkpoint_scratch,
    durable_io) and an absolute ``from src.ember.model.model import ...``, so
    it is loaded as a plain top-level import with both its own directory and
    the repo root on sys.path -- exactly the pattern
    tests/ember_restart_model/domain-governance/test_checkpoint_artifacts.py
    already uses, not a second import convention.
    """

    restart_3b_dir = (
        repo_root
        / "src"
        / "ember"
        / "infrastructure"
        / "tools"
        / "ember-restart-3b"
    )
    for extra in (str(_SCRIPT_DIR), str(repo_root), str(restart_3b_dir)):
        if extra not in sys.path:
            sys.path.insert(0, extra)
    import checkpoint_artifacts  # noqa: E402
    import durable_io  # noqa: E402
    import gen_readme_status  # noqa: E402  (sibling module, same directory)

    return checkpoint_artifacts, durable_io, gen_readme_status


def update_current_subject(
    *,
    repo_root: Path,
    published_checkpoint_root: Path,
    candidate_payload: dict[str, Any],
    expected_parent_checkpoint_manifest_sha256: str,
    current_subject_path: Path | None = None,
) -> dict[str, Any]:
    """Atomically advance the durable selected-continuation record.

    Returns the payload actually written. Raises ``ValueError`` (a
    ``StaleParentError`` specifically for the compare-and-swap case) and
    changes nothing on disk when any check fails.
    """

    repo_root = Path(repo_root)
    published_checkpoint_root = Path(published_checkpoint_root)
    target_path = (
        Path(current_subject_path)
        if current_subject_path is not None
        else repo_root / CURRENT_SUBJECT_RELATIVE_PATH
    )
    checkpoint_artifacts, durable_io, gen_readme_status = _import_siblings(repo_root)

    # Mechanism 1: verify immutable checkpoint bytes straight off disk. The
    # writer's own claimed checkpoint_manifest_sha256 (if the candidate
    # payload's subject carries one at all) is never trusted -- it is always
    # overwritten with this freshly re-derived value.
    receipt = checkpoint_artifacts.published_checkpoint_receipt(
        published_checkpoint_root
    )
    computed_sha256 = receipt["checkpoint_manifest_sha256"]

    # Mechanism 2: the compare-and-swap read, and the stale-parent refusal.
    if target_path.exists():
        current = gen_readme_status.load_current_subject(str(target_path))
        current_sha256 = current["subject"]["checkpoint_manifest_sha256"]
        if expected_parent_checkpoint_manifest_sha256 != current_sha256:
            raise StaleParentError(
                "stale parent: expected the durable record's "
                "checkpoint_manifest_sha256 to be "
                f"{expected_parent_checkpoint_manifest_sha256!r}, but it is "
                f"{current_sha256!r} -- a newer continuation head has "
                "already been selected since this run's parent was resolved"
            )
    else:
        current = None
        if expected_parent_checkpoint_manifest_sha256 != GENESIS_SENTINEL:
            raise StaleParentError(
                "no current subject record exists yet; pass "
                f"--expected-parent-checkpoint-manifest-sha256 {GENESIS_SENTINEL} "
                "to author the first (bootstrap) record"
            )

    candidate = json.loads(json.dumps(candidate_payload))
    subject = candidate.get("subject")
    if not isinstance(subject, dict):
        raise ValueError("candidate payload is missing its subject object")
    subject["checkpoint_manifest_sha256"] = computed_sha256
    if current is not None:
        # predecessor is a fixed historical anchor (the lineage's step-1
        # checkpoint), never a rolling pointer to the outgoing subject --
        # see the module docstring. Preserved verbatim across every
        # non-bootstrap write.
        subject["predecessor"] = current["subject"]["predecessor"]
    elif "predecessor" not in subject:
        raise ValueError(
            "bootstrap write (no prior current-subject record) must declare "
            "its own subject.predecessor"
        )

    # Mechanism 3: pre-write round-trip validation, then the one disk
    # mutation. The temp file sits beside the target (same directory, same
    # volume) so atomic_replace_durable's MoveFileExW/os.replace boundary is
    # the only concurrency primitive in play -- no second format, no lock.
    target_path.parent.mkdir(parents=True, exist_ok=True)
    staged_path = (
        target_path.parent
        / f".{target_path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    )
    payload_bytes = (
        json.dumps(candidate, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    try:
        with open(staged_path, "xb") as handle:
            handle.write(payload_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        # Raises and leaves the target untouched if the candidate would fail
        # the reader's own validation -- the target is never promoted.
        gen_readme_status.load_current_subject(str(staged_path))
        durable_io.atomic_replace_durable(staged_path, target_path)
    finally:
        try:
            staged_path.unlink()
        except FileNotFoundError:
            pass

    return candidate


def _read_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=_REPO_ROOT_DEFAULT)
    parser.add_argument(
        "--published-checkpoint-root",
        type=Path,
        help=(
            "Directory holding the just-published checkpoint's "
            "checkpoint-manifest.json"
        ),
    )
    parser.add_argument(
        "--candidate-payload",
        type=Path,
        help=(
            "Path to a JSON file holding the full candidate "
            "ember-current-subject-v1 payload (schema_version/authority/"
            "subject). subject.checkpoint_manifest_sha256 and, on every "
            "non-bootstrap write, subject.predecessor are overwritten by "
            "this script and need not be accurate in the input file."
        ),
    )
    parser.add_argument(
        "--expected-parent-checkpoint-manifest-sha256",
        default=None,
        help=(
            "The checkpoint_manifest_sha256 this run believed was the "
            "current selected continuation head when it started (compare-"
            "and-swap). Pass the literal GENESIS to author the first "
            "(bootstrap) record."
        ),
    )
    parser.add_argument(
        "--current-subject-path",
        type=Path,
        default=None,
        help="Override the target path (default: <root>/manifests/ember-current-subject-v1.json)",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help=(
            "Read and validate the current durable record without writing "
            "anything; print its checkpoint_manifest_sha256 and predecessor "
            "identity and exit 0, or exit non-zero on any validation failure."
        ),
    )
    args = parser.parse_args(argv)

    repo_root = args.root.resolve()
    target_path = (
        args.current_subject_path.resolve()
        if args.current_subject_path is not None
        else repo_root / CURRENT_SUBJECT_RELATIVE_PATH
    )

    if args.verify_only:
        _, _, gen_readme_status = _import_siblings(repo_root)
        current = gen_readme_status.load_current_subject(str(target_path))
        subject = current["subject"]
        print(
            json.dumps(
                {
                    "checkpoint_manifest_sha256": subject["checkpoint_manifest_sha256"],
                    "predecessor": subject["predecessor"],
                    "token_cursor": subject["token_cursor"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.published_checkpoint_root is None:
        parser.error("--published-checkpoint-root is required unless --verify-only")
    if args.candidate_payload is None:
        parser.error("--candidate-payload is required unless --verify-only")
    if args.expected_parent_checkpoint_manifest_sha256 is None:
        parser.error(
            "--expected-parent-checkpoint-manifest-sha256 is required "
            "unless --verify-only"
        )

    candidate_payload = _read_json(args.candidate_payload)
    written = update_current_subject(
        repo_root=repo_root,
        published_checkpoint_root=args.published_checkpoint_root,
        candidate_payload=candidate_payload,
        expected_parent_checkpoint_manifest_sha256=(
            args.expected_parent_checkpoint_manifest_sha256
        ),
        current_subject_path=target_path,
    )
    print(
        json.dumps(
            {
                "checkpoint_manifest_sha256": written["subject"][
                    "checkpoint_manifest_sha256"
                ],
                "target_path": str(target_path),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
