"""receipt_fp — args-fingerprint universality (eng #10).

t4_chunked keys its progress file to an args-fingerprint and REFUSES to
resume under changed sampling args (PROGRESS-MISMATCH). This module makes
the same identity available to every receipt: a 16-hex sha1 of the
canonical JSON of the args that produced the run. Receipts become
join-able and replay-checkable by exact configuration, not filename
convention — two receipts with the same fingerprint were produced by
byte-identical args; a replay can assert it re-derived the SAME run.

Wired into: t2_round, t2_wcode, t2_grpo, t2_mtp, t5_harm (the t2/t5
families per the issue; t4_chunked keeps its own — same construction).
Passive field: no behavior change anywhere.

Selftest: key-order invariance, non-JSON-type fallback, 16-hex shape.
"""

import hashlib
import json


def args_fingerprint(d):
    """16-hex sha1 over canonical JSON (sorted keys, str-fallback)."""
    blob = json.dumps(d, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


def _selftest():
    a = {"k": 8, "model": "m", "seed": 14}
    b = {"seed": 14, "model": "m", "k": 8}  # same args, different order
    assert args_fingerprint(a) == args_fingerprint(b)
    assert args_fingerprint(a) != args_fingerprint({**a, "seed": 15})
    fp = args_fingerprint({"path": object()})  # str-fallback, no raise
    assert len(fp) == 16 and int(fp, 16) >= 0
    print("RECEIPT_FP_SELFTEST_PASS")


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        _selftest()
    else:
        print(__doc__)
