# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""C0 CRASH_SURVIVAL: a checkpoint written mid-crash is rejected on resume.

Synthetic-crash resume probe, zero real Ember checkpoints, zero GPU: every fixture
is a small torch tensor saved to a tempdir, then truncated to simulate a process
killed mid-write.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import torch

REPO_ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
SCRIPT_DIR = REPO_ROOT / "scripts" / "ember_01_custody"
IDENTITY_DIR = REPO_ROOT / "scripts" / "ember_01_identity"
for _extra in (SCRIPT_DIR, IDENTITY_DIR):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

import crash_survival_guard as guard


@pytest.fixture()
def tmp_checkpoint_dir(tmp_path: Path) -> Path:
    return tmp_path


def _write_real_checkpoint(path: Path) -> Path:
    """A small, complete, real checkpoint shard -- multiple tensors so a partial
    truncation reliably lands mid-archive rather than exactly at a boundary."""
    torch.save(
        {
            "model": {
                "layer.weight": torch.full((64,), 0.5, dtype=torch.float32),
                "layer.bias": torch.zeros(64, dtype=torch.float32),
                "norm.scale": torch.ones(64, dtype=torch.bfloat16),
            }
        },
        path,
    )
    return path


class TestResumeGuardRedFirst:
    """RED-first: a genuinely mid-crash-truncated checkpoint must be REJECTED."""

    def test_complete_checkpoint_is_accepted(self, tmp_checkpoint_dir: Path) -> None:
        shard = _write_real_checkpoint(tmp_checkpoint_dir / "complete.pt")
        verdict = guard.resume_guard(shard)
        assert verdict["result"] == "ACCEPTED"
        assert verdict["receipt"]["result"] == "MEASURED"

    @pytest.mark.parametrize("truncate_fraction", [0.1, 0.5, 0.9, 0.99])
    def test_mid_crash_truncated_checkpoint_is_rejected(
        self, tmp_checkpoint_dir: Path, truncate_fraction: float
    ) -> None:
        source = _write_real_checkpoint(tmp_checkpoint_dir / "source.pt")
        crashed = guard.simulate_mid_crash_write(
            source,
            tmp_checkpoint_dir / f"crashed-{truncate_fraction}.pt",
            truncate_fraction=truncate_fraction,
        )
        verdict = guard.resume_guard(crashed)
        assert verdict["result"] == "REJECTED"
        assert verdict.get("reason")

    def test_zero_byte_crash_is_rejected(self, tmp_checkpoint_dir: Path) -> None:
        source = _write_real_checkpoint(tmp_checkpoint_dir / "source.pt")
        crashed = guard.simulate_mid_crash_write(
            source, tmp_checkpoint_dir / "crashed-0.pt", truncate_fraction=0.0
        )
        verdict = guard.resume_guard(crashed)
        assert verdict["result"] == "REJECTED"

    def test_missing_checkpoint_is_rejected_not_an_exception(
        self, tmp_checkpoint_dir: Path
    ) -> None:
        verdict = guard.resume_guard(tmp_checkpoint_dir / "never-written.pt")
        assert verdict["result"] == "REJECTED"
        assert "does not exist" in verdict["reason"]

    def test_simulate_mid_crash_write_fails_closed_on_bad_fraction(
        self, tmp_checkpoint_dir: Path
    ) -> None:
        source = _write_real_checkpoint(tmp_checkpoint_dir / "source.pt")
        with pytest.raises(ValueError):
            guard.simulate_mid_crash_write(
                source, tmp_checkpoint_dir / "bad.pt", truncate_fraction=1.5
            )
        with pytest.raises(ValueError):
            guard.simulate_mid_crash_write(
                source, tmp_checkpoint_dir / "bad2.pt", truncate_fraction=-0.1
            )


class TestResumeGuardMutationProof:
    def test_resume_guard_mutation_guard_is_load_bearing(
        self, tmp_checkpoint_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Neutralize the fail-closed except clause (swallow the mismatch and
        report ACCEPTED unconditionally) and prove the SAME mid-crash-truncated
        checkpoint would then be wrongly accepted -- the except clause is the
        guard, not decorative code beside it."""
        source = _write_real_checkpoint(tmp_checkpoint_dir / "source.pt")
        crashed = guard.simulate_mid_crash_write(
            source, tmp_checkpoint_dir / "crashed.pt", truncate_fraction=0.5
        )

        # Sanity: the real guard rejects this fixture.
        assert guard.resume_guard(crashed)["result"] == "REJECTED"

        def _blind_resume_guard(shard_path):
            path = guard.Path(shard_path)
            try:
                receipt = guard.measure_checkpoint_identity(path)
            except guard.CheckpointSaveLoadIdentityMismatch:
                # Mutation: swallow the fail-closed signal entirely.
                return {
                    "schema": guard.RESUME_GUARD_SCHEMA,
                    "result": "ACCEPTED",
                    "receipt": {"result": "MUTATED_UNSAFE_PASS"},
                }
            return {
                "schema": guard.RESUME_GUARD_SCHEMA,
                "result": "ACCEPTED",
                "receipt": receipt,
            }

        monkeypatch.setattr(guard, "resume_guard", _blind_resume_guard)
        mutated_verdict = guard.resume_guard(crashed)
        assert mutated_verdict["result"] == "ACCEPTED"


class TestResumeGuardCLI:
    def test_main_exits_nonzero_on_crashed_checkpoint(
        self, tmp_checkpoint_dir: Path, capsys: pytest.CaptureFixture
    ) -> None:
        source = _write_real_checkpoint(tmp_checkpoint_dir / "source.pt")
        crashed = guard.simulate_mid_crash_write(
            source, tmp_checkpoint_dir / "crashed.pt", truncate_fraction=0.4
        )
        exit_code = guard.main([str(crashed)])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert '"result": "REJECTED"' in captured.out

    def test_main_exits_zero_on_complete_checkpoint(
        self, tmp_checkpoint_dir: Path, capsys: pytest.CaptureFixture
    ) -> None:
        shard = _write_real_checkpoint(tmp_checkpoint_dir / "complete.pt")
        exit_code = guard.main([str(shard)])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert '"result": "ACCEPTED"' in captured.out
