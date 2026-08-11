"""
Ember constitutional invariant stamping and verification.

The invariant is the sole unamendable surface of the ember project.
This module provides the mechanism to stamp invariant hashes into artifacts
and verify them against the canonical docs/authority/INVARIANT.md file.
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict

# The canonical hash of docs/authority/INVARIANT.md as of genesis
INVARIANT_SHA256 = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"


def _read_invariant_bytes(repo_root: str) -> bytes:
    """Read docs/authority/INVARIANT.md bytes from repo root.

    Args:
        repo_root: Absolute path to ember repo root

    Returns:
        Raw bytes of docs/authority/INVARIANT.md

    Raises:
        FileNotFoundError: If docs/authority/INVARIANT.md does not exist
    """
    invariant_path = Path(repo_root) / "docs/authority/INVARIANT.md"
    if not invariant_path.exists():
        raise FileNotFoundError(f"docs/authority/INVARIANT.md not found at {invariant_path}")
    return invariant_path.read_bytes()


def _compute_hash(data: bytes) -> str:
    """Compute sha256 hash of data.

    Args:
        data: Bytes to hash

    Returns:
        Hex-encoded sha256 hash
    """
    return hashlib.sha256(data).hexdigest()


def verify(repo_root: str) -> str:
    """Verify that docs/authority/INVARIANT.md in repo_root matches the canonical hash.

    Args:
        repo_root: Absolute path to ember repo root

    Returns:
        The verified hash string

    Raises:
        FileNotFoundError: If docs/authority/INVARIANT.md does not exist
        ValueError: If docs/authority/INVARIANT.md hash does not match INVARIANT_SHA256
    """
    invariant_bytes = _read_invariant_bytes(repo_root)
    computed_hash = _compute_hash(invariant_bytes)

    if computed_hash != INVARIANT_SHA256:
        raise ValueError(
            f"docs/authority/INVARIANT.md hash mismatch: expected {INVARIANT_SHA256}, "
            f"got {computed_hash}"
        )

    return computed_hash


def stamp(artifact: Dict[str, Any], repo_root: str = None) -> Dict[str, Any]:
    """Stamp an artifact dict with the invariant hash.

    Reads docs/authority/INVARIANT.md from repo root (or cwd if not specified),
    verifies its hash against the canonical value, and adds the hash
    to the artifact. The artifact is not written if the hash is invalid.

    Args:
        artifact: Dictionary to stamp (will be modified in-place)
        repo_root: Absolute path to ember repo root (defaults to cwd)

    Returns:
        The stamped artifact dict

    Raises:
        FileNotFoundError: If docs/authority/INVARIANT.md does not exist
        ValueError: If docs/authority/INVARIANT.md hash does not match INVARIANT_SHA256
    """
    if repo_root is None:
        repo_root = os.getcwd()

    # This will raise if hash doesn't match
    hash_value = verify(repo_root)

    # Only stamp if verification passed
    artifact["invariant_sha256"] = hash_value

    return artifact


def _selftest():
    """Self-test for invariant module.

    This test runs in the current working directory and verifies:
    1. The docs/authority/INVARIANT.md file exists and has the correct hash
    2. stamp() correctly adds the hash to a dict
    3. Verification succeeds when hashes match
    4. Verification fails with wrong hash
    """
    import tempfile

    print("Running invariant.py selftest...")

    # Test 1: Verify current docs/authority/INVARIANT.md matches canonical hash
    try:
        cwd = os.getcwd()
        computed = verify(cwd)
        print("[PASS] Test 1: docs/authority/INVARIANT.md hash verified")
        print(f"  Hash: {computed}")
        assert computed == INVARIANT_SHA256, f"Hash mismatch: {computed} != {INVARIANT_SHA256}"
    except Exception as e:
        print(f"[FAIL] Test 1: {e}")
        raise

    # Test 2: stamp() correctly adds hash to dict
    try:
        test_artifact = {"test": "data"}
        stamped = stamp(test_artifact, cwd)
        assert "invariant_sha256" in stamped
        assert stamped["invariant_sha256"] == INVARIANT_SHA256
        assert stamped["test"] == "data"
        print("[PASS] Test 2: stamp() adds hash to artifact")
    except Exception as e:
        print(f"[FAIL] Test 2: {e}")
        raise

    # Test 3: stamp() with explicit repo_root
    try:
        test_artifact2 = {"nested": {"data": 123}}
        stamped2 = stamp(test_artifact2, cwd)
        assert stamped2["invariant_sha256"] == INVARIANT_SHA256
        print("[PASS] Test 3: stamp() with explicit repo_root")
    except Exception as e:
        print(f"[FAIL] Test 3: {e}")
        raise

    # Test 4: verify() with missing file raises FileNotFoundError
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            # tmpdir has no docs/authority/INVARIANT.md
            verify(tmpdir)
            print("[FAIL] Test 4: Expected FileNotFoundError")
            raise AssertionError("Should have raised FileNotFoundError for missing docs/authority/INVARIANT.md")
    except FileNotFoundError:
        print("[PASS] Test 4: Correctly raises FileNotFoundError for missing docs/authority/INVARIANT.md")
    except Exception as e:
        print(f"[FAIL] Test 4: Wrong exception: {e}")
        raise

    # Test 5: stamp() fails if hash doesn't match
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a fake docs/authority/INVARIANT.md with different content
            fake_path = Path(tmpdir) / "docs/authority/INVARIANT.md"
            fake_path.write_text("wrong content")

            try:
                stamp({"test": "data"}, tmpdir)
                print("[FAIL] Test 5: Expected ValueError for mismatched hash")
                raise AssertionError("Should have raised ValueError for wrong hash")
            except ValueError as ve:
                if "hash mismatch" in str(ve):
                    print("[PASS] Test 5: Correctly raises ValueError for wrong hash")
                else:
                    raise
    except Exception as e:
        print(f"[FAIL] Test 5: {e}")
        raise

    print("\n[PASS] All selftest cases passed")
    return True


if __name__ == "__main__":
    success = _selftest()
    exit(0 if success else 1)
