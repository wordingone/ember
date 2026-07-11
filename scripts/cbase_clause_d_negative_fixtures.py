#!/usr/bin/env python3
"""cbase_clause_d_negative_fixtures.py — negative fixtures for the falsifier
cure on PR #799 (issue #785 C-BASE clause (d) hardening, 2026-07-11).

Three findings, three fixtures, each must FLIP THE VERDICT when triggered:

  (a)/(b) artifact-absent    — receipt claims a grown_checkpoint path +
                                grown_model_pt_sha256, but no file exists at
                                that path. test_c_base.py's clause-(d) leg
                                must print RED (never select this receipt).
  (a)/(b) artifact-replaced  — the grown_checkpoint file exists on disk, but
                                its real sha256 does NOT match the receipt's
                                claimed grown_model_pt_sha256 (simulating a
                                corrupted/substituted artifact). Must RED.
  (c)     unused-key-deleted — an mtp_heads key is missing from a
                                load_state_dict result / keyset comparison.
                                check_state_dict_load / check_mtp_keyset
                                (cbase_grow_clause_d_dryrun.py) must raise
                                SystemExit -- exercised as the REAL functions
                                under test, not a re-description of their
                                logic, so this fixture cannot drift from
                                production behavior.

Each fixture also runs a POSITIVE control (the same shape, uncorrupted) to
prove the harness isn't trivially always-red / always-raising.

Pure Python + hashlib + subprocess only. No torch. No GPU. No box-token
contention expected -- but per the standing execution-hold instruction on
this issue, this script is committed UNEXECUTED; run only after the
coordinator's box-slot GO. `python scripts/cbase_clause_d_negative_fixtures.py`
prints one FIXTURE_<n>_<PASS|FAIL> line per fixture and exits nonzero if any
fixture failed to flip as expected.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _base_pass_receipt(grown_ckpt_rel: str, grown_sha: str, evidence_name: str) -> dict:
    """Minimal synthetic clause-(d)-satisfying receipt shape (mirrors the
    real schema cbase_grow_clause_d_dryrun.py emits after the cure)."""
    return {
        "ticket": "CBASE-GROW-CLAUSE-D-DRYRUN",
        "ts": "2026-07-11T20:00:00+00:00",
        "invariant_sha256": "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6",
        "sha_convention": "sha256 over on-disk raw bytes (binary read, no line-ending normalization)",
        "grow-operator": True, "grow_dry_run": True, "net2net": True,
        "pre_grow": True, "post_grow": True, "replays": True,
        "replay_across_shape": True,
        "grow_operator_evidence": f"receipts/{evidence_name}",
        "grown_checkpoint": grown_ckpt_rel,
        "grown_model_pt_sha256": grown_sha,
        "api_spend_usd": 0, "paid_api_surface_used": False,
        "invalid_tokens_present": [],
        "pass": True, "verdict": "PASS",
    }


def _evidence_receipt(name: str) -> dict:
    return {
        "ticket": "CBASE-GROW-CLAUSE-D-OP-VERIFY",
        "ts": "2026-07-11T20:00:00+00:00",
        "invariant_sha256": "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6",
        "sha_convention": "sha256 over on-disk raw bytes (binary read, no line-ending normalization)",
        "verdict": "PASS",
    }


def _run_probe(scratch_root: Path) -> str:
    """Invoke test_c_base.py against an isolated tree; return the printed
    RED/GREEN line (stdout, single line expected)."""
    env = dict(os.environ)
    env["EMBER_TOTALITY_ROOT"] = str(scratch_root)
    env["EMBER_ARTIFACT_ROOT"] = str(scratch_root)
    probe = REPO / "scripts" / "ember_totality" / "test_c_base.py"
    out = subprocess.run([sys.executable, str(probe)], cwd=str(REPO), env=env,
                          capture_output=True, text=True, timeout=60)
    return out.stdout.strip()


def fixture_artifact_absent() -> bool:
    """Receipt claims a grown checkpoint + hash; the file genuinely does not
    exist. Expect RED. (No positive counterpart needed here beyond fixture 2's
    positive control, which shares this fixture's tree shape with the file
    present and correctly hashed.)"""
    with tempfile.TemporaryDirectory(prefix="cbase-negctrl-absent-") as td:
        root = Path(td)
        (root / "receipts").mkdir(parents=True)
        grown_rel = "models/cbase-negctrl/model.pt"
        # deliberately never create models/cbase-negctrl/model.pt
        fake_sha = "0" * 64
        evidence_name = "grow-op-verify-negctrl-absent.json"
        (root / "receipts" / evidence_name).write_text(
            json.dumps(_evidence_receipt(evidence_name)), encoding="utf-8")
        (root / "receipts" / "grow-operator-dryrun-negctrl-absent.json").write_text(
            json.dumps(_base_pass_receipt(grown_rel, fake_sha, evidence_name)), encoding="utf-8")
        line = _run_probe(root)
        flipped = line.startswith("RED")
        print(f"FIXTURE_1_ARTIFACT_ABSENT_{'PASS' if flipped else 'FAIL'} probe_line={line!r}")
        return flipped


def fixture_artifact_replaced() -> bool:
    """Grown checkpoint file exists, but its real bytes hash does NOT match
    the receipt's claimed grown_model_pt_sha256 (simulated substitution/
    corruption). Expect RED. Positive control: same tree shape with the
    CORRECT hash claimed -> expect GREEN (proves the harness can pass)."""
    ok = True
    for correct_hash, tag in ((False, "mismatch"), (True, "positive_control")):
        with tempfile.TemporaryDirectory(prefix=f"cbase-negctrl-replaced-{tag}-") as td:
            root = Path(td)
            (root / "receipts").mkdir(parents=True)
            ckpt_dir = root / "models" / "cbase-negctrl"
            ckpt_dir.mkdir(parents=True)
            model_pt = ckpt_dir / "model.pt"
            real_bytes = b"REAL-GROWN-CHECKPOINT-BYTES-PLACEHOLDER"
            model_pt.write_bytes(real_bytes)
            real_sha = _sha256_bytes(real_bytes)
            claimed_sha = real_sha if correct_hash else _sha256_bytes(b"DIFFERENT-BYTES-SUBSTITUTED-ARTIFACT")
            grown_rel = "models/cbase-negctrl/model.pt"
            evidence_name = f"grow-op-verify-negctrl-{tag}.json"
            (root / "receipts" / evidence_name).write_text(
                json.dumps(_evidence_receipt(evidence_name)), encoding="utf-8")
            (root / "receipts" / f"grow-operator-dryrun-negctrl-{tag}.json").write_text(
                json.dumps(_base_pass_receipt(grown_rel, claimed_sha, evidence_name)), encoding="utf-8")
            line = _run_probe(root)
            if correct_hash:
                flipped = line.startswith("GREEN")
                print(f"FIXTURE_2b_ARTIFACT_HASH_MATCH_POSITIVE_CONTROL_{'PASS' if flipped else 'FAIL'} "
                      f"probe_line={line!r}")
            else:
                flipped = line.startswith("RED")
                print(f"FIXTURE_2_ARTIFACT_REPLACED_{'PASS' if flipped else 'FAIL'} probe_line={line!r}")
            ok = ok and flipped
    return ok


def fixture_unused_key_deleted() -> bool:
    """Exercises the REAL check_state_dict_load / check_mtp_keyset functions
    from cbase_grow_clause_d_dryrun.py (imported, not re-described) with
    synthetic missing/unexpected/keyset inputs representing a dropped
    mtp_heads key. Both must raise SystemExit; both must pass on the
    matching uncorrupted shape (positive control)."""
    from cbase_grow_clause_d_dryrun import check_state_dict_load, check_mtp_keyset  # noqa: E402

    ok = True

    # (i) check_state_dict_load: a real mtp_heads key missing -> must raise.
    try:
        check_state_dict_load("replay", ["mtp_heads.0.weight"], [])
        raised = False
    except SystemExit:
        raised = True
    print(f"FIXTURE_3a_LOAD_STATE_DICT_MTP_KEY_MISSING_{'PASS' if raised else 'FAIL'}")
    ok = ok and raised

    # (ii) positive control: ONLY the known-benign head.weight alias missing
    # -> must NOT raise (proves the check isn't trivially always-red).
    try:
        check_state_dict_load("replay", ["head.weight"], [])
        raised = False
    except SystemExit:
        raised = True
    print(f"FIXTURE_3b_LOAD_STATE_DICT_HEAD_WEIGHT_ALIAS_ALLOWED_{'PASS' if not raised else 'FAIL'}")
    ok = ok and (not raised)

    # (iii) check_mtp_keyset: replay keyset missing one key vs seed/grown -> raise.
    seed_keys = ["mtp_heads.0.weight", "mtp_heads.1.weight"]
    grown_keys = ["mtp_heads.0.weight", "mtp_heads.1.weight"]
    replay_keys_corrupted = ["mtp_heads.0.weight"]  # one key silently dropped
    try:
        check_mtp_keyset(seed_keys, grown_keys, replay_keys_corrupted)
        raised = False
    except SystemExit:
        raised = True
    print(f"FIXTURE_3c_MTP_KEYSET_DROPPED_KEY_{'PASS' if raised else 'FAIL'}")
    ok = ok and raised

    # (iv) positive control: identical keysets -> must NOT raise, returns dict.
    try:
        result = check_mtp_keyset(seed_keys, grown_keys, list(grown_keys))
        raised = False
        returned_ok = isinstance(result, dict) and result.get("n_mtp_heads_keys") == 2
    except SystemExit:
        raised = True
        returned_ok = False
    print(f"FIXTURE_3d_MTP_KEYSET_MATCHING_POSITIVE_CONTROL_{'PASS' if (not raised and returned_ok) else 'FAIL'}")
    ok = ok and (not raised) and returned_ok

    return ok


def main() -> int:
    results = {
        "artifact_absent": fixture_artifact_absent(),
        "artifact_replaced": fixture_artifact_replaced(),
        "unused_key_deleted": fixture_unused_key_deleted(),
    }
    all_ok = all(results.values())
    print(f"\n{'CBASE_CLAUSE_D_NEGATIVE_FIXTURES_ALL_PASS' if all_ok else 'CBASE_CLAUSE_D_NEGATIVE_FIXTURES_FAIL'} "
          f"results={results}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
