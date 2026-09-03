#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""TDD: gh issue #353 -- durable attestation + VOID-supersession semantics for
the C(-1) spend-annex generator (spend_annex_scan.py).

Incident this fixes (2026-07-07): PR #348's "17 of 18 attested" coverage was
produced by a throwaway build-time helper (scratch/attest_extend.py, never
committed) that hand-stamped evidence_class directly onto a frozen annex JSON
snapshot, without ever teaching the real generator's own classification tables
about those 17 receipts. Re-running the actual generator (PR #350's own
verification) regressed the count right back from 1 to 19 unresolvable -- the
attestation was real and evidence-backed as a one-time annotation, but not
durable across a future regeneration. This test file locks in the two
mechanisms that make coverage durable:

  (1) Attestation sidecars (receipts/spend-annex/attestations/*.json): a
      target_path + a PINNED target_sha256 + real evidence pointers. The
      generator itself loads these, verifies the pin against the target's
      CURRENT on-disk sha256, and re-runs its own content scan on the
      target's raw text -- content-dirty ALWAYS overrides the attestation,
      a stale pin ALWAYS rejects it. Nothing is ever hand-stamped onto an
      output snapshot again; every regeneration re-derives the same result.

  (2) VOID-supersession semantics: a receipt named in a VOID receipt's
      `supersedes` list (matched by basename + sha256) is excluded from the
      decisive-claim classification set entirely (excluded_superseded,
      listed honestly). The VOID receipt itself stays IN the set, classified
      via a new structural rule (verdict=="VOID" + non-empty supersedes) as
      manually-authored governance text, content-scanned like everything else.

Amendment (2026-07-08, gh issue #428): even a durable, correctly-pinned attestation
can drift AFTER the fact -- 3 already-attested receipts were redacted (a custody pass
stripping founder-scoped local paths) hours after their sidecars were written, so a
fresh regen's direct pin check correctly rejected the now-stale hash and 3 previously-
covered rows silently regressed to unresolvable. The receipt itself self-documents the
mutation (a `redaction` block naming `original_sha256`), so the generator now also
accepts a pin match against THAT field -- a redaction-chain match, distinct from a
direct match, disclosed via `attestation_pin_match` on the row -- while the content
re-scan still always runs against the receipt's CURRENT (post-redaction) text. The
tests below (test_attestation_redaction_chain_*) lock this in without weakening the
content-dirty-always-overrides invariant or accepting an unrelated redaction as a
free pass.
"""

import hashlib
import importlib.util
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..', '..'))


def _load_scanner_module(tmp_root, unique_suffix):
    """Import a FRESH copy of spend_annex_scan.py (and its test_c_neg1
    dependency) bound to tmp_root via EMBER_TOTALITY_ROOT. Both modules
    resolve ROOT at import time from that env var, so a stale cached module
    would silently keep pointing at whatever root a prior test set -- a
    unique module name + fresh exec_module call per test forces a real
    re-import every time, always against the CURRENT tmp_root."""
    os.environ["EMBER_TOTALITY_ROOT"] = tmp_root

    cneg1_name = f"test_c_neg1_{unique_suffix}"
    cneg1_spec = importlib.util.spec_from_file_location(
        cneg1_name, os.path.join(REPO_ROOT, "scripts", "ember_totality", "test_c_neg1.py"))
    cneg1_mod = importlib.util.module_from_spec(cneg1_spec)
    sys.modules[cneg1_name] = cneg1_mod
    cneg1_spec.loader.exec_module(cneg1_mod)

    # spend_annex_scan.py does `import test_c_neg1 as c_neg1` by bare module
    # name -- pre-register our freshly-bound instance under that exact key so
    # the bare import resolves to THIS sandboxed module, not any other copy.
    sys.modules["test_c_neg1"] = cneg1_mod

    scanner_name = f"spend_annex_scan_{unique_suffix}"
    scanner_spec = importlib.util.spec_from_file_location(
        scanner_name, os.path.join(REPO_ROOT, "scripts", "ember_totality", "spend_annex_scan.py"))
    scanner_mod = importlib.util.module_from_spec(scanner_spec)
    sys.modules[scanner_name] = scanner_mod
    scanner_spec.loader.exec_module(scanner_mod)
    return scanner_mod, cneg1_mod


def _write_json(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(content, fh, indent=2)
    return path


def _sha256_of(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _make_sandbox():
    """Minimal sandbox tree: one plain decisive receipt with no resolvable
    generator (the attestation target), a second decisive receipt plus a
    VOID receipt superseding it, and an empty scripts/ dir (required by the
    tree-wide scan glob)."""
    tmpdir = tempfile.mkdtemp()
    receipts = os.path.join(tmpdir, "receipts")

    target_path = _write_json(
        os.path.join(receipts, "hand-run-probe-20260707T000000Z.json"),
        {"verdict": "PASS", "claim": "a hand-run probe with no generating script recorded"},
    )

    superseded_path = _write_json(
        os.path.join(receipts, "family", "superseded-claim-20260622T000000Z.json"),
        {"verdict": "PASS_CLASS_FAKE", "claim": "a receipt that will be VOID-superseded"},
    )
    superseded_sha = _sha256_of(superseded_path)

    _write_json(
        os.path.join(receipts, "family", "superseded-claim-VOID-20260707T000000Z.json"),
        {
            "ticket": "TEST-VOID",
            "verdict": "VOID",
            "supersedes": [{"filename": "superseded-claim-20260622T000000Z.json", "sha256": superseded_sha}],
            "reason": "test fixture supersession",
            "cites": [],
        },
    )

    os.makedirs(os.path.join(tmpdir, "scripts"), exist_ok=True)
    return tmpdir, target_path


def _write_sidecar(tmpdir, target_sha):
    sidecar_path = os.path.join(tmpdir, "receipts", "spend-annex", "attestations", "hand-run-probe.json")
    _write_json(sidecar_path, {
        "target_path": "receipts/hand-run-probe-20260707T000000Z.json",
        "target_sha256": target_sha,
        "evidence_class": "generator_absent_content_clean",
        "evidence": "test fixture evidence pointer (fixture-only, not a real citation)",
        "cites": ["receipts/hand-run-probe-20260707T000000Z.json"],
    })
    return sidecar_path


def test_attestation_sidecar_covers_when_pin_and_content_are_clean():
    tmpdir, target_path = _make_sandbox()
    target_sha = _sha256_of(target_path)
    _write_sidecar(tmpdir, target_sha)

    mod, _ = _load_scanner_module(tmpdir, "attest_clean")
    result = mod.main(out_path=None)

    row = next(r for r in result["rows"] if r["path"] == "receipts/hand-run-probe-20260707T000000Z.json")
    assert row["evidence_class"] == "generator_absent_content_clean", row
    assert row.get("evidence_subtype") == "attested_sidecar", row
    assert row.get("attestation_sidecar", "").endswith("hand-run-probe.json"), row
    assert result["counts"]["attested_via_sidecar"] == 1, result["counts"]
    print("[PASS] attestation sidecar covers a receipt when pin + content are both clean")


def test_attestation_sidecar_rejected_on_sha_pin_mismatch():
    tmpdir, _target_path = _make_sandbox()
    stale_sha = "0" * 64  # deliberately wrong -- simulates the target mutating after attestation
    _write_sidecar(tmpdir, stale_sha)

    mod, _ = _load_scanner_module(tmpdir, "attest_mismatch")
    result = mod.main(out_path=None)

    row = next(r for r in result["rows"] if r["path"] == "receipts/hand-run-probe-20260707T000000Z.json")
    assert row["evidence_class"] == "unresolvable", row
    assert "does NOT match" in row["notes"] or "REJECTED" in row["notes"], row
    print("[PASS] attestation sidecar with a stale sha256 pin is rejected, row stays unresolvable")


def test_content_dirty_overrides_attestation():
    tmpdir, target_path = _make_sandbox()
    # Overwrite the target so its own raw content trips the paid-client scan
    # (a real import statement, not a bare provider-name mention).
    with open(target_path, "w", encoding="utf-8") as fh:
        json.dump({"verdict": "PASS", "claim": "script text follows",
                    "embedded_source_sample": "call openai.OpenAI() to init the client"}, fh, indent=2)
    target_sha = _sha256_of(target_path)
    _write_sidecar(tmpdir, target_sha)

    mod, _ = _load_scanner_module(tmpdir, "attest_dirty")
    result = mod.main(out_path=None)

    row = next(r for r in result["rows"] if r["path"] == "receipts/hand-run-probe-20260707T000000Z.json")
    assert row["evidence_class"] == "unresolvable", row
    assert row.get("content_scan_hits", {}).get("client_patterns"), row
    assert result["counts"]["attested_via_sidecar"] == 0, result["counts"]
    print("[PASS] content-dirty target overrides a sha-pin-valid attestation sidecar")


def _write_redacted_target(tmpdir, original_content):
    """Write the sandbox's target receipt with a `redaction` block recording the
    PRE-redaction sha256, mirroring the real 2026-07-07 custody redaction shape
    (receipts/cbase-gpu-verify-20260707T064453Z.json etc.) that gh issue #428
    disclosed: a receipt attested, then legitimately mutated afterward by a
    redaction pass, invalidating the sidecar's original pin."""
    target_path = os.path.join(tmpdir, "receipts", "hand-run-probe-20260707T000000Z.json")
    original_sha = _sha256_of(target_path) if os.path.exists(target_path) else None
    if original_sha is None:
        original_sha = hashlib.sha256(json.dumps(original_content, indent=2).encode("utf-8")).hexdigest()
    redacted_content = dict(original_content)
    redacted_content["redaction"] = {
        "redacted_fields": ["eval_config.data_source"],
        "original_sha256": original_sha,
        "reason": "test fixture: founder-scoped local path redaction",
        "redaction_ts": "2026-07-07T18:48:51.000000Z",
    }
    _write_json(target_path, redacted_content)
    return target_path


def test_attestation_redaction_chain_pin_covers_when_content_clean():
    """gh issue #428: an attestation pinned to a receipt's PRE-redaction hash
    still resolves the row -- via the redaction-chain fallback, not the direct
    pin -- because the receipt's own `redaction.original_sha256` field matches
    the sidecar's target_sha256, and the CURRENT (redacted) content re-scans
    clean."""
    tmpdir, target_path = _make_sandbox()
    pre_redaction_sha = _sha256_of(target_path)
    _write_sidecar(tmpdir, pre_redaction_sha)  # sidecar pinned to the OLD hash
    _write_redacted_target(tmpdir, {"verdict": "PASS", "claim": "a hand-run probe with no generating script recorded"})

    mod, _ = _load_scanner_module(tmpdir, "redaction_chain_clean")
    result = mod.main(out_path=None)

    row = next(r for r in result["rows"] if r["path"] == "receipts/hand-run-probe-20260707T000000Z.json")
    assert row["evidence_class"] == "generator_absent_content_clean", row
    assert row.get("attestation_pin_match") == "redaction_chain", row
    assert "redaction" in row["notes"].lower(), row
    assert result["counts"]["attested_via_sidecar"] == 1, result["counts"]
    print("[PASS] redaction-chain pin covers a receipt redacted after attestation, content clean")


def test_attestation_redaction_chain_content_dirty_still_rejected():
    """The redaction-chain fallback must NOT weaken the content-dirty override:
    a receipt whose CURRENT (post-redaction) text trips the paid-client scan
    is rejected exactly like the direct-pin path."""
    tmpdir, target_path = _make_sandbox()
    pre_redaction_sha = _sha256_of(target_path)
    _write_sidecar(tmpdir, pre_redaction_sha)
    _write_redacted_target(tmpdir, {
        "verdict": "PASS", "claim": "script text follows",
        "embedded_source_sample": "call openai.OpenAI() to init the client",
    })

    mod, _ = _load_scanner_module(tmpdir, "redaction_chain_dirty")
    result = mod.main(out_path=None)

    row = next(r for r in result["rows"] if r["path"] == "receipts/hand-run-probe-20260707T000000Z.json")
    assert row["evidence_class"] == "unresolvable", row
    assert row.get("content_scan_hits", {}).get("client_patterns"), row
    assert result["counts"]["attested_via_sidecar"] == 0, result["counts"]
    print("[PASS] redaction-chain pin still rejected when the CURRENT content is dirty")


def test_attestation_redaction_original_sha_mismatch_still_rejected():
    """A `redaction.original_sha256` that does NOT match the sidecar's pin is
    not a free pass -- neither the direct nor the redaction-chain path fires,
    and the row stays unresolvable (guards against the fallback becoming a
    bare exemption)."""
    tmpdir, target_path = _make_sandbox()
    stale_sha = "1" * 64  # neither the current hash nor a real prior hash
    _write_sidecar(tmpdir, stale_sha)
    redacted_content = {"verdict": "PASS", "claim": "a hand-run probe with no generating script recorded",
                         "redaction": {"redacted_fields": ["x"], "original_sha256": "2" * 64,
                                       "reason": "unrelated redaction", "redaction_ts": "2026-07-07T00:00:00Z"}}
    _write_json(target_path, redacted_content)

    mod, _ = _load_scanner_module(tmpdir, "redaction_chain_mismatch")
    result = mod.main(out_path=None)

    row = next(r for r in result["rows"] if r["path"] == "receipts/hand-run-probe-20260707T000000Z.json")
    assert row["evidence_class"] == "unresolvable", row
    assert "REJECTED" in row["notes"], row
    print("[PASS] a redaction.original_sha256 that doesn't match the sidecar's pin is still rejected")


def test_redaction_chain_regeneration_is_idempotent():
    tmpdir, target_path = _make_sandbox()
    pre_redaction_sha = _sha256_of(target_path)
    _write_sidecar(tmpdir, pre_redaction_sha)
    _write_redacted_target(tmpdir, {"verdict": "PASS", "claim": "a hand-run probe with no generating script recorded"})

    mod1, _ = _load_scanner_module(tmpdir, "redaction_idem_run1")
    result1 = mod1.main(out_path=None)
    mod2, _ = _load_scanner_module(tmpdir, "redaction_idem_run2")
    result2 = mod2.main(out_path=None)

    assert result1["rows"] == result2["rows"], "rows differ across two identical redaction-chain regenerations"
    print("[PASS] redaction-chain coverage regenerates byte-identically across two runs")


def test_void_supersession_excludes_target_keeps_void_row():
    tmpdir, _target_path = _make_sandbox()

    mod, _ = _load_scanner_module(tmpdir, "void_supersession")
    result = mod.main(out_path=None)

    excluded_paths = {r["path"] for r in result["excluded_superseded"]}
    assert "receipts/family/superseded-claim-20260622T000000Z.json" in excluded_paths, result["excluded_superseded"]

    row_paths = {r["path"] for r in result["rows"]}
    assert "receipts/family/superseded-claim-20260622T000000Z.json" not in row_paths, row_paths

    void_row = next(r for r in result["rows"]
                     if r["path"] == "receipts/family/superseded-claim-VOID-20260707T000000Z.json")
    assert void_row["evidence_class"] == "generator_absent_content_clean", void_row
    assert void_row.get("evidence_subtype") == "manually_authored", void_row
    print("[PASS] VOID supersession excludes its target and keeps the VOID receipt itself covered")


def test_idempotent_regeneration():
    tmpdir, target_path = _make_sandbox()
    target_sha = _sha256_of(target_path)
    _write_sidecar(tmpdir, target_sha)

    mod1, _ = _load_scanner_module(tmpdir, "idem_run1")
    result1 = mod1.main(out_path=None)
    mod2, _ = _load_scanner_module(tmpdir, "idem_run2")
    result2 = mod2.main(out_path=None)

    assert result1["rows"] == result2["rows"], "rows differ across two identical regenerations"
    assert result1["excluded_superseded"] == result2["excluded_superseded"], \
        "exclusions differ across two identical regenerations"
    assert result1["counts"] == result2["counts"], "counts differ across two identical regenerations"
    print("[PASS] two identical regenerations produce byte-identical rows/exclusions/counts")


if __name__ == "__main__":
    test_attestation_sidecar_covers_when_pin_and_content_are_clean()
    test_attestation_sidecar_rejected_on_sha_pin_mismatch()
    test_content_dirty_overrides_attestation()
    test_attestation_redaction_chain_pin_covers_when_content_clean()
    test_attestation_redaction_chain_content_dirty_still_rejected()
    test_attestation_redaction_original_sha_mismatch_still_rejected()
    test_redaction_chain_regeneration_is_idempotent()
    test_void_supersession_excludes_target_keeps_void_row()
    test_idempotent_regeneration()
    print("\n[SUCCESS] All tests passed!")
