#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""C0 CRASH_SURVIVAL guard: a checkpoint written mid-crash must be rejected on resume.

The C0 ledger's blocking_reason for CRASH_SURVIVAL is exact: checkpoint save/load
identity binding exists (scripts/ember_01_identity/checkpoint_save_load_identity_
binding.py) but "no guard proves a checkpoint written mid-crash is rejected on
resume. Needs a synthetic-crash resume probe before this row can close."

This module IS that synthetic-crash resume probe. It does not reimplement
checkpoint identity measurement -- it wraps the existing trusted measurement path
(``measure_checkpoint_identity``, which already reads a shard via the isolated
counter's safe metadata-only unpickler, never ``torch.load``) in a resume-time
ACCEPTED/REJECTED decision, and supplies the crash simulation that path never had
a test for: a checkpoint file physically truncated partway through its write,
exactly what a process killed mid-``fwrite`` (OOM-killed, native-crashed, host
power-cut) leaves on disk.

Zero real Ember checkpoints, zero GPU: every fixture here is a small synthetic
torch tensor saved to a tempdir.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parents[1] / "ember_01_identity"
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from checkpoint_save_load_identity_binding import (
    CheckpointSaveLoadIdentityMismatch,
    measure_checkpoint_identity,
)

RESUME_GUARD_SCHEMA = "ember-01-crash-survival-resume-guard-v1"


def simulate_mid_crash_write(source_path: Path, dest_path: Path, *, truncate_fraction: float) -> Path:
    """Produce a synthetic mid-crash checkpoint: copy the real, complete checkpoint
    bytes at ``source_path`` and truncate the copy to ``truncate_fraction`` of its
    original length. This is what a process killed mid-write (OOM-kill, native
    crash, power loss) leaves behind -- a file that starts as a valid checkpoint
    archive on disk but never finished being written, so its trailing bytes
    (central directory, storage tail, or both) are simply absent.

    Fails closed on a malformed fraction rather than silently clamping it, so a
    caller that passes an out-of-range value never gets a fixture disguised as
    something it isn't.
    """
    if not (0.0 <= truncate_fraction <= 1.0):
        raise ValueError(f"truncate_fraction must be in [0.0, 1.0], got {truncate_fraction!r}")
    original = Path(source_path).read_bytes()
    keep = int(len(original) * truncate_fraction)
    Path(dest_path).write_bytes(original[:keep])
    return Path(dest_path)


def resume_guard(shard_path: Path) -> dict[str, Any]:
    """Fail-closed resume decision for a checkpoint shard.

    Attempts to measure the shard's save/load identity via the trusted binding
    path (``measure_checkpoint_identity``). A shard that cannot be safely
    measured -- because it is not a complete, parseable checkpoint archive, which
    is exactly the shape a mid-crash-truncated write leaves -- is REJECTED, never
    silently handed to a resume path that would call ``load_state_dict`` on
    partial/corrupted tensor storage. A shard that measures cleanly is ACCEPTED
    with its measured receipt attached, so a caller can proceed to bind/verify
    identity against the manifest as normal.

    This function raises only on a caller error (non-existent path is reported as
    a REJECTED verdict, not an exception -- "checkpoint missing" IS a resume-time
    rejection, not a programming bug); every checkpoint-content failure mode is
    captured as a REJECTED verdict naming the reason, never propagated as an
    uncaught exception a careless caller could skip past.
    """
    path = Path(shard_path)
    if not path.is_file():
        return {
            "schema": RESUME_GUARD_SCHEMA,
            "result": "REJECTED",
            "reason": f"checkpoint shard does not exist on disk: {path}",
        }
    try:
        receipt = measure_checkpoint_identity(path)
    except CheckpointSaveLoadIdentityMismatch as exc:
        return {
            "schema": RESUME_GUARD_SCHEMA,
            "result": "REJECTED",
            "reason": str(exc),
        }
    return {
        "schema": RESUME_GUARD_SCHEMA,
        "result": "ACCEPTED",
        "receipt": receipt,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("shard_path", type=Path, help="Checkpoint shard to resume-check.")
    args = parser.parse_args(argv)
    verdict = resume_guard(args.shard_path)
    print(json.dumps(verdict, indent=2, sort_keys=True, default=str))
    return 0 if verdict["result"] == "ACCEPTED" else 1


if __name__ == "__main__":
    sys.exit(main())
