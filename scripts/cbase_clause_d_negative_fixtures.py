#!/usr/bin/env python3
"""cbase_clause_d_negative_fixtures.py — negative fixtures for the falsifier
cure on PR #799 (issue #785 C-BASE clause (d) hardening, 2026-07-11).

ROUND 2 (external falsifier, 2026-07-11) rebuilt this file after the
falsifier EXECUTED fixture_artifact_replaced() directly against round-1's
version (head 23b87a3) and proved it structurally ALWAYS-RED for the wrong
reason: every scratch tree wrote a grow/evidence receipt but never an owned
seed-checkpoint receipt+manifest+model satisfying clause (a)/(c), so BOTH
the mismatch case and the correct-hash POSITIVE control printed the same
"0 owned-pretrain candidates ... CHK clause (a)/(c) unmet" RED line -- the
fixture never actually reached clause (d)'s evaluation at all, positive or
negative. Every fixture below now lays down a real owned-seed carrier via
_write_owned_seed_carrier() FIRST, so a flip is decisive about the thing
each fixture claims to test, not an artifact of an unrelated unmet clause.
(Verified by direct read of ember_totality/test_c_base.py's clause-(a)/(c)
loop, 2026-07-11: OWNED_PRETRAIN_MARKERS substring match against the
receipt's flattened text, last_checkpoint/checkpoint/resume_checkpoint
field, DEAD_LINEAGE/BORROWED_MARKERS exclusion, then a real hash-verify of
manifest.json's files["model.pt"] claim against the on-disk model.pt bytes
-- every field this module's _write_owned_seed_carrier() constructs.)

Six findings total across both rounds, all covered here:
  (a)/(b) artifact-absent     — receipt claims a grown_checkpoint path +
                                 grown_model_pt_sha256, no file exists there.
  (a)/(b) artifact-replaced   — on-disk bytes hash-mismatch the receipt's
                                 claim (simulated substitution/corruption).
  round2-4 manifest-absent     — grown_checkpoint_evidence.manifest_path
                                 names a file that does not exist.
  round2-4 manifest-replaced   — the manifest file exists but its bytes
                                 don't hash-match manifest_sha256.
  round2-4 manifest-incoherent — the manifest's bytes DO hash-match, but
                                 its internal content disagrees with the
                                 receipt (files["model.pt"] != the claimed
                                 top-level hash), or its source lineage
                                 (grown_from.model_pt_sha256) doesn't trace
                                 back to the owned seed, or its arch block
                                 is missing required keys.
  (c)     unused-key-deleted   — check_state_dict_load / check_mtp_keyset
                                 (cbase_grow_clause_d_dryrun.py) exercised
                                 directly with a synthetic dropped mtp_heads
                                 key.
  round2-5 unused-key-corrupted — check_mtp_tensor_values exercised
                                 directly with a synthetic mtp_heads tensor
                                 that keeps its KEY NAME but has a corrupted
                                 VALUE in the "replay" state dict -- proves
                                 the tensor-value check catches what the
                                 keyset-only check (above) structurally
                                 cannot.

Each fixture also runs (or, for the pure-function cases, calls) a POSITIVE
control (the same shape, uncorrupted) to prove the harness isn't trivially
always-red / always-raising.

Pure Python + hashlib + subprocess (only fixture_unused_key_corrupted needs
torch, for real tensors) -- no GPU beyond CPU tensor ops. UNEXECUTED as
authored: per the coordinator's binding execution protocol (round 2,
2026-07-11), this file is committed but NOT RUN. It runs only inside the
coordinator's granted execution slot (CPU-only, scratch-root, <=15 min),
after which the raw PASS/FAIL output belongs in the PR body verbatim.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

INVARIANT_SHA256 = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"
SHA_CONVENTION = "sha256 over on-disk raw bytes (binary read, no line-ending normalization)"


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _write_bytes_and_hash(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return _sha256_bytes(data)


def _write_owned_seed_carrier(root: Path) -> dict:
    """[falsifier round 2, finding 3] Lay down a VALID clause-(a)/(c)
    satisfying owned checkpoint carrier: a receipt (OWNED_PRETRAIN_MARKERS
    hit via "cbase"/"pretrain"/"from-scratch"; no DEAD_LINEAGE/BORROWED
    marker text) + manifest.json + model.pt, hash-coherent, under
    <root>/models/cbase-negctrl/seed/. Without this, clause (d)'s
    evaluation is never reached at all -- see module docstring."""
    seed_dir = root / "models" / "cbase-negctrl" / "seed"
    seed_bytes = b"OWNED-SEED-CHECKPOINT-BYTES-PLACEHOLDER-NEGCTRL"
    seed_sha = _write_bytes_and_hash(seed_dir / "model.pt", seed_bytes)
    (seed_dir / "manifest.json").write_text(
        json.dumps({"files": {"model.pt": seed_sha}}), encoding="utf-8")
    owned_receipt = {
        "ticket": "CBASE-OWNED-PRETRAIN-NEGCTRL",
        "ts": "2026-07-11T20:00:00+00:00",
        "invariant_sha256": INVARIANT_SHA256,
        "sha_convention": SHA_CONVENTION,
        # OWNED_PRETRAIN_MARKERS hit ("cbase", "from-scratch", "pretrain");
        # no DEAD_LINEAGE ("12c050e7") or BORROWED_MARKERS text present.
        "scope": ("cbase from-scratch pretrain owned checkpoint "
                  "(synthetic negative-fixture carrier, timeshare v0_segment shape)"),
        "last_checkpoint": "models/cbase-negctrl/seed",
        "pass": True, "verdict": "PASS",
    }
    (root / "receipts").mkdir(parents=True, exist_ok=True)
    (root / "receipts" / "owned-pretrain-negctrl.json").write_text(
        json.dumps(owned_receipt), encoding="utf-8")
    return {"seed_model_pt_sha256": seed_sha, "seed_checkpoint_rel": "models/cbase-negctrl/seed"}


def _write_grown_carrier(
    root: Path, tag: str, *, source_lineage_sha: str,
    model_bytes: bytes | None = None,
    write_model: bool = True,
    claimed_model_sha: str | None = None,
    write_manifest: bool = True,
    manifest_bytes_override: bytes | None = None,
    claimed_manifest_sha: str | None = None,
    include_arch: bool = True,
    internal_model_claim_override: str | None = None,
) -> dict:
    """Write a grown-checkpoint carrier under an isolated per-fixture
    directory, with knobs to deliberately corrupt exactly one field under
    test while leaving everything else coherent -- so each fixture proves
    ONE thing. Returns the receipt-side fields (grown_checkpoint,
    grown_model_pt_sha256, grown_checkpoint_evidence) ready to merge into
    a base receipt dict.

      write_model=False               -- artifact-absent (model.pt never
                                          written; claimed_model_sha still
                                          required by the caller).
      claimed_model_sha                -- override the RECEIPT's top-level
                                          grown_model_pt_sha256 claim
                                          (None = the real hash -- correct).
      write_manifest=False             -- manifest-absent.
      manifest_bytes_override          -- write these exact bytes as the
                                          manifest file (None = build a
                                          coherent manifest from the other
                                          kwargs).
      claimed_manifest_sha             -- override the RECEIPT's
                                          grown_checkpoint_evidence.
                                          manifest_sha256 claim (None = the
                                          real hash of whatever bytes were
                                          written -- correct).
      include_arch=False               -- manifest's arch block omitted
                                          entirely (incoherence case).
      internal_model_claim_override    -- override the MANIFEST's own
                                          files["model.pt"] value (None =
                                          the real model hash -- coherent
                                          with the receipt's top-level
                                          claim).
    """
    grown_dir = root / "models" / "cbase-negctrl" / f"grown-{tag}"
    if model_bytes is None:
        model_bytes = f"GROWN-CHECKPOINT-BYTES-{tag}".encode("utf-8")
    if write_model:
        real_model_sha = _write_bytes_and_hash(grown_dir / "model.pt", model_bytes)
    else:
        real_model_sha = _sha256_bytes(model_bytes)  # never written to disk

    manifest_obj = {
        "files": {"model.pt": internal_model_claim_override
                  if internal_model_claim_override is not None else real_model_sha},
        "grown_from": {"model_pt_sha256": source_lineage_sha},
    }
    if include_arch:
        manifest_obj["arch"] = {"hidden": 8, "layers": 1, "heads": 1, "vocab": 32, "intermediate": 16}

    real_manifest_bytes = (manifest_bytes_override if manifest_bytes_override is not None
                            else json.dumps(manifest_obj).encode("utf-8"))
    manifest_path = grown_dir / "manifest.json"
    if write_manifest:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_bytes(real_manifest_bytes)
    real_manifest_sha = _sha256_bytes(real_manifest_bytes)

    return {
        "grown_checkpoint": f"models/cbase-negctrl/grown-{tag}/model.pt",
        "grown_model_pt_sha256": claimed_model_sha if claimed_model_sha is not None else real_model_sha,
        "grown_checkpoint_evidence": {
            "path": f"models/cbase-negctrl/grown-{tag}/model.pt",
            "model_pt_sha256": claimed_model_sha if claimed_model_sha is not None else real_model_sha,
            "manifest_path": f"models/cbase-negctrl/grown-{tag}/manifest.json",
            "manifest_sha256": claimed_manifest_sha if claimed_manifest_sha is not None else real_manifest_sha,
        },
    }


def _evidence_receipt(name: str) -> dict:
    return {
        "ticket": "CBASE-GROW-CLAUSE-D-OP-VERIFY",
        "ts": "2026-07-11T20:00:00+00:00",
        "invariant_sha256": INVARIANT_SHA256,
        "sha_convention": SHA_CONVENTION,
        "verdict": "PASS",
    }


def _base_pass_receipt(grown_fields: dict, evidence_name: str) -> dict:
    """Minimal synthetic clause-(d)-satisfying receipt shape (mirrors the
    real schema cbase_grow_clause_d_dryrun.py emits, round 2). grown_fields
    comes from _write_grown_carrier -- boolean keys below are the
    GROW_OP_MARKERS / GROW_REPLAY_MARKERS this probe boolean-gate-matches
    on key NAME with value True (verified against test_c_base.py's
    _marker_satisfied / GROW_OP_MARKERS / GROW_REPLAY_MARKERS lists)."""
    r = {
        "ticket": "CBASE-GROW-CLAUSE-D-DRYRUN",
        "ts": "2026-07-11T20:00:00+00:00",
        "invariant_sha256": INVARIANT_SHA256,
        "sha_convention": SHA_CONVENTION,
        "grow-operator": True, "grow_dry_run": True, "net2net": True,
        "pre_grow": True, "post_grow": True, "replays": True,
        "replay_across_shape": True,
        "grow_operator_evidence": f"receipts/{evidence_name}",
        "api_spend_usd": 0, "paid_api_surface_used": False,
        "invalid_tokens_present": [],
        "pass": True, "verdict": "PASS",
    }
    r.update(grown_fields)
    return r


def _write_scratch_receipts(root: Path, tag: str, grown_fields: dict) -> None:
    (root / "receipts").mkdir(parents=True, exist_ok=True)
    evidence_name = f"grow-op-verify-negctrl-{tag}.json"
    (root / "receipts" / evidence_name).write_text(
        json.dumps(_evidence_receipt(evidence_name)), encoding="utf-8")
    (root / "receipts" / f"grow-operator-dryrun-negctrl-{tag}.json").write_text(
        json.dumps(_base_pass_receipt(grown_fields, evidence_name)), encoding="utf-8")


def _run_probe(scratch_root: Path) -> str:
    """Invoke test_c_base.py against an isolated tree; return the printed
    RED/GREEN line (stdout, single line expected). UNEXECUTED by this
    module at authoring time -- only called from main(), which only runs
    under `python cbase_clause_d_negative_fixtures.py` directly, never on
    import."""
    env = dict(os.environ)
    env["EMBER_TOTALITY_ROOT"] = str(scratch_root)
    env["EMBER_ARTIFACT_ROOT"] = str(scratch_root)
    probe = REPO / "scripts" / "ember_totality" / "test_c_base.py"
    out = subprocess.run([sys.executable, str(probe)], cwd=str(REPO), env=env,
                          capture_output=True, text=True, timeout=60)
    return out.stdout.strip()


def _scratch_case(tag: str, **grown_kwargs) -> tuple[tempfile.TemporaryDirectory, str]:
    """Build one complete isolated scratch tree: owned seed carrier + a
    grown carrier per grown_kwargs + the two clause-(d) receipts. Returns
    (tempdir_context, probe_line) -- the caller owns the
    TemporaryDirectory context (use it as a `with` block), this just
    fills it in and runs the probe."""
    td = tempfile.TemporaryDirectory(prefix=f"cbase-negctrl-{tag}-")
    root = Path(td.name)
    seed = _write_owned_seed_carrier(root)
    grown_fields = _write_grown_carrier(root, tag, source_lineage_sha=seed["seed_model_pt_sha256"],
                                         **grown_kwargs)
    _write_scratch_receipts(root, tag, grown_fields)
    line = _run_probe(root)
    return td, line


# Exact substring emitted by test_c_base.py's clause-(d)-UNMET RED line
# (owned checkpoint accepted, grow-op receipt rejected) -- verified by
# direct read, 2026-07-11: "...but CHK clause (d) is UNMET -- no
# grow-operator dry-run receipt produces...". Distinguishes a genuine
# clause-(d) flip from a clause-(a)/(c)-unmet RED (the exact defect finding
# 3 proved: "0 owned-pretrain candidates scanned ... CHK clause (a)/(c)
# unmet") -- a fixture is only decisive if it reaches the CORRECT clause.
CLAUSE_D_UNMET_MARK = "CHK clause (d)"


def fixture_artifact_absent() -> bool:
    """[(a)/(b)] Receipt claims a grown checkpoint + hash; the file
    genuinely does not exist. Expect RED, and specifically clause-(d)-RED
    (owned seed carrier present and correct, so the reason must NOT be
    "0 owned-pretrain candidates")."""
    td, line = _scratch_case("absent", write_model=False,
                              claimed_model_sha="0" * 64)
    with td:
        flipped = line.startswith("RED") and CLAUSE_D_UNMET_MARK in line
        print(f"FIXTURE_1_ARTIFACT_ABSENT_{'PASS' if flipped else 'FAIL'} probe_line={line!r}")
        return flipped


def fixture_artifact_replaced() -> bool:
    """[(a)/(b)] Grown checkpoint file exists, but its real bytes hash does
    NOT match the receipt's claimed grown_model_pt_sha256. Expect
    clause-(d)-RED. Positive control (this fixture's other leg): identical
    tree shape with the CORRECT hash and a fully coherent manifest -> GREEN.
    """
    ok = True

    td, line = _scratch_case("mismatch",
                              claimed_model_sha=_sha256_bytes(b"DIFFERENT-BYTES-SUBSTITUTED-ARTIFACT"))
    with td:
        flipped = line.startswith("RED") and CLAUSE_D_UNMET_MARK in line
        print(f"FIXTURE_2_ARTIFACT_REPLACED_{'PASS' if flipped else 'FAIL'} probe_line={line!r}")
        ok = ok and flipped

    td, line = _scratch_case("positive")
    with td:
        flipped = line.startswith("GREEN")
        print(f"FIXTURE_2b_POSITIVE_CONTROL_ALL_COHERENT_{'PASS' if flipped else 'FAIL'} probe_line={line!r}")
        ok = ok and flipped

    return ok


def fixture_manifest_absent() -> bool:
    """[round2-4] Manifest file never written; model.pt itself is correct
    and hash-matches. Expect clause-(d)-RED (the manifest-existence leg of
    the coherence check, not the model-hash leg, since the model hash on
    its own would otherwise pass)."""
    td, line = _scratch_case("manifest-absent", write_manifest=False)
    with td:
        flipped = line.startswith("RED") and CLAUSE_D_UNMET_MARK in line
        print(f"FIXTURE_3_MANIFEST_ABSENT_{'PASS' if flipped else 'FAIL'} probe_line={line!r}")
        return flipped


def fixture_manifest_replaced() -> bool:
    """[round2-4] Manifest file exists, but its real on-disk bytes do not
    hash-match the receipt's claimed manifest_sha256 (simulated
    substitution of the manifest itself, independent of the model.pt
    check). Expect clause-(d)-RED."""
    td, line = _scratch_case("manifest-replaced",
                              claimed_manifest_sha=_sha256_bytes(b"DIFFERENT-MANIFEST-BYTES"))
    with td:
        flipped = line.startswith("RED") and CLAUSE_D_UNMET_MARK in line
        print(f"FIXTURE_4_MANIFEST_REPLACED_{'PASS' if flipped else 'FAIL'} probe_line={line!r}")
        return flipped


def fixture_manifest_incoherent() -> bool:
    """[round2-4] Three independent incoherence sub-cases, each with the
    manifest's OWN bytes hash-matching manifest_sha256 (so the "manifest
    exists and matches its claimed hash" leg alone would pass) but the
    manifest's INTERNAL content disagreeing with the receipt or the owned
    seed lineage:
      (a) manifest.files["model.pt"] != the receipt's top-level
          grown_model_pt_sha256 (the receipt disagrees with itself);
      (b) manifest.grown_from.model_pt_sha256 != the owned seed's real
          hash (the grow claims to descend from a DIFFERENT seed than the
          one clause (a)/(c) actually verified);
      (c) manifest.arch is missing entirely (existence/shape check).
    Each must independently flip to clause-(d)-RED."""
    ok = True

    td, line = _scratch_case("incoherent-model-claim",
                              internal_model_claim_override=_sha256_bytes(b"WRONG-INTERNAL-CLAIM"))
    with td:
        flipped = line.startswith("RED") and CLAUSE_D_UNMET_MARK in line
        print(f"FIXTURE_5a_MANIFEST_INTERNAL_MODEL_CLAIM_MISMATCH_{'PASS' if flipped else 'FAIL'} "
              f"probe_line={line!r}")
        ok = ok and flipped

    # Lineage sub-case built by hand (needs a WRONG source_lineage_sha, not
    # the real seed's -- _scratch_case always wires the real one).
    td_lineage = tempfile.TemporaryDirectory(prefix="cbase-negctrl-incoherent-lineage-")
    with td_lineage as root_name:
        root = Path(root_name)
        _write_owned_seed_carrier(root)  # real seed exists and is correct
        grown_fields = _write_grown_carrier(
            root, "incoherent-lineage", source_lineage_sha=_sha256_bytes(b"WRONG-SEED-LINEAGE"))
        _write_scratch_receipts(root, "incoherent-lineage", grown_fields)
        line = _run_probe(root)
        flipped = line.startswith("RED") and CLAUSE_D_UNMET_MARK in line
        print(f"FIXTURE_5b_MANIFEST_SOURCE_LINEAGE_MISMATCH_{'PASS' if flipped else 'FAIL'} "
              f"probe_line={line!r}")
        ok = ok and flipped

    td, line = _scratch_case("incoherent-no-arch", include_arch=False)
    with td:
        flipped = line.startswith("RED") and CLAUSE_D_UNMET_MARK in line
        print(f"FIXTURE_5c_MANIFEST_ARCH_MISSING_{'PASS' if flipped else 'FAIL'} probe_line={line!r}")
        ok = ok and flipped

    return ok


def fixture_unused_key_deleted() -> bool:
    """[(c)] Exercises the REAL check_state_dict_load / check_mtp_keyset
    functions from cbase_grow_clause_d_dryrun.py (imported, not
    re-described) with synthetic missing/unexpected/keyset inputs
    representing a dropped mtp_heads key. Both must raise SystemExit; both
    must pass on the matching uncorrupted shape (positive control)."""
    from cbase_grow_clause_d_dryrun import check_state_dict_load, check_mtp_keyset  # noqa: E402

    ok = True

    try:
        check_state_dict_load("replay", ["mtp_heads.0.weight"], [])
        raised = False
    except SystemExit:
        raised = True
    print(f"FIXTURE_6a_LOAD_STATE_DICT_MTP_KEY_MISSING_{'PASS' if raised else 'FAIL'}")
    ok = ok and raised

    try:
        check_state_dict_load("replay", ["head.weight"], [])
        raised = False
    except SystemExit:
        raised = True
    print(f"FIXTURE_6b_LOAD_STATE_DICT_HEAD_WEIGHT_ALIAS_ALLOWED_{'PASS' if not raised else 'FAIL'}")
    ok = ok and (not raised)

    seed_keys = ["mtp_heads.0.weight", "mtp_heads.1.weight"]
    grown_keys = ["mtp_heads.0.weight", "mtp_heads.1.weight"]
    replay_keys_corrupted = ["mtp_heads.0.weight"]  # one key silently dropped
    try:
        check_mtp_keyset(seed_keys, grown_keys, replay_keys_corrupted)
        raised = False
    except SystemExit:
        raised = True
    print(f"FIXTURE_6c_MTP_KEYSET_DROPPED_KEY_{'PASS' if raised else 'FAIL'}")
    ok = ok and raised

    try:
        result = check_mtp_keyset(seed_keys, grown_keys, list(grown_keys))
        raised = False
        returned_ok = isinstance(result, dict) and result.get("n_mtp_heads_keys") == 2
    except SystemExit:
        raised = True
        returned_ok = False
    print(f"FIXTURE_6d_MTP_KEYSET_MATCHING_POSITIVE_CONTROL_{'PASS' if (not raised and returned_ok) else 'FAIL'}")
    ok = ok and (not raised) and returned_ok

    return ok


def fixture_unused_key_corrupted() -> bool:
    """[round2-5] Exercises the REAL check_mtp_tensor_values function
    directly with synthetic tensors: a "replay" state dict that keeps the
    SAME mtp_heads KEY NAME (so fixture_unused_key_deleted's keyset check
    would find nothing wrong) but has a corrupted (zeroed) VALUE. Proves
    the tensor-value check catches what the keyset-only check structurally
    cannot -- exactly the falsifier's finding (5) scenario. Positive
    control: values matching within the bf16-round-trip tolerance ->
    must NOT raise."""
    import torch
    from cbase_grow_clause_d_dryrun import check_mtp_tensor_values  # noqa: E402

    ok = True
    key = "mtp_heads.0.weight"
    real_tensor = torch.arange(16, dtype=torch.float32).reshape(4, 4)

    # (a) seed vs grown diverge (net2net must never touch mtp_heads) -> raise.
    sd = {key: real_tensor}
    grown_sd_corrupted = {key: real_tensor.clone() * 0.0}  # zeroed at the grown stage
    reload_sd = {key: real_tensor.clone()}
    try:
        check_mtp_tensor_values(sd, grown_sd_corrupted, reload_sd, [key])
        raised = False
    except SystemExit:
        raised = True
    print(f"FIXTURE_7a_MTP_TENSOR_SEED_GROWN_DIVERGE_{'PASS' if raised else 'FAIL'}")
    ok = ok and raised

    # (b) seed==grown (correct), but replay is zeroed (the exact "key name
    # survives, value corrupted" scenario the keyset-only check misses).
    grown_sd_ok = {key: real_tensor.clone()}
    reload_sd_corrupted = {key: real_tensor.clone() * 0.0}
    try:
        check_mtp_tensor_values(sd, grown_sd_ok, reload_sd_corrupted, [key])
        raised = False
    except SystemExit:
        raised = True
    print(f"FIXTURE_7b_MTP_TENSOR_REPLAY_VALUE_CORRUPTED_{'PASS' if raised else 'FAIL'}")
    ok = ok and raised

    # (c) positive control: everything genuinely matches (bit-exact, well
    # within the bf16-round-trip tolerance) -> must NOT raise.
    reload_sd_ok = {key: real_tensor.clone()}
    try:
        result = check_mtp_tensor_values(sd, grown_sd_ok, reload_sd_ok, [key])
        raised = False
        returned_ok = isinstance(result, dict) and result.get("n_checked") == 1
    except SystemExit:
        raised = True
        returned_ok = False
    print(f"FIXTURE_7c_MTP_TENSOR_POSITIVE_CONTROL_{'PASS' if (not raised and returned_ok) else 'FAIL'}")
    ok = ok and (not raised) and returned_ok

    return ok


def main() -> int:
    results = {
        "artifact_absent": fixture_artifact_absent(),
        "artifact_replaced_and_positive_control": fixture_artifact_replaced(),
        "manifest_absent": fixture_manifest_absent(),
        "manifest_replaced": fixture_manifest_replaced(),
        "manifest_incoherent": fixture_manifest_incoherent(),
        "unused_key_deleted": fixture_unused_key_deleted(),
        "unused_key_corrupted": fixture_unused_key_corrupted(),
    }
    all_ok = all(results.values())
    print(f"\n{'CBASE_CLAUSE_D_NEGATIVE_FIXTURES_ALL_PASS' if all_ok else 'CBASE_CLAUSE_D_NEGATIVE_FIXTURES_FAIL'} "
          f"results={results}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
