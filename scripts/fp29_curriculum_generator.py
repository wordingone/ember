"""fp29_curriculum_generator.py — curriculum-synthesis episode generator.

Pre-stages the curriculum generator for the fp-29 synthesis-window (Row 9,
ledger 2026-06-12).  Generates L1 and L2 episodes in TRAIN buckets 10-99
(probe buckets 0-9 never materialized), builds the per-episode manifest, and
computes `episodes_manifest_sha256` — the field that must appear in any valid
synthesis receipt consumed by fp29_kill_synthesis_gate.validate_kill().

This script proves the generator machinery WORKS and its manifest sha is
computable BEFORE the 2B->4B retry window fires.  The generator is NOT the
synthesis emitter (that lives in the continued-pretrain eng harness); it is
the proof that the harness has something to bind to.

Receipt shapes:
  DRY-RUN receipt (--dry-run --emit):
    ticket: FP29-CURRICULUM-GENERATOR-DRY-RUN
    episodes_manifest_sha256: sha256 of the manifest JSON (sort_keys=True)
    All conformance asserts: True
    window: "DRY-RUN" (not "2B->4B" — not a synthesis attempt)

  The REAL synthesis receipt (ticket: CURRICULUM-SYNTHESIS-2B4B, window:
  "2B->4B") is emitted by the continued-pretrain harness at run time using
  the SAME generator imported here; the harness adds ingestion_manifest_sha256
  after data ingestion.

`--selftest`: determinism, bucket range, no probe leak, ops-in-grammar,
  sha256 stability, receipt_check-clean on dry-run receipt.

`--dry-run N [--seed S] [--emit]`: generate N episodes (L1 + L2 split 60/40
  by default), print conformance summary, optionally write receipt.
"""
import argparse
import hashlib
import json
import os
import random
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
NC = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import fp23_probe_prereg as fp23                           # noqa: E402
from fp28_v0_coverage import _ref                          # noqa: E402
import fp31_l2_grammar as fp31                             # noqa: E402
from receipt_write import checked_write                    # noqa: E402
from receipt_check import validate_receipt                 # noqa: E402

SHA_CONVENTION = (
    "episodes_manifest_sha256: sha256 of UTF-8 JSON of the manifest list "
    "(sort_keys=True, separators=(',',':')); "
    "file shas: sha256 over raw bytes, no normalization"
)


# ---------------------------------------------------------------------------
# L1 episode draw — TRAIN buckets only
# ---------------------------------------------------------------------------

def _draw_l1(rng):
    """One L1 episode in a TRAIN bucket (bucket 10-99). Redraws on probe bucket."""
    while True:
        op = rng.choice(fp23.L1_OPS)
        ln = rng.randint(*fp23.INPUT_LEN)
        xs = [rng.randint(*fp23.INPUT_VAL) for _ in range(ln)]
        b = fp23.bucket(op, repr(xs))
        if b not in fp23.PROBE_BUCKETS:
            try:
                expected = _ref(op, list(xs))
            except Exception:
                continue  # partial op on bad input (e.g. min_fold on empty)
            return {
                "level": "L1",
                "op": op,
                "name": op,
                "input": xs,
                "bucket": b,
                "expected_repr": repr(expected),
            }


# ---------------------------------------------------------------------------
# L2 episode draw — TRAIN buckets only
# ---------------------------------------------------------------------------

def _draw_l2(rng):
    """One L2 episode in a TRAIN bucket (bucket 10-99). Redraws on probe bucket."""
    while True:
        ep = fp31.draw_l2(rng)
        if ep["bucket"] not in fp23.PROBE_BUCKETS:
            return {
                "level": "L2",
                "op": ep["name"],     # '+'-joined L1 ops
                "name": ep["name"],
                "input": ep["input"],
                "bucket": ep["bucket"],
                "expected_repr": ep["expected_repr"],
            }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_episodes(n_l1: int, n_l2: int, seed: int) -> list:
    """Generate n_l1 L1 + n_l2 L2 episodes, all in TRAIN buckets 10-99.

    Deterministic under seed; probe buckets never materialized.
    Returns list of episode dicts (level, op, name, input, bucket, expected_repr).
    """
    rng = random.Random(seed)
    episodes = []
    for _ in range(n_l1):
        episodes.append(_draw_l1(rng))
    for _ in range(n_l2):
        episodes.append(_draw_l2(rng))
    return episodes


def episodes_manifest(episodes: list) -> list:
    """Serialize episodes to the manifest shape.

    Manifest = sorted by (level, bucket, op) for determinism; each entry is
    {level, name, input, bucket, expected_repr}.  The sha256 of this list
    (JSON, sort_keys=True) is episodes_manifest_sha256.
    """
    rows = []
    for ep in episodes:
        rows.append({
            "level": ep["level"],
            "name": ep["name"],
            "input": ep["input"],
            "bucket": ep["bucket"],
            "expected_repr": ep["expected_repr"],
        })
    rows.sort(key=lambda r: (r["level"], r["bucket"], r["name"]))
    return rows


def sha256_manifest(manifest: list) -> str:
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def conformance_check(episodes: list) -> list:
    """Return list of violations (empty = conformant).

    Checks:
    1. All buckets in TRAIN range (10-99) — probe buckets 0-9 never present.
    2. Every op name in the L1/L2 grammar: L1 ops appear in fp23.L1_OPS;
       L2 op names are '+'-joined sequences where every component is in
       fp23.L1_OPS.
    """
    violations = []
    l1_ops_set = set(fp23.L1_OPS)
    for i, ep in enumerate(episodes):
        b = ep["bucket"]
        if b in fp23.PROBE_BUCKETS:
            violations.append(
                f"episode[{i}]: probe bucket {b} (op={ep['op']!r})"
            )
        elif b not in fp23.TRAIN_BUCKETS:
            violations.append(
                f"episode[{i}]: bucket {b} outside TRAIN range 10-99"
            )
        # op grammar check
        name = ep["name"]
        components = name.split("+")
        bad = [c for c in components if c not in l1_ops_set]
        if bad:
            violations.append(
                f"episode[{i}]: op name {name!r} has components "
                f"{bad!r} not in L1_OPS"
            )
    return violations


def build_dry_run_receipt(
    ts: str, n_l1: int, n_l2: int, seed: int, manifest_sha: str,
) -> dict:
    return {
        "ticket": "FP29-CURRICULUM-GENERATOR-DRY-RUN",
        "ts": ts,
        "generator_seed": seed,
        "n_episodes_l1": n_l1,
        "n_episodes_l2": n_l2,
        "n_episodes_total": n_l1 + n_l2,
        "episodes_manifest_sha256": manifest_sha,
        "bucket_range_assert": True,
        "ops_in_grammar_assert": True,
        "probe_buckets_untouched_assert": True,
        "window": "DRY-RUN",
        "note": (
            "conformance dry-run: generator machinery proven shape-conformant "
            "before the 2B->4B retry window. The REAL synthesis receipt "
            "(ticket CURRICULUM-SYNTHESIS-2B4B, window 2B->4B) is emitted by "
            "the continued-pretrain eng harness at run time."
        ),
        "sha_convention": SHA_CONVENTION,
        "no_gpu": True,
    }


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

def _selftest():
    N_L1, N_L2 = 80, 40
    SEED = fp23.GENERATOR_SEED

    # 1. All episodes in TRAIN buckets; probe never materialized
    eps = generate_episodes(N_L1, N_L2, SEED)
    assert len(eps) == N_L1 + N_L2
    for ep in eps:
        assert ep["bucket"] not in fp23.PROBE_BUCKETS, (
            f"probe bucket leaked: {ep['bucket']} op={ep['op']!r}"
        )
        assert ep["bucket"] in fp23.TRAIN_BUCKETS, (
            f"bucket {ep['bucket']} outside TRAIN range"
        )

    # 2. No conformance violations
    viols = conformance_check(eps)
    assert not viols, f"conformance violations: {viols}"

    # 3. L1 and L2 episodes present
    assert any(e["level"] == "L1" for e in eps)
    assert any(e["level"] == "L2" for e in eps)

    # 4. sha256 determinism: same seed -> identical sha
    mf1 = episodes_manifest(eps)
    sha1 = sha256_manifest(mf1)
    eps2 = generate_episodes(N_L1, N_L2, SEED)
    mf2 = episodes_manifest(eps2)
    sha2 = sha256_manifest(mf2)
    assert sha1 == sha2, f"sha not deterministic under seed {SEED}"
    assert len(sha1) == 64

    # 5. Different seed -> different sha (probabilistic; expected with overwhelming prob)
    eps3 = generate_episodes(N_L1, N_L2, SEED + 1)
    sha3 = sha256_manifest(episodes_manifest(eps3))
    assert sha1 != sha3, "sha collision across seeds — expected distinct"

    # 6. All manifest rows have required fields
    for row in mf1:
        for field in ("level", "name", "input", "bucket", "expected_repr"):
            assert field in row, f"manifest row missing {field!r}: {row}"

    # 7. Dry-run receipt passes receipt_check
    ts = "20260101T000000Z"
    receipt = build_dry_run_receipt(ts, N_L1, N_L2, SEED, sha1)
    findings = validate_receipt(receipt)
    assert findings == [], f"dry-run receipt fails receipt_check: {findings}"

    # 8. Conformance check catches probe-bucket violation (synthetic inject)
    bad_ep = {"level": "L1", "op": "reverse", "name": "reverse",
              "input": [1, 2], "bucket": 3, "expected_repr": "[2, 1]"}
    viols2 = conformance_check([bad_ep])
    assert any("probe bucket" in v for v in viols2), viols2

    # 9. Conformance check catches unknown op
    bad_ep2 = {"level": "L1", "op": "unknown_op", "name": "unknown_op",
               "input": [1], "bucket": 42, "expected_repr": "1"}
    viols3 = conformance_check([bad_ep2])
    assert any("not in L1_OPS" in v for v in viols3), viols3

    print("FP29_CURRICULUM_GENERATOR_SELFTEST_PASS")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="fp-29 curriculum generator — dry-run + conformance check"
    )
    ap.add_argument("--selftest", action="store_true",
                    help="pure-logic selftest (no disk writes)")
    ap.add_argument("--dry-run", type=int, default=None, metavar="N",
                    help="generate N episodes (60%% L1, 40%% L2) and check conformance")
    ap.add_argument("--seed", type=int, default=fp23.GENERATOR_SEED,
                    help=f"RNG seed (default: {fp23.GENERATOR_SEED})")
    ap.add_argument("--emit", action="store_true",
                    help="write dry-run receipt to receipts/ (requires --dry-run)")
    args = ap.parse_args()

    if args.selftest:
        _selftest()
        return

    if args.dry_run is None:
        print(
            "FP29_CURRICULUM_GENERATOR_STAGED\n"
            "  --selftest: pure-logic selftest\n"
            "  --dry-run N [--seed S] [--emit]: generate N episodes + conformance\n"
            "  The REAL synthesis receipt is emitted by the continued-pretrain harness."
        )
        return

    n = args.dry_run
    n_l1 = max(1, int(n * 0.6))
    n_l2 = n - n_l1
    seed = args.seed

    print(f"Generating {n} episodes (L1={n_l1}, L2={n_l2}, seed={seed})...")
    eps = generate_episodes(n_l1, n_l2, seed)

    viols = conformance_check(eps)
    if viols:
        for v in viols:
            print(f"  VIOLATION: {v}")
        raise SystemExit("fp29_curriculum_generator: conformance FAIL")

    mf = episodes_manifest(eps)
    sha = sha256_manifest(mf)

    print(f"  episodes_manifest_sha256: {sha[:16]}...")
    print(f"  bucket range: {min(e['bucket'] for e in eps)}"
          f"–{max(e['bucket'] for e in eps)} (all TRAIN 10-99)")
    print(f"  L1 ops in batch: {sorted(set(e['op'] for e in eps if e['level']=='L1'))}")
    l2_names = sorted(set(e['name'] for e in eps if e['level'] == 'L2'))
    print(f"  L2 op names (sample): {l2_names[:3]}{'...' if len(l2_names) > 3 else ''}")
    print("  conformance: PASS (no probe buckets; all ops in L1/L2 grammar)")

    if args.emit:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        receipt = build_dry_run_receipt(ts, n_l1, n_l2, seed, sha)
        findings = validate_receipt(receipt)
        if findings:
            raise SystemExit(f"receipt_check FAIL: {findings}")
        out = os.path.join(NC, "receipts", f"fp29-curriculum-dryrun-{ts}.json")
        checked_write(out, receipt)
        print(f"\nRECEIPT: {out}")
        print(f"  episodes_manifest_sha256: {sha}")
    else:
        print("\n(dry-run: pass --emit to write receipt)")


if __name__ == "__main__":
    main()
