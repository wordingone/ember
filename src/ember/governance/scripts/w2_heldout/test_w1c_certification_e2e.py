"""test_w1c_certification_e2e.py -- Tier-2 INTEGRATION test for the #372
W1c certification re-scope (RE-SCOPE RULING, issue #374 comment 4920277395).

Binding clause of the ruling: "Tier-2 integration tests must NOT be
env-guarded out of CI for the re-scoped build; the silent-certification
failure mode this PR's own body documents is the reason." This test file
therefore has NO env-var skip, NO --shard-dir requirement, NO GPU, NO
network -- it is fully synthetic/pilot-scale and runs unconditionally.

It exercises the REAL production wiring end-to-end (not mocked pieces):
  heldout_v21_fcalib.py CLI (--emit-boilerplate-keys)
    -> w2-boilerplate-keys/v1 JSON
    -> BoilerplateBloomIndex.build_from_fcalib_boilerplate_keys
    -> HeldoutCertifier
    -> certification verdicts, checked against a ground-truth oracle

This is exactly the class of test whose ABSENCE let two real defects ship
to master via PR #506 undetected:
  1. cap-saturated keys were excluded from the Bloom instead of folded in
     (silent-certification failure for the 3 largest sources' highest-
     frequency ambiguous-band windows)
  2. --emit-boilerplate-keys silently wrote NO output file on the default
     (non-chunked) single-call invocation path -- the only path a normal
     run without --position-chunk-count would ever take
Both are fixed in corpus_boilerplate_bloom.py / certify_heldout_batch.py /
heldout_v21_fcalib.py; this test is the regression guard for both, plus the
proof that the fcalib-output-to-certifier WIRING (previously nonexistent)
is correct.
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_ROOT = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS_ROOT)
sys.path.insert(0, SCRIPTS_ROOT)

from w2_heldout.w1c_certification_e2e import (  # noqa: E402
    run_synthetic_e2e, CERT_SOURCE, TEST_CAP, F_KEY,
)


@pytest.fixture(scope="module")
def receipt():
    """Runs the full synthetic pipeline ONCE per test module (the pipeline
    is deterministic -- see test_deterministic_across_repeated_runs, which
    runs it a second, independent time specifically to prove that)."""
    return run_synthetic_e2e()


class TestW1cCertificationE2E:
    """Full synthetic-corpus end-to-end pipeline, run unconditionally."""

    def test_fcalib_run_completes(self, receipt):
        assert receipt["fcalib_run_status"] == "complete"
        assert receipt["fcalib_predicate_version"] == "v2.1-exact50-droponly"

    def test_emit_boilerplate_keys_actually_produced_output(self, receipt):
        """Regression guard for the single-call-path silent-emission bug:
        a run with genuine boilerplate present must produce non-empty
        buckets, not just complete successfully."""
        buckets = receipt["boilerplate_keys_by_source_buckets"].get(CERT_SOURCE)
        assert buckets is not None, (
            "no boilerplate-keys buckets recorded for the certification "
            "source -- this is the exact single-call emission regression")
        assert F_KEY in buckets
        assert "cap_saturated" in buckets

    def test_bloom_sizing_reflects_actual_key_cardinality(self, receipt):
        """AC3: Bloom m/k disclosed and derived from the REAL boilerplate-
        set cardinality (1 genuine + 1 cap-saturated key here), not a
        placeholder."""
        bi = receipt["bloom_index"]
        assert bi["n_boilerplate_keys"] == 1
        assert bi["n_cap_saturated_keys"] == 1
        assert bi["bloom_m"] > 0
        assert bi["bloom_k"] > 0
        assert bi["target_fp_rate"] == 0.01

    def test_genuine_boilerplate_window_rejected_and_confirmed(self, receipt):
        """The (10,11,12,13) window (real freq=12 > k=10, cap=15 so NOT
        cap-saturated) is rejected via the Bloom-hit + exact-recheck-
        confirmed path, not the cap-saturated path."""
        results = receipt["certification_batch"]["results"]
        boilerplate_result = results[0]  # (10,11,12,13) is candidate 0
        assert boilerplate_result["certified"] is False
        assert boilerplate_result["reason"] == "bloom_positive_confirmed"
        assert boilerplate_result["bloom_hit"] is True

    def test_cap_saturated_window_rejected_unconditionally(self, receipt):
        """The (20,21,22,23) window (real freq=15 == TEST_CAP) is rejected
        via the cap-saturated path, regardless of the exact-recheck oracle
        (which would otherwise confirm it too, since freq=15 > k=10 --
        this test doesn't distinguish "confirmed via recheck" from
        "dropped as cap-saturated" on THIS window alone, but the reason
        label proves which branch fired)."""
        results = receipt["certification_batch"]["results"]
        capped_result = results[1]  # (20,21,22,23) is candidate 1
        assert capped_result["certified"] is False
        assert capped_result["reason"] == "cap_saturated"

    def test_clean_window_certified(self, receipt):
        """The (30,31,32,33) window (real freq=1, never crosses any k) is
        certified: not a Bloom hit at all."""
        results = receipt["certification_batch"]["results"]
        clean_result = results[2]  # (30,31,32,33) is candidate 2
        assert clean_result["certified"] is True
        assert clean_result["reason"] == "certified"
        assert clean_result["bloom_hit"] is False

    def test_batch_aggregate_counts(self, receipt):
        cb = receipt["certification_batch"]
        assert cb["candidates"] == 3
        assert cb["dropped_disjointness"] == 0
        assert cb["bloom_hits"] == 1          # only the genuine boilerplate key
        assert cb["exact_confirmed"] == 1     # confirmed by ground-truth recheck
        assert cb["bloom_fp_absorbed"] == 0   # no FP in this fixture
        assert cb["cap_dropped"] == 1
        assert cb["certified_count"] == 1     # only the clean window

    def test_receipt_carries_required_disclosure_fields(self, receipt):
        """AC5: schema, ts format, api_spend_usd, paid_api_surface_used."""
        assert receipt["schema"] == "w2-w1c-certification-e2e/v1"
        assert receipt["ticket"] == "W1C-CERTIFICATION-E2E"
        assert receipt["api_spend_usd"] == 0
        assert receipt["paid_api_surface_used"] is False
        # ts format: %Y%m%dT%H%M%SZ (e.g. 20260709T111421Z)
        ts = receipt["ts"]
        assert len(ts) == 16 and ts[8] == "T" and ts[-1] == "Z"
        assert "invariant_sha256" in receipt

    def test_deterministic_across_repeated_runs(self, receipt):
        """Same synthetic corpus, same fixed hash seed (SimpleBloomFilter's
        seed=0) -> identical certification verdicts across an INDEPENDENT
        second run (deliberately NOT reusing the `receipt` fixture, so this
        really re-executes the whole pipeline)."""
        r2 = run_synthetic_e2e()
        assert receipt["certification_batch"]["results"] == r2["certification_batch"]["results"]
        assert receipt["bloom_index"]["bloom_m"] == r2["bloom_index"]["bloom_m"]
        assert receipt["bloom_index"]["bloom_k"] == r2["bloom_index"]["bloom_k"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
