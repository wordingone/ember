# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PROBE = REPO_ROOT / "scripts" / "ember_totality" / "test_c_auto.py"


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CAutonomyClaimContractTests(unittest.TestCase):
    def _git(self, root: Path, *args: str, env: dict[str, str] | None = None) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()

    def _run_probe(self, root: Path) -> str:
        env = os.environ.copy()
        env["EMBER_TOTALITY_ROOT"] = str(root)
        completed = subprocess.run(
            [sys.executable, "-B", str(PROBE)],
            cwd=REPO_ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            self.fail(
                f"probe exited {completed.returncode}\n"
                f"stdout:\n{completed.stdout}\n"
                f"stderr:\n{completed.stderr}"
            )
        return completed.stdout.strip()

    def _write_json(self, path: Path, value: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    def _build_valid_claim(self, root: Path) -> tuple[list[Path], Path]:
        self._git(root, "init", "-q")
        self._git(root, "config", "user.name", "C-AUTO Fixture")
        self._git(root, "config", "user.email", "c-auto@example.invalid")

        contract = root / "docs" / "spec" / "autonomy-relinquishment-ladder-v1.md"
        contract.parent.mkdir(parents=True)
        contract.write_text("# fixture contract\n", encoding="utf-8", newline="\n")

        window_paths: list[Path] = []
        window_refs: list[str] = []
        claim_windows: list[dict[str, str]] = []
        latest_commit = ""
        for number in range(1, 6):
            ts = f"2026-07-30T10:0{number}:00Z"
            evidence = root / "evidence" / f"window-{number}.txt"
            evidence.parent.mkdir(parents=True, exist_ok=True)
            evidence.write_text(f"window {number}\n", encoding="utf-8", newline="\n")
            self._git(root, "add", str(evidence.relative_to(root)))
            commit_env = os.environ.copy()
            commit_env["GIT_AUTHOR_DATE"] = ts
            commit_env["GIT_COMMITTER_DATE"] = ts
            self._git(root, "commit", "-q", "-m", f"window {number}", env=commit_env)
            latest_commit = self._git(root, "rev-parse", "HEAD")

            payload = {
                "schema": "ember-autonomy-window-v2",
                "rung": "R0",
                "window_id": f"R0-{number}",
                "ts": ts,
                "verdict": "PASS",
                "independent_evidence": {
                    "kind": "git_commit",
                    "commit_sha": latest_commit,
                    "commit_ts": ts,
                },
            }
            payload_sha = canonical_sha256(payload)
            provenance_core = {
                "producer": "ember",
                "window_payload_sha256": payload_sha,
            }
            receipt = {
                **payload,
                "provenance": {
                    **provenance_core,
                    "token_sha256": canonical_sha256(provenance_core),
                },
            }
            name = f"R0-window-{number}.json"
            window_path = root / "receipts" / "autonomy-ladder" / name
            self._write_json(window_path, receipt)
            window_paths.append(window_path)
            window_refs.append(name)
            claim_windows.append({"path": name, "sha256": file_sha256(window_path)})

        claim = {
            "schema": "ember-autonomy-claim-v2",
            "rung": "R0",
            "claim": True,
            "ts": "2026-07-30T10:06:00Z",
            "source_commit": latest_commit,
            "windows": claim_windows,
        }
        claim_path = (
            root
            / "receipts"
            / "autonomy-ladder"
            / "R0-claim-20260730T100600Z.json"
        )
        self._write_json(claim_path, claim)

        state = {
            "schema": "autonomy-ladder-state-v1",
            "contract": "docs/spec/autonomy-relinquishment-ladder-v1.md",
            "current_rung": "R0",
            "rungs": {
                "R0": {
                    "status": "CLAIMED",
                    "claimed": True,
                    "windows": window_refs,
                }
            },
            "reversion_log": [],
            "promotion_rule": "K=5 consecutive clean receipted windows",
            "safety_floor": (
                "operator escalation set + governor caps + kill-discipline NEVER transfer"
            ),
        }
        self._write_json(root / "autonomy-ladder-state.json", state)
        return window_paths, claim_path

    def _assert_red(self, root: Path) -> None:
        output = self._run_probe(root)
        self.assertTrue(output.startswith("RED "), output)
        self.assertIn("invalid_autonomy_claim_evidence", output)

    def test_accepts_five_hash_linked_windows_bound_to_real_commits(self) -> None:
        with tempfile.TemporaryDirectory(prefix="c-auto-valid-") as raw_root:
            root = Path(raw_root)
            self._build_valid_claim(root)
            output = self._run_probe(root)
            self.assertTrue(output.startswith("GREEN "), output)

    def test_rejects_empty_claim_receipt_content(self) -> None:
        with tempfile.TemporaryDirectory(prefix="c-auto-empty-claim-") as raw_root:
            root = Path(raw_root)
            _, claim_path = self._build_valid_claim(root)
            self._write_json(claim_path, {})
            self._assert_red(root)

    def test_rejects_nonexistent_claim_source_commit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="c-auto-fake-commit-") as raw_root:
            root = Path(raw_root)
            _, claim_path = self._build_valid_claim(root)
            claim = json.loads(claim_path.read_text(encoding="utf-8"))
            claim["source_commit"] = "f" * 40
            self._write_json(claim_path, claim)
            self._assert_red(root)

    def test_rejects_claim_window_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory(prefix="c-auto-window-hash-") as raw_root:
            root = Path(raw_root)
            _, claim_path = self._build_valid_claim(root)
            claim = json.loads(claim_path.read_text(encoding="utf-8"))
            claim["windows"][2]["sha256"] = "0" * 64
            self._write_json(claim_path, claim)
            self._assert_red(root)

    def test_rejects_tampered_structured_provenance_token(self) -> None:
        with tempfile.TemporaryDirectory(prefix="c-auto-token-") as raw_root:
            root = Path(raw_root)
            window_paths, _ = self._build_valid_claim(root)
            receipt = json.loads(window_paths[1].read_text(encoding="utf-8"))
            receipt["provenance"]["token_sha256"] = "0" * 64
            self._write_json(window_paths[1], receipt)
            self._assert_red(root)

    def test_rejects_window_commit_timestamp_mismatch(self) -> None:
        with tempfile.TemporaryDirectory(prefix="c-auto-commit-ts-") as raw_root:
            root = Path(raw_root)
            window_paths, _ = self._build_valid_claim(root)
            receipt = json.loads(window_paths[3].read_text(encoding="utf-8"))
            receipt["independent_evidence"]["commit_ts"] = "2026-07-30T11:00:00Z"
            self._write_json(window_paths[3], receipt)
            self._assert_red(root)

    def test_rejects_duplicate_claim_receipts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="c-auto-duplicate-claim-") as raw_root:
            root = Path(raw_root)
            _, claim_path = self._build_valid_claim(root)
            duplicate = claim_path.with_name("R0-claim-duplicate.json")
            duplicate.write_bytes(claim_path.read_bytes())
            self._assert_red(root)


if __name__ == "__main__":
    unittest.main()
