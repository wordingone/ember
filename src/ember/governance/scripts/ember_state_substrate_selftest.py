#!/usr/bin/env python3
"""Selftest for Ember MVP local state substrate semantics."""
from __future__ import annotations

import tempfile
from pathlib import Path

import ember_state_substrate as substrate


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ember-state-substrate-") as td:
        root = Path(td)
        run = substrate.run_fixture_state_cycle(root, promotion="rejected")

        assert run.branch["status"] == "candidate"
        assert run.commit["promotion"] == "rejected"
        assert run.commit["gc_enggible"] is True
        assert Path(run.commit["diff"]["path"]).exists()
        assert run.rollback["restored_state_hash"] == run.rollback["pre_cycle_state_hash"]
        assert run.gc["deleted"] is True
        assert not Path(run.branch["produced_deltas"][0]["path"]).exists()

        replay = substrate.replay_from_commit_receipt(Path(run.commit["receipt_path"]))
        assert replay["deterministic"] is True
        assert replay["replayed_state_hash"] == run.commit["post_candidate_state_hash"]
        assert replay["diff_sha256"] == run.commit["diff"]["sha256"]

        substrate.validate_state_bundle(
            observation=run.observation,
            branch=run.branch,
            commit=run.commit,
            rollback=run.rollback,
            replay=replay,
            gc=run.gc,
        )

    print("EMBER_STATE_SUBSTRATE_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
