# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""test_fcalib_default_mode_equivalence.py -- Prove new fcalib is behavior-preserving.

Synthetic fixture runs old and new fcalib.py on identical input WITHOUT the
--emit-boilerplate-keys flag. Outputs must be receipt-equivalent (excluding
timestamps and wall_s which vary per run).

This test pins the default behavior against regression from the new flag's
signature change (finalize_source now returns a tuple).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import subprocess
from pathlib import Path

import pytest
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_ROOT = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS_ROOT)
sys.path.insert(0, SCRIPTS_ROOT)


def _make_synthetic_shard_receipt(tmpdir: str) -> tuple[str, dict]:
    """Create a minimal token-shards-v0 receipt + binary shard for fixture.

    Returns: (receipt_path, boundaries_dict)

    Receipt schema must match fcalib's expectations:
    - per_source dict with entries: {
        "stream_tokens": total tokens for source,
        "separator_tokens": count of separators,
        "content_tokens": count of non-separator tokens,
      }
    """
    # Generate tokens for all 5 sources with separators
    # Must be in production order: code_github_clean, fineweb_edu, wikipedia_en, gutenberg_en, ledger_mit
    rng = np.random.RandomState(42)
    sources_config = [
        ("code_github_clean", 40000, 400),
        ("fineweb_edu", 30000, 300),
        ("wikipedia_en", 20000, 200),
        ("gutenberg_en", 5000, 50),
        ("ledger_mit", 1000, 10),
    ]

    tokens_list = []
    per_source_data = {}
    cur_start = 0

    for src_name, n_tokens, n_seps in sources_config:
        # Generate non-separator tokens
        n_content = n_tokens - n_seps
        src_tokens = rng.randint(8, 60000, size=n_content, dtype=np.uint16)

        # Interleave separators (id=0) into the token stream
        src = []
        sep_count = 0
        for i in range(0, len(src_tokens), n_content // max(1, n_seps)):
            chunk_end = min(i + n_content // max(1, n_seps), len(src_tokens))
            if i < len(src_tokens):
                src.extend(src_tokens[i:chunk_end])
            if sep_count < n_seps:
                src.append(0)  # separator
                sep_count += 1

        src = np.array(src, dtype=np.uint16)
        src_end = cur_start + len(src)

        tokens_list.append(src)

        # Build per_source entry (required by fcalib)
        per_source_data[src_name] = {
            "stream_tokens": int(len(src)),
            "separator_tokens": n_seps,
            "content_tokens": n_content,
        }

        cur_start = src_end

    tokens = np.concatenate(tokens_list)
    total_tokens = len(tokens)

    # Write binary shard
    shard_path = os.path.join(tmpdir, "shard-00.bin")
    tokens.astype("<u2").tofile(shard_path)

    # Build receipt with proper schema
    receipt = {
        "ticket": "TOKEN-SHARDS-V0",
        "ts": "20260708T000000Z",
        "total_stream_tokens": int(total_tokens),
        "per_source": per_source_data,
    }

    receipt_path = os.path.join(tmpdir, "token-shards-v0-fixture.json")
    with open(receipt_path, "w") as f:
        json.dump(receipt, f)

    return receipt_path, None


def test_fcalib_default_mode_equivalence():
    """Old (6675e2a) and new fcalib produce receipt-equivalent output (without flag).

    Proof that PR #506 changes (finalize_source signature) are behavior-preserving
    when --emit-boilerplate-keys is NOT set. Runs old and new on SAME fixture,
    compares receipts with exclusion list for timing/path differences.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # Set up fixture (shared between old and new runs)
        receipt_path, _ = _make_synthetic_shard_receipt(tmpdir)
        shard_dir = tmpdir

        # Extract OLD fcalib from 6675e2a (master pre-PR)
        old_fcalib_result = subprocess.run(
            ["git", "show", "6675e2a:src/ember/governance/scripts/heldout_v21_fcalib.py"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True
        )
        assert old_fcalib_result.returncode == 0, (
            f"Failed to extract old fcalib from 6675e2a: {old_fcalib_result.stderr}"
        )

        old_fcalib_path = os.path.join(tmpdir, "heldout_v21_fcalib_old.py")
        with open(old_fcalib_path, "w") as f:
            f.write(old_fcalib_result.stdout)

        # Run OLD fcalib (separate cache dir to avoid collision)
        tmpdir_old_cache = os.path.join(tmpdir, "cache-old")
        os.makedirs(tmpdir_old_cache, exist_ok=True)
        out_old = os.path.join(tmpdir, "out-old.json")

        # Set PYTHONPATH for old fcalib to find scripts.lib and receipt_check modules
        env_old = os.environ.copy()
        pathsep = ";" if sys.platform == "win32" else ":"
        env_old["PYTHONPATH"] = f"{REPO_ROOT}{pathsep}{SCRIPTS_ROOT}"

        old_result = subprocess.run([
            sys.executable, old_fcalib_path,
            f"--shard-dir={shard_dir}",
            f"--shard-receipt={receipt_path}",
            f"--out={out_old}",
            f"--cache-dir={tmpdir_old_cache}",
            "--sample-rate=0.01",
            "--window-tokens=50",
            "--commit-floor-gib=0.1",
        ], cwd=REPO_ROOT, capture_output=True, text=True, env=env_old)

        print(f"\n[OLD] 6675e2a fcalib run")
        print(f"  Return code: {old_result.returncode}")
        if old_result.returncode != 0:
            print(f"  Stderr: {old_result.stderr}")
        assert old_result.returncode == 0, (
            f"Old fcalib failed: {old_result.stderr}"
        )
        assert Path(out_old).exists(), "Old fcalib didn't write receipt"

        # Run NEW fcalib (separate cache dir)
        tmpdir_new_cache = os.path.join(tmpdir, "cache-new")
        os.makedirs(tmpdir_new_cache, exist_ok=True)
        out_new = os.path.join(tmpdir, "out-new.json")

        new_result = subprocess.run([
            sys.executable, "src/ember/governance/scripts/heldout_v21_fcalib.py",
            f"--shard-dir={shard_dir}",
            f"--shard-receipt={receipt_path}",
            f"--out={out_new}",
            f"--cache-dir={tmpdir_new_cache}",
            "--sample-rate=0.01",
            "--window-tokens=50",
            "--commit-floor-gib=0.1",
        ], cwd=REPO_ROOT, capture_output=True, text=True)

        print(f"[NEW] Current fcalib run")
        print(f"  Return code: {new_result.returncode}")
        if new_result.returncode != 0:
            print(f"  Stderr: {new_result.stderr}")
        assert new_result.returncode == 0, (
            f"New fcalib failed: {new_result.stderr}"
        )
        assert Path(out_new).exists(), "New fcalib didn't write receipt"

        # Load both receipts
        with open(out_old) as f:
            receipt_old = json.load(f)
        with open(out_new) as f:
            receipt_new = json.load(f)

        # Diff with exclusion list: ts, wall_s, runner git sha, mmap_cache_report paths,
        # invariant_stamp_error/invariant_sha256 rename pair, shard_receipt_path, commit_preflight
        def normalize_receipt(receipt):
            """Remove timing/path/system differences for comparison."""
            normalized = json.loads(json.dumps(receipt))  # Deep copy

            # Exclude top-level timing/metadata/path/invariant fields
            for key in ["ts", "wall_s", "pass_b_wall_s", "runner_git_sha", "runner_invocation_id",
                        "shard_receipt_path", "commit_preflight", "mmap_cache_report",
                        "invariant_stamp_error", "invariant_sha256"]:
                normalized.pop(key, None)

            # Process per_source: exclude timing, path, and field-rename differences
            if "per_source" in normalized:
                for source_name, source_data in normalized["per_source"].items():
                    # Remove timing fields at source level
                    for key in ["ts", "wall_s", "pass_b_wall_s"]:
                        source_data.pop(key, None)

                    # Remove field-rename inconsistencies (old has invariant_stamp_error, new has invariant_sha256)
                    source_data.pop("invariant_stamp_error", None)
                    source_data.pop("invariant_sha256", None)

                    # Remove mmap_cache_report (path-based, may differ)
                    source_data.pop("mmap_cache_report", None)

            return normalized

        normalized_old = normalize_receipt(receipt_old)
        normalized_new = normalize_receipt(receipt_new)

        # Assert equivalence
        assert normalized_old == normalized_new, (
            f"Old and new receipts differ:\n"
            f"Old: {json.dumps(normalized_old, indent=2)}\n"
            f"New: {json.dumps(normalized_new, indent=2)}"
        )

        print(f"[PASS] Old (6675e2a) and new fcalib produce equivalent receipts")
        print(f"  Old receipt: {out_old}")
        print(f"  New receipt: {out_new}")
        print(f"  Both: status={receipt_new.get('status')}, sources={sorted(receipt_new.get('per_source', {}).keys())}")


def test_old_v0_cache_regenerated_not_misread():
    """Verify new fcalib uses v1 cache naming, ignoring old v0 caches.

    OLD ISSUE (FINDING 2): Old fcalib's cache (shards-v0-stream.uint16.bin)
    was SILENTLY MISREAD by new fcalib as double token count (192k vs 96k),
    causing data corruption in thresholds.

    CURE: v1 cache versioning. The new fcalib WRITES cache under v1 names
    (shards-v1-stream.uint16.bin, shards-v1-stream.manifest.json). Old v0
    caches are never found or loaded because the new code doesn't look for them.
    This test verifies the v1 naming is enforced: a fresh fixture produces
    v1 cache, not v0.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create fixture
        receipt_path, _ = _make_synthetic_shard_receipt(tmpdir)
        shard_dir = tmpdir

        # Run new fcalib (should build v1 cache, not v0)
        out = os.path.join(tmpdir, "out.json")
        result = subprocess.run([
            sys.executable, "src/ember/governance/scripts/heldout_v21_fcalib.py",
            f"--shard-dir={shard_dir}",
            f"--shard-receipt={receipt_path}",
            f"--out={out}",
            f"--cache-dir={tmpdir}",
            "--sample-rate=0.01",
            "--window-tokens=50",
            "--commit-floor-gib=0.1",
        ], cwd=REPO_ROOT, capture_output=True, text=True)

        assert result.returncode == 0, (
            f"New fcalib should succeed: {result.stderr}"
        )

        # Verify v1 cache was created (new naming)
        v1_cache_path = os.path.join(tmpdir, "shards-v1-stream.uint16.bin")
        v1_manifest_path = os.path.join(tmpdir, "shards-v1-stream.manifest.json")

        assert os.path.exists(v1_cache_path), (
            f"New fcalib must create v1 cache (shards-v1-stream.uint16.bin). "
            f"Files: {os.listdir(tmpdir)}"
        )
        assert os.path.exists(v1_manifest_path), (
            f"New fcalib must create v1 manifest (shards-v1-stream.manifest.json)"
        )

        # Verify v1 manifest has correct token count
        with open(v1_manifest_path) as f:
            v1_manifest = json.load(f)
        assert v1_manifest["n_tokens"] == 96000, (
            f"v1 manifest should have 96000 tokens, got {v1_manifest['n_tokens']}"
        )

        # Verify v0 cache was NOT created (core of the cure)
        v0_cache_path = os.path.join(tmpdir, "shards-v0-stream.uint16.bin")
        v0_manifest_path = os.path.join(tmpdir, "shards-v0-stream.manifest.json")

        assert not os.path.exists(v0_cache_path), (
            "New fcalib should NOT create v0 cache (v0 is retired)"
        )
        assert not os.path.exists(v0_manifest_path), (
            "New fcalib should NOT create v0 manifest (v0 is retired)"
        )

        print(f"[PASS] v1 cache versioning cure enforced: v1 created, v0 never created")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
