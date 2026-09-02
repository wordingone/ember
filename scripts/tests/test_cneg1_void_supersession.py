#!/usr/bin/env python3
"""TDD: gh issue #358 -- mirror the scanner's VOID-supersession exclusion in
test_c_neg1.py's own _decisive_claim_files() corpus, via the shared helper
module src/ember/governance/scripts/ember_totality/void_supersession.py (factored out of
spend_annex_scan.py, gh issue #353).

Incident this fixes (PR #350's own body): spend_annex_scan.py excludes a
VOID-superseded receipt from its annex row set, but test_c_neg1.py's own
decisive-claim corpus did not mirror that exclusion -- so the probe kept
counting the exact same, formally-disposed receipt as undeclared+uncovered.
Live instance: C(-1) read RED 1/264 where the 1 was exactly
reference-uiux-ax-observation-20260622T151722Z.json, excluded by the
scanner, still counted by the probe.

Three regression tests, per issue #358's own text:
  (1) a superseded receipt is excluded by the probe, AND the exclusion is
      disclosed in the reason text (never silent) -- an exclusion that only
      shrinks the denominator with no trace is indistinguishable from
      laundering.
  (2) the VOID receipt itself is still counted as a decisive-claim receipt
      (it must self-declare zero-cost or be annex-covered like any other).
  (3) a supersedes entry whose sha256 does not match the target's on-disk
      file does NOT exclude it -- the cbase-gpu-verify-VOID receipts record
      the superseded CHECKPOINT's sha256, not either receipt FILE's own
      hash; this must never produce a false-positive exclusion.
"""

import hashlib
import importlib.util
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
TOTALITY_DIR = os.path.join(REPO_ROOT, "scripts", "ember_totality")
if TOTALITY_DIR not in sys.path:
    sys.path.insert(0, TOTALITY_DIR)  # both void_supersession.py and test_c_neg1.py
                                        # import _lane14_common by bare module name


def _load_cneg1_module(tmp_root, unique_suffix):
    """Import a FRESH copy of test_c_neg1.py (and its void_supersession
    dependency) bound to tmp_root via EMBER_TOTALITY_ROOT. Both modules
    resolve ROOT at import time from that env var -- a unique module name +
    fresh exec_module call per test forces a real re-import every time,
    always against the CURRENT tmp_root, never a stale cached binding."""
    os.environ["EMBER_TOTALITY_ROOT"] = tmp_root

    void_supersession_name = f"void_supersession_{unique_suffix}"
    vs_spec = importlib.util.spec_from_file_location(
        void_supersession_name, os.path.join(TOTALITY_DIR, "void_supersession.py"))
    vs_mod = importlib.util.module_from_spec(vs_spec)
    sys.modules[void_supersession_name] = vs_mod
    vs_spec.loader.exec_module(vs_mod)
    # test_c_neg1.py does `import void_supersession` by bare module name --
    # pre-register this freshly-bound instance under that exact key.
    sys.modules["void_supersession"] = vs_mod

    cneg1_name = f"test_c_neg1_{unique_suffix}"
    cneg1_spec = importlib.util.spec_from_file_location(
        cneg1_name, os.path.join(TOTALITY_DIR, "test_c_neg1.py"))
    cneg1_mod = importlib.util.module_from_spec(cneg1_spec)
    sys.modules[cneg1_name] = cneg1_mod
    cneg1_spec.loader.exec_module(cneg1_mod)
    return cneg1_mod


def _write_json(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(content, fh, indent=2)
    return path


def _sha256_of(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _make_sandbox(void_sha):
    """A clean, PASS-class, zero-cost decisive receipt (so the probe has a
    valid clear packet regardless of what happens to the superseded one),
    the target receipt to be superseded, and a VOID receipt whose supersedes
    entry carries `void_sha` (the caller controls whether this matches the
    target's real on-disk hash or not)."""
    tmpdir = tempfile.mkdtemp()
    receipts = os.path.join(tmpdir, "receipts")

    _write_json(
        os.path.join(receipts, "clean-clear-packet-20260707T000000Z.json"),
        {"verdict": "SOMETHING_PASS", "api_spend_usd": 0, "paid_api_surface_used": False},
    )

    target_path = _write_json(
        os.path.join(receipts, "family", "superseded-claim-20260622T000000Z.json"),
        {"verdict": "PASS_CLASS_FAKE", "claim": "a receipt that will be VOID-superseded"},
    )

    _write_json(
        os.path.join(receipts, "family", "superseded-claim-VOID-20260707T000000Z.json"),
        {
            "ticket": "TEST-VOID-358",
            "verdict": "VOID",
            # self-declares zero-cost like any other governance-text receipt would
            # (a VOID receipt is hand-authored prose, same class as the scanner's
            # own manually_authored convention row) -- keeps this fixture focused
            # on the supersession-exclusion mechanism itself, not on annex coverage.
            "api_spend_usd": 0,
            "paid_api_surface_used": False,
            "supersedes": [{"filename": "superseded-claim-20260622T000000Z.json", "sha256": void_sha}],
            "reason": "test fixture supersession",
            "cites": [],
        },
    )

    os.makedirs(os.path.join(tmpdir, "scripts"), exist_ok=True)
    return tmpdir, target_path


def test_probe_excludes_superseded_receipt_with_disclosed_reason():
    # build sandbox with a placeholder sha, then rewrite with the real one below
    tmpdir, target_path = _make_sandbox(void_sha="placeholder")
    real_sha = _sha256_of(target_path)
    # rewrite the VOID receipt with the real sha now that we know it
    _write_json(
        os.path.join(tmpdir, "receipts", "family", "superseded-claim-VOID-20260707T000000Z.json"),
        {
            "ticket": "TEST-VOID-358",
            "verdict": "VOID",
            "api_spend_usd": 0,
            "paid_api_surface_used": False,
            "supersedes": [{"filename": "superseded-claim-20260622T000000Z.json", "sha256": real_sha}],
            "reason": "test fixture supersession",
            "cites": [],
        },
    )

    mod = _load_cneg1_module(tmpdir, "excl_disclosed")
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            mod.main()
    except SystemExit:
        pass
    out = buf.getvalue().strip()

    assert out.startswith("GREEN"), out
    assert "264" not in out  # sanity: this is the tiny sandbox corpus, not the real tree
    assert "VOID-superseded" in out and "issue #353/#358" in out, out
    assert "disclosed not silent" in out, out
    print("[PASS] probe excludes the VOID-superseded receipt and discloses it in the reason text, never silently")


def test_void_receipt_itself_still_counted():
    tmpdir, target_path = _make_sandbox(void_sha="placeholder")
    real_sha = _sha256_of(target_path)
    void_path = os.path.join(tmpdir, "receipts", "family", "superseded-claim-VOID-20260707T000000Z.json")
    _write_json(void_path, {
        "ticket": "TEST-VOID-358",
        "verdict": "VOID",
        "supersedes": [{"filename": "superseded-claim-20260622T000000Z.json", "sha256": real_sha}],
        "reason": "test fixture supersession",
        "cites": [],
    })

    mod = _load_cneg1_module(tmpdir, "void_still_counted")
    decisive_raw = mod._decisive_claim_files()
    decisive, excluded = mod.void_supersession.partition_superseded(decisive_raw, mod.ROOT)

    kept_paths = {p for p, _d, _raw in decisive}
    assert void_path in kept_paths, (void_path, kept_paths)
    excluded_paths = {e["path"] for e in excluded}
    assert "receipts/family/superseded-claim-20260622T000000Z.json" in excluded_paths, excluded
    assert "receipts/family/superseded-claim-VOID-20260707T000000Z.json" not in excluded_paths, excluded
    print("[PASS] the VOID receipt itself remains in the probe's decisive-claim corpus, only its target is excluded")


def test_mismatched_sha_does_not_exclude():
    """The cbase-gpu-verify-VOID live case (PR #350's body): a supersedes
    entry's sha256 refers to something OTHER than the target receipt file's
    own hash (there, the superseded CHECKPOINT's hash). Must not exclude."""
    wrong_sha = "0" * 64
    tmpdir, target_path = _make_sandbox(void_sha=wrong_sha)

    mod = _load_cneg1_module(tmpdir, "mismatch_no_exclude")
    decisive_raw = mod._decisive_claim_files()
    decisive, excluded = mod.void_supersession.partition_superseded(decisive_raw, mod.ROOT)

    kept_paths = {p for p, _d, _raw in decisive}
    assert any(p.endswith("superseded-claim-20260622T000000Z.json") for p in kept_paths), kept_paths
    assert excluded == [], excluded

    # And the end-to-end probe treats it as an ordinary undeclared receipt
    # (uncovered, since no annex is present in this sandbox) -- RED, not a
    # silent pass-through.
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            mod.main()
    except SystemExit:
        pass
    out = buf.getvalue().strip()
    assert out.startswith("RED"), out
    assert "VOID-superseded" not in out, out
    print("[PASS] a supersedes entry whose sha256 does not match the on-disk file excludes nothing "
          "(the cbase-checkpoint-sha case) -- probe correctly stays RED on the uncovered receipt")


if __name__ == "__main__":
    test_probe_excludes_superseded_receipt_with_disclosed_reason()
    test_void_receipt_itself_still_counted()
    test_mismatched_sha_does_not_exclude()
    print("\n[SUCCESS] All tests passed!")
