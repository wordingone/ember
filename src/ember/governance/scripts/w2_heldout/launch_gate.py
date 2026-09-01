# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""launch_gate.py -- W2 preregistration sec.4 launch-gate hook.

"Before either arm launches ... contamination_recheck must report 0 matches
or the launch gate refuses" (docs/domains/governance/spec/w2-scale-preregistration-v1.md sec.4).

No W2 runner file exists yet (grepped scripts/ + receipts/ + docs/ for
w2_scale*/w2-scale*: nothing but this precondition's own frozen spec and the
unrelated archived w2_ingest.py corpus-ingest scripts under
state/archive/2026-07-02-cleanup/, a different lineage). Delivered here as a
standalone, importable module per the dispatch's own fallback instruction:
the future W2 runner imports `refuse_or_pass` (or `assert_launch_allowed` for
a fail-closed one-liner) and calls it before building either arm's model.

Refusal contract (fail-closed on every ambiguous case):
  1. The decontam receipt (receipts/ember-c-scale/w2-heldout-decontam-*.json,
     newest by ts if more than one) must exist and parse as JSON.
  2. The receipt's own `pass` field must be true and
     `contamination_recheck.confirmed_non_self_matches` must be exactly 0.
  3. The batch file the receipt is pinned to (co-located
     w2-heldout-batch.npy by convention, or an explicit --batch-file) must
     exist on disk, and sha256(int64 bytes of [x||y], the SAME convention as
     build_decontam_batch.batch_sha256 / sha256_tokens) must equal the
     receipt's `batch_sha256`.
  4. Any missing file, unparseable JSON, mismatched sha, non-zero
     contamination count, or pass=false -> REFUSE with a specific reason.
     Only all four checks passing -> ALLOW.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import sys
from dataclasses import dataclass

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", ".."))

DEFAULT_RECEIPT_DIR = os.path.join(REPO_ROOT, "receipts", "ember-c-scale")
DEFAULT_RECEIPT_GLOB = "w2-heldout-decontam-*.json"


@dataclass
class GateResult:
    allowed: bool
    reason: str
    receipt_path: str | None = None


def _newest_receipt(receipt_dir: str, pattern: str = DEFAULT_RECEIPT_GLOB) -> str | None:
    matches = sorted(glob.glob(os.path.join(receipt_dir, pattern)))
    return matches[-1] if matches else None


def _batch_sha256_from_file(batch_path: str, seq: int) -> str:
    """Recomputes the SAME sha256 convention build_decontam_batch.batch_sha256
    uses (int64 bytes of [x||y] per row, row-major), reading whatever batch
    array is on disk -- a tampered file produces a different sha, which is
    exactly the RED case this gate exists to catch."""
    arr = np.load(batch_path)
    arr = np.asarray(arr, dtype=np.int64)
    if arr.ndim != 2 or arr.shape[1] < seq + 1:
        raise ValueError(
            f"batch file {batch_path!r} has shape {arr.shape}, expected "
            f"[batch, >= seq+1={seq + 1}]")
    xs = arr[:, :seq]
    ys = arr[:, 1:seq + 1]
    combined = np.concatenate([xs, ys], axis=1)
    return hashlib.sha256(combined.tobytes()).hexdigest()


def refuse_or_pass(*, batch_path: str, receipt_dir: str = DEFAULT_RECEIPT_DIR,
                    receipt_path: str | None = None) -> GateResult:
    """The launch-gate check. Returns a GateResult; never raises for an
    ordinary refusal case (missing/mismatched/tampered) -- those are ALL
    valid REFUSE outcomes, not exceptions. Only a genuinely broken
    environment (e.g. numpy itself unavailable) would raise."""
    rp = receipt_path or _newest_receipt(receipt_dir)
    if rp is None:
        return GateResult(False, f"no decontamination receipt found under {receipt_dir!r} "
                                  f"(pattern {DEFAULT_RECEIPT_GLOB!r}) -- W2 launch refused")
    if not os.path.isfile(rp):
        return GateResult(False, f"receipt path {rp!r} does not exist -- W2 launch refused")

    try:
        with open(rp, "r", encoding="utf-8") as fh:
            receipt = json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        return GateResult(False, f"receipt {rp!r} unreadable/unparseable "
                                  f"({type(e).__name__}: {e}) -- W2 launch refused", rp)

    if receipt.get("pass") is not True:
        return GateResult(False, f"receipt {rp!r} pass={receipt.get('pass')!r} "
                                  "(not True) -- W2 launch refused", rp)

    cr = receipt.get("contamination_recheck") or {}
    confirmed = cr.get("confirmed_non_self_matches")
    if confirmed != 0:
        return GateResult(False, f"receipt {rp!r} contamination_recheck."
                                  f"confirmed_non_self_matches={confirmed!r} != 0 -- "
                                  "W2 launch refused", rp)

    if not os.path.isfile(batch_path):
        return GateResult(False, f"pinned batch file {batch_path!r} does not exist -- "
                                  "W2 launch refused", rp)

    pinned_sha = receipt.get("batch_sha256")
    seq = receipt.get("seq")
    if not pinned_sha or not isinstance(seq, int):
        return GateResult(False, f"receipt {rp!r} missing batch_sha256 or seq -- "
                                  "W2 launch refused", rp)

    try:
        on_disk_sha = _batch_sha256_from_file(batch_path, seq)
    except Exception as e:
        return GateResult(False, f"could not hash batch file {batch_path!r} "
                                  f"({type(e).__name__}: {e}) -- W2 launch refused", rp)

    if on_disk_sha != pinned_sha:
        return GateResult(False, f"batch file {batch_path!r} sha256={on_disk_sha} != "
                                  f"receipt-pinned sha256={pinned_sha} -- tampered or stale "
                                  "batch, W2 launch refused", rp)

    return GateResult(True, f"receipt {rp!r} pinned sha matches {batch_path!r}, "
                             "contamination_recheck.confirmed_non_self_matches=0 -- "
                             "W2 launch ALLOWED", rp)


def assert_launch_allowed(*, batch_path: str, receipt_dir: str = DEFAULT_RECEIPT_DIR,
                           receipt_path: str | None = None) -> GateResult:
    """Fail-closed one-liner for the future runner: raises SystemExit on
    refusal so a runner that forgets to check `.allowed` itself still can't
    proceed past an unchecked call site."""
    result = refuse_or_pass(batch_path=batch_path, receipt_dir=receipt_dir,
                             receipt_path=receipt_path)
    if not result.allowed:
        raise SystemExit(f"W2_LAUNCH_GATE_REFUSED: {result.reason}")
    return result


# ---------------------------------------------------------------------------
# CLI selftest -- RED (tampered batch -> refuse) and GREEN (pinned batch ->
# pass) cases, built from a tiny synthetic fixture (no real corpus needed:
# this gate tests refusal LOGIC against a receipt+batch-file pair, not the
# real decontamination run itself -- that's build_decontam_batch's job,
# covered separately). Exits 0 with a verdict line only if BOTH cases behave
# as expected; exits 1 otherwise.
# ---------------------------------------------------------------------------

def _selftest() -> int:
    import tempfile

    seq = 4
    rows = np.array([[1, 2, 3, 4, 5], [6, 7, 8, 9, 10]], dtype=np.int64)
    xs, ys = rows[:, :seq], rows[:, 1:seq + 1]
    sha = hashlib.sha256(np.concatenate([xs, ys], axis=1).tobytes()).hexdigest()

    with tempfile.TemporaryDirectory() as td:
        batch_path = os.path.join(td, "batch.npy")
        np.save(batch_path, rows)
        receipt_dir = os.path.join(td, "receipts")
        os.makedirs(receipt_dir, exist_ok=True)

        def _write_receipt(name, *, pass_field=True, confirmed=0, sha256=sha):
            path = os.path.join(receipt_dir, name)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"pass": pass_field, "seq": seq, "batch_sha256": sha256,
                           "contamination_recheck": {"confirmed_non_self_matches": confirmed}},
                          fh)
            return path

        # GREEN: pinned batch, matching sha, pass=True, 0 confirmed matches.
        green_receipt = _write_receipt("w2-heldout-decontam-GREEN.json")
        green = refuse_or_pass(batch_path=batch_path, receipt_path=green_receipt)
        if not green.allowed:
            print(f"SELFTEST_FAIL green case refused unexpectedly: {green.reason}")
            return 1

        # RED case A: tampered batch file (content changed after receipt
        # pinned -> sha mismatch).
        tampered_path = os.path.join(td, "batch_tampered.npy")
        np.save(tampered_path, rows + 1)
        red_a = refuse_or_pass(batch_path=tampered_path, receipt_path=green_receipt)
        if red_a.allowed:
            print("SELFTEST_FAIL red-tampered-batch case was allowed, expected refusal")
            return 1

        # RED case B: receipt itself claims contamination found.
        red_receipt = _write_receipt("w2-heldout-decontam-RED.json", confirmed=42)
        red_b = refuse_or_pass(batch_path=batch_path, receipt_path=red_receipt)
        if red_b.allowed:
            print("SELFTEST_FAIL red-contaminated-receipt case was allowed, expected refusal")
            return 1

        # RED case C: no receipt at all.
        red_c = refuse_or_pass(batch_path=batch_path,
                                receipt_path=os.path.join(receipt_dir, "does-not-exist.json"))
        if red_c.allowed:
            print("SELFTEST_FAIL red-missing-receipt case was allowed, expected refusal")
            return 1

    print("selftest=PASS green=ALLOWED red_tampered=REFUSED "
          "red_contaminated=REFUSED red_missing=REFUSED exit=PASS")
    return 0


if __name__ == "__main__":
    sys.exit(_selftest())
