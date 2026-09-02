# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""exp711_permute.py -- #711 ordering-screen CPU apparatus, component 3:
arm permutation wrapper.

Prereg v2 SS2 (binding): arms are PERMUTATIONS OF IDENTICAL TRIMMED WINDOW
INDICES (BLOCK_DOCUMENT_REPACK) over the ONE frozen manifest (component 2):

  A / A' / A''  -- independent random permutations, seeds 4241 / 5479 /
                   6733 (stage 1 noise band; A(4241) doubles as baseline
                   and compute-target setter).
  B             -- ascending frozen-scorer window score (ties -> ascending
                   window id).
  C             -- descending frozen-scorer window score, the directional
                   control (ties -> ascending window id, NOT a naive
                   reverse(B) -- tie order stays ascending-id both ways).

This permutation machinery is NEW CODE on the causal path (prereg SS2,
panel B2: no permutation parameter exists in the production loader). The
identity permutation must byte-reproduce legacy sequential
PackedShardLoader batches over probe steps (SS8 selftest); the launch
preflight cross-checks the realized first 1,000 window ids against the
arm's manifest permutation FAIL-CLOSED (SS2, not log-only); full-example
hash-multiset equality is asserted across all arm manifests (SS2 pre-run
assert -- arms reorder the SAME window multiset, they never add/drop/
duplicate).

Run (given a component-2 manifest receipt, writes the permutation
apparatus receipt for arms A/A'/A''; B/C require a scorer receipt --
see exp711_scorer.py):
    python src/ember/governance/scripts/exp711_permute.py --emit \\
        --manifest-receipt receipts/exp711-apparatus/exp711-manifest-<ts>.json
Selftest (small synthetic manifest + synthetic scores):
    python src/ember/governance/scripts/exp711_permute.py --selftest
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

# issue2015 exact-local-import:src/ember/governance/scripts/receipt_write.py
import importlib.util as _ember_66ee9e91637922dc_importlib
import sys as _ember_66ee9e91637922dc_sys
from pathlib import Path as _ember_66ee9e91637922dc_Path
_ember_66ee9e91637922dc_path = _ember_66ee9e91637922dc_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'receipt_write.py')
if not _ember_66ee9e91637922dc_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/receipt_write.py')
_ember_66ee9e91637922dc_aliases = ('_ember_issue2015_66ee9e91637922dc', 'receipt_write', 'scripts.receipt_write')
_ember_66ee9e91637922dc_existing = []
for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
    _ember_66ee9e91637922dc_candidate = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
    if _ember_66ee9e91637922dc_candidate is not None and all(_ember_66ee9e91637922dc_candidate is not item for item in _ember_66ee9e91637922dc_existing):
        _ember_66ee9e91637922dc_existing.append(_ember_66ee9e91637922dc_candidate)
if len(_ember_66ee9e91637922dc_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/receipt_write.py')
if _ember_66ee9e91637922dc_existing:
    _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_existing[0]
    _ember_66ee9e91637922dc_observed = getattr(_ember_66ee9e91637922dc_module, '__file__', None)
    if _ember_66ee9e91637922dc_observed is None or _ember_66ee9e91637922dc_Path(_ember_66ee9e91637922dc_observed).resolve() != _ember_66ee9e91637922dc_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/receipt_write.py')
else:
    _ember_66ee9e91637922dc_spec = _ember_66ee9e91637922dc_importlib.spec_from_file_location('_ember_issue2015_66ee9e91637922dc', _ember_66ee9e91637922dc_path)
    if _ember_66ee9e91637922dc_spec is None or _ember_66ee9e91637922dc_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_importlib.module_from_spec(_ember_66ee9e91637922dc_spec)
    for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
        _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
        if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
        _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
    try:
        _ember_66ee9e91637922dc_spec.loader.exec_module(_ember_66ee9e91637922dc_module)
    except BaseException:
        for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
            if _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias) is _ember_66ee9e91637922dc_module:
                _ember_66ee9e91637922dc_sys.modules.pop(_ember_66ee9e91637922dc_alias, None)
        raise
for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
    _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
    if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
checked_write = getattr(_ember_66ee9e91637922dc_module, 'checked_write')
# issue2015 exact-local-import-end:src/ember/governance/scripts/receipt_write.py  # noqa: E402
import exp711_manifest as em  # noqa: E402

INVARIANT_SHA256 = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"
SHA_CONVENTION = "sha256 over the little-endian int64 bytes of the ordered window-id array"

SEEDS = {"A": 4241, "A_PRIME": 5479, "A_DPRIME": 6733}
OUT_DIR = os.path.join(REPO, "receipts", "exp711-apparatus")


def _now_ts():
    return datetime.now(timezone.utc).isoformat()


class PermuteError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Arms
# ---------------------------------------------------------------------------

def seeded_permutation_arm(window_ids, seed: int):
    """Independent random permutation of the frozen manifest's window ids
    (numpy Generator(PCG64(seed)), a deterministic, reproducible RNG)."""
    import numpy as np
    rng = np.random.default_rng(seed)
    perm = rng.permutation(len(window_ids))
    return np.asarray(window_ids)[perm]


def score_ordered_arm(window_ids, scores_by_id: dict, ascending: bool):
    """Score-ordered arm (B: ascending, C: descending). Ties -> ascending
    window id, for BOTH directions (C is NOT a naive reverse(B) -- a
    reversed B would present tied elements in descending id order, which
    the prereg's tie rule forbids for either arm)."""
    import numpy as np
    ids = list(window_ids)
    sign = 1.0 if ascending else -1.0
    keyed = sorted(ids, key=lambda w: (sign * scores_by_id[int(w)], int(w)))
    return np.asarray(keyed, dtype=np.asarray(window_ids).dtype)


def build_all_arms(window_ids, scores_by_id: dict = None):
    """{'A':.., 'A_PRIME':.., 'A_DPRIME':.., 'B':.., 'C':..} -- B/C omitted
    if scores_by_id is None (permute component can run standalone for the
    A-arms; B/C need the frozen scorer's output)."""
    arms = {name: seeded_permutation_arm(window_ids, seed)
            for name, seed in SEEDS.items()}
    if scores_by_id is not None:
        arms["B"] = score_ordered_arm(window_ids, scores_by_id, ascending=True)
        arms["C"] = score_ordered_arm(window_ids, scores_by_id, ascending=False)
    return arms


# ---------------------------------------------------------------------------
# step -> permuted window id -> window
# ---------------------------------------------------------------------------

def batch_window_ids(arm_order, step: int, batch_size: int):
    """Window ids for global `step` under an arm's frozen order. Pure
    function of step (resume-safe, mirrors PackedShardLoader.batch's
    contract) -- but REFUSES out-of-range access (never wraps modulo
    len(arm_order); a frozen exp711 arm is consumed for exactly one
    epoch, launch-asserted via exp711_manifest.assert_launch)."""
    n = len(arm_order)
    start = step * batch_size
    end = start + batch_size
    if start < 0 or end > n:
        raise IndexError(
            f"WRAP_REFUSED: step {step} batch {batch_size} needs "
            f"[{start},{end}) but arm order has only {n} ids -- the "
            "frozen arm never wraps")
    return [int(w) for w in arm_order[start:end]]


# ---------------------------------------------------------------------------
# Identity-permutation selftest support: byte-reproduce legacy sequential
# PackedShardLoader batches.
# ---------------------------------------------------------------------------

def identity_arm(window_ids):
    """The identity permutation IS the manifest's own canonical
    (ascending) order -- seed-free, used only for the byte-reproduction
    selftest below, never as a treatment arm."""
    import numpy as np
    return np.asarray(window_ids)


# ---------------------------------------------------------------------------
# Launch preflight (fail-closed, not log-only)
# ---------------------------------------------------------------------------

def preflight_check_first_1000(realized_window_ids: list, arm_order) -> None:
    """Cross-check the REALIZED first 1,000 window ids a run actually
    consumed against the arm's frozen manifest permutation. Fail-closed:
    raises on any mismatch, at any position -- this is the guard that
    catches the permutation machinery (new code, no production precedent)
    silently drifting from its own frozen order."""
    n = min(1000, len(arm_order))
    expected = [int(w) for w in arm_order[:n]]
    got = list(realized_window_ids[:n])
    if len(got) < n:
        raise PermuteError(
            f"PREFLIGHT_SHORT: realized only {len(got)} ids, need {n}")
    mismatches = [(i, expected[i], got[i]) for i in range(n) if expected[i] != got[i]]
    if mismatches:
        raise PermuteError(
            f"PREFLIGHT_MISMATCH: {len(mismatches)}/{n} realized window "
            f"ids diverge from the arm's frozen permutation -- first: "
            f"position {mismatches[0][0]} expected {mismatches[0][1]} "
            f"got {mismatches[0][2]}")


# ---------------------------------------------------------------------------
# Full-example hash-multiset equality across arm manifests
# ---------------------------------------------------------------------------

def assert_hash_multiset_equality(manifest_window_ids, arm_order, arm_name: str) -> None:
    """Every arm is a REORDERING of the identical frozen window-id
    multiset -- never adds, drops, or duplicates. Since a per-window hash
    is a deterministic function of window id alone (component 2's
    freeze_example_hashes), multiset equality on ids IS multiset
    equality on hashes; asserted directly on ids (cheaper, no re-decode)
    plus disclosed as such."""
    base = sorted(int(w) for w in manifest_window_ids)
    arm = sorted(int(w) for w in arm_order)
    if base != arm:
        base_set, arm_set = set(base), set(arm)
        raise PermuteError(
            f"HASH_MULTISET_MISMATCH[{arm_name}]: arm order is not a pure "
            f"permutation of the manifest -- {len(base_set - arm_set)} id(s) "
            f"missing, {len(arm_set - base_set)} id(s) added/duplicated")


# ---------------------------------------------------------------------------
# Real-corpus wiring
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--emit", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--manifest-receipt")
    ap.add_argument("--scorer-receipt", default=None,
                     help="optional exp711_scorer.py receipt; enables B/C arms")
    args = ap.parse_args()

    if args.selftest:
        _selftest()
        return

    if not args.emit:
        ap.error("pass --emit or --selftest")
    if not args.manifest_receipt:
        ap.error("--emit requires --manifest-receipt")

    with open(args.manifest_receipt, encoding="utf-8") as f:
        mrec = json.load(f)

    # The manifest receipt banks only first/last 1000 ids + a sha256 of
    # the FULL id array (real corpus scale, ~6.8M ids) -- this component's
    # --emit path operates on the disclosed sample the manifest receipt
    # carries; a full-corpus arm build is the treatment-launch's job
    # (which re-derives the manifest deterministically from the same
    # frozen inputs and gets the identical id array, verified by the
    # manifest_window_ids_sha256 pin).
    sample_ids = (mrec["manifest_window_ids_first_1000"]
                  + mrec["manifest_window_ids_last_1000"])

    scores_by_id = None
    if args.scorer_receipt:
        with open(args.scorer_receipt, encoding="utf-8") as f:
            srec = json.load(f)
        scores_by_id = {int(w): float(s) for w, s in
                         zip(srec["scored_window_ids"], srec["scores"])}
        sample_ids = [w for w in sample_ids if w in scores_by_id]

    arms = build_all_arms(sample_ids, scores_by_id)
    for name, arm_order in arms.items():
        assert_hash_multiset_equality(sample_ids, arm_order, name)

    os.makedirs(OUT_DIR, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = os.path.join(OUT_DIR, f"exp711-permute-{ts}.json")
    receipt_out = {
        "ticket": "EXP711-PERMUTE",
        "ts": _now_ts(),
        "invariant_sha256": INVARIANT_SHA256,
        "sha_convention": SHA_CONVENTION,
        "refs": [711, 739],
        "manifest_receipt": os.path.basename(args.manifest_receipt),
        "scorer_receipt": os.path.basename(args.scorer_receipt) if args.scorer_receipt else None,
        "n_sample_ids": len(sample_ids),
        "seeds": SEEDS,
        "arms": {name: {
            "n_ids": len(arm_order),
            "order_sha256": hashlib.sha256(
                __import__("numpy").asarray(arm_order, dtype="<i8").tobytes()
            ).hexdigest(),
            "first_50": [int(w) for w in arm_order[:50]],
        } for name, arm_order in arms.items()},
        "note": ("this receipt operates on the manifest receipt's disclosed "
                 "first/last-1000 sample, not the full ~6.8M-id manifest -- "
                 "the full-manifest arm build is a treatment-launch-time "
                 "artifact, re-derived deterministically and pinned by "
                 "manifest_window_ids_sha256"),
    }
    checked_write(out_path, receipt_out)
    print(f"EXP711_PERMUTE_EMIT_OK: {out_path}")
    print(json.dumps({name: receipt_out["arms"][name]["order_sha256"]
                       for name in receipt_out["arms"]}, indent=2))


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

def _selftest():
    import numpy as np
    from timeshare_pretrain import PackedShardLoader

    # --- Identity-permutation byte-reproduction of legacy sequential
    # PackedShardLoader batches, over a synthetic no-reservation manifest
    # (manifest == range(n_windows_trimmed) exactly when nothing is
    # excluded, so identity_arm reproduces the production loader's own
    # sequential batch() output verbatim). Build synthetic shards on disk
    # so we can drive the REAL PackedShardLoader (ground truth).
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        rng = np.random.default_rng(4241)
        seq, n_mtp = 16, 2
        bl = seq + 1 + n_mtp
        n_tokens = 2000
        stream_arr = rng.integers(8, 32000, size=n_tokens, dtype=np.uint16)
        shard_path = os.path.join(tmpdir, "v0-00000.bin")
        stream_arr.tofile(shard_path)

        loader = PackedShardLoader(tmpdir, seq=seq, n_mtp=n_mtp)  # legacy path
        n_windows = loader.n_windows
        batch_size = 4
        n_trimmed = (n_windows // batch_size) * batch_size
        manifest_ids = np.arange(n_trimmed, dtype=np.int64)  # no exclusions

        id_arm = identity_arm(manifest_ids)
        assert list(id_arm) == list(range(n_trimmed)), (
            "SELFTEST: identity arm must equal canonical ascending order "
            "when nothing is excluded")

        probe_steps = n_trimmed // batch_size
        for step in range(probe_steps):
            legacy_x, legacy_y0, legacy_ymtp = loader.batch(step, batch_size)
            perm_ids = batch_window_ids(id_arm, step, batch_size)
            assert perm_ids == list(range(step * batch_size, step * batch_size + batch_size)), (
                f"SELFTEST: identity arm batch ids diverge from sequential "
                f"at step {step}")
            for j, wid in enumerate(perm_ids):
                x_np, y0_np, ymtp_np = loader.window_np(wid)
                assert np.array_equal(legacy_x[j].numpy(), x_np), (
                    f"SELFTEST: identity-arm x mismatch step={step} j={j}")
                assert np.array_equal(legacy_y0[j].numpy(), y0_np), (
                    f"SELFTEST: identity-arm y0 mismatch step={step} j={j}")
                for k in range(n_mtp):
                    assert np.array_equal(legacy_ymtp[k][j].numpy(), ymtp_np[k]), (
                        f"SELFTEST: identity-arm y_mtp[{k}] mismatch "
                        f"step={step} j={j}")

    # --- Seeded-permutation arms: deterministic, reproducible, and a true
    # permutation (multiset-preserving) of a synthetic manifest.
    manifest_ids2 = np.arange(500, dtype=np.int64)
    scores = {int(w): float(rng.normal()) for w in manifest_ids2}
    # Force a real tie-block so the tie-break rule is exercised.
    tie_ids = manifest_ids2[:5]
    for w in tie_ids:
        scores[int(w)] = 0.0

    arms = build_all_arms(manifest_ids2, scores)
    assert set(arms.keys()) == {"A", "A_PRIME", "A_DPRIME", "B", "C"}

    for name, arm_order in arms.items():
        assert_hash_multiset_equality(manifest_ids2, arm_order, name)

    # Reproducibility: same seed -> byte-identical order.
    arm_a_again = seeded_permutation_arm(manifest_ids2, SEEDS["A"])
    assert list(arm_a_again) == list(arms["A"]), (
        "SELFTEST: seeded permutation not reproducible for the same seed")

    # Different seeds -> different orders (sanity; astronomically unlikely
    # to collide by chance at n=500).
    assert list(arms["A"]) != list(arms["A_PRIME"]), (
        "SELFTEST: A and A' produced identical order -- seed not taking effect")

    # B ascending / C descending by score, ties -> ascending window id
    # (for BOTH arms, not a naive reverse).
    b_scores = [scores[int(w)] for w in arms["B"]]
    assert all(b_scores[i] <= b_scores[i + 1] for i in range(len(b_scores) - 1)), (
        "SELFTEST: B arm not ascending by score")
    c_scores = [scores[int(w)] for w in arms["C"]]
    assert all(c_scores[i] >= c_scores[i + 1] for i in range(len(c_scores) - 1)), (
        "SELFTEST: C arm not descending by score")
    b_tie_block = [int(w) for w in arms["B"] if scores[int(w)] == 0.0]
    c_tie_block = [int(w) for w in arms["C"] if scores[int(w)] == 0.0]
    assert b_tie_block == sorted(b_tie_block), "SELFTEST: B tie-block not ascending id"
    assert c_tie_block == sorted(c_tie_block), (
        "SELFTEST: C tie-block not ascending id (must NOT be a naive "
        "reverse(B), which would give descending id here)")

    # Launch preflight: matching first-1000 (here: first-n) passes;
    # a corrupted realized stream is caught fail-closed.
    preflight_check_first_1000(list(arms["A"]), arms["A"])
    corrupted = list(arms["A"])
    corrupted[3] = corrupted[3] + 1 if corrupted[3] + 1 not in corrupted else corrupted[3] - 1
    try:
        preflight_check_first_1000(corrupted, arms["A"])
        raise AssertionError("SELFTEST: preflight failed to catch a "
                              "corrupted realized-id stream")
    except PermuteError:
        pass

    # batch_window_ids refuses to wrap past the arm's own length.
    n = len(arms["A"])
    bs = 8
    steps_ok = n // bs
    _ = batch_window_ids(arms["A"], steps_ok - 1, bs)
    try:
        batch_window_ids(arms["A"], steps_ok, bs)  # runs past the end
        raise AssertionError("SELFTEST: batch_window_ids failed to refuse "
                              "an out-of-range (wrap) step")
    except IndexError:
        pass

    # Multiset-equality assert actually catches a broken arm (duplicate +
    # drop, same length).
    broken = np.array(arms["A"], copy=True)
    broken[0] = broken[1]  # duplicate id 1, silently drops another
    try:
        assert_hash_multiset_equality(manifest_ids2, broken, "BROKEN")
        raise AssertionError("SELFTEST: multiset-equality assert failed "
                              "to catch a duplicated/dropped id")
    except PermuteError:
        pass

    print("EXP711_PERMUTE_SELFTEST_PASS")
    print(json.dumps({
        "identity_probe_steps": probe_steps,
        "n_arms": len(arms),
        "b_tie_block_len": len(b_tie_block),
    }, indent=2))


if __name__ == "__main__":
    main()
