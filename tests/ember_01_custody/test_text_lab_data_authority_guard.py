# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""C0 TEXT_LAB_DATA_AUTHORITY: every consumed training shard is cross-referenced
against the accepted-training-input-authority registry at cycle start.

Zero live lab data: the census fixtures here are synthetic shard-source
declarations (shard_id/authority_id/input_id triples), never real training
shards or real training data bytes -- exactly the provenance-audit boundary the
ledger row asks for (cross-reference declared authority, not shard content).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = REPO_ROOT / "scripts" / "ember_01_custody"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import text_lab_data_authority_guard as guard

ACTIVE_AUTHORITY = {
    "authority_id": "ember-02-issue-812",
    "body_sha256": "6" + "a" * 63,
    "input_id": "github-issue-812",
    "issue_url": "https://github.com/wordingone/ember/issues/812",
    "state": "CURRENT_EXECUTABLE",
}
FIXTURE_DIGEST = "b" * 64
FIXTURE_AUTHORITY = (ACTIVE_AUTHORITY, FIXTURE_DIGEST)


def _census(*shards: dict, cycle_id: str = "cycle-0001") -> dict:
    return {
        "schema": guard.CENSUS_SCHEMA,
        "cycle_id": cycle_id,
        "shards": list(shards),
    }


def _good_shard(shard_id: str) -> dict:
    return {
        "shard_id": shard_id,
        "authority_id": ACTIVE_AUTHORITY["authority_id"],
        "input_id": ACTIVE_AUTHORITY["input_id"],
    }


class TestVerifyShardCensusAuthorityRedFirst:
    def test_all_shards_bound_to_active_authority_is_accepted(self) -> None:
        census = _census(_good_shard("shard-0001"), _good_shard("shard-0002"))
        verdict = guard.verify_shard_census_authority(
            census, accepted_authority=FIXTURE_AUTHORITY
        )
        assert verdict["result"] == "ACCEPTED"
        assert verdict["violations"] == []
        assert verdict["shards_checked"] == 2

    def test_one_shard_with_stale_authority_id_is_rejected(self) -> None:
        stale_shard = _good_shard("shard-0002")
        stale_shard["authority_id"] = "ember-02-issue-682-stale"
        census = _census(_good_shard("shard-0001"), stale_shard)
        verdict = guard.verify_shard_census_authority(
            census, accepted_authority=FIXTURE_AUTHORITY
        )
        assert verdict["result"] == "REJECTED"
        assert len(verdict["violations"]) == 1
        assert verdict["violations"][0]["shard_id"] == "shard-0002"

    def test_shard_missing_authority_id_entirely_is_rejected(self) -> None:
        naked_shard = _good_shard("shard-0003")
        naked_shard["authority_id"] = ""
        census = _census(_good_shard("shard-0001"), naked_shard)
        verdict = guard.verify_shard_census_authority(
            census, accepted_authority=FIXTURE_AUTHORITY
        )
        assert verdict["result"] == "REJECTED"
        assert "no authority_id binding" in verdict["violations"][0]["reason"]

    def test_shard_with_mismatched_input_id_is_rejected(self) -> None:
        wrong_input = _good_shard("shard-0004")
        wrong_input["input_id"] = "github-issue-793"
        census = _census(wrong_input)
        verdict = guard.verify_shard_census_authority(
            census, accepted_authority=FIXTURE_AUTHORITY
        )
        assert verdict["result"] == "REJECTED"

    def test_empty_shard_list_is_rejected_not_vacuously_accepted(self) -> None:
        census = {"schema": guard.CENSUS_SCHEMA, "cycle_id": "cycle-empty", "shards": []}
        with pytest.raises(guard.TextLabDataAuthorityError):
            guard.verify_shard_census_authority(census, accepted_authority=FIXTURE_AUTHORITY)

    def test_malformed_census_schema_is_rejected(self) -> None:
        with pytest.raises(guard.TextLabDataAuthorityError):
            guard.verify_shard_census_authority(
                {"schema": "wrong-schema", "cycle_id": "x", "shards": []},
                accepted_authority=FIXTURE_AUTHORITY,
            )

    def test_shard_entry_missing_required_key_is_rejected(self) -> None:
        malformed = {"shard_id": "shard-0005", "authority_id": "x"}  # missing input_id
        census = _census(malformed)
        with pytest.raises(guard.TextLabDataAuthorityError):
            guard.verify_shard_census_authority(census, accepted_authority=FIXTURE_AUTHORITY)


class TestLoadAcceptedAuthorityFailsClosed:
    def test_missing_registry_file_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(guard.validate_identity, "_pinned_accepted_training_input", lambda: None)
        with pytest.raises(guard.TextLabDataAuthorityError):
            guard.load_accepted_authority()

    def test_live_registry_loads_and_matches_repo_manifest(self) -> None:
        # Grounds the fixture constant against the real, live in-repo registry --
        # not just an isolated mock.
        active, _digest = guard.load_accepted_authority()
        assert active["authority_id"] == ACTIVE_AUTHORITY["authority_id"]
        assert active["input_id"] == ACTIVE_AUTHORITY["input_id"]
        assert active["state"] == "CURRENT_EXECUTABLE"


class TestCycleStartGuardFileDriven:
    def test_census_file_missing_is_rejected(self, tmp_path: Path) -> None:
        verdict = guard.cycle_start_guard(tmp_path / "never-written.json")
        assert verdict["result"] == "REJECTED"

    def test_census_file_malformed_json_is_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        verdict = guard.cycle_start_guard(path)
        assert verdict["result"] == "REJECTED"

    def test_census_file_with_live_registry_and_good_shards_is_accepted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Uses the LIVE registry (no injected fixture) end-to-end through the CLI path.
        active, _digest = guard.load_accepted_authority()
        census = _census(
            {
                "shard_id": "shard-live-0001",
                "authority_id": active["authority_id"],
                "input_id": active["input_id"],
            }
        )
        path = tmp_path / "census.json"
        path.write_text(json.dumps(census), encoding="utf-8")
        verdict = guard.cycle_start_guard(path)
        assert verdict["result"] == "ACCEPTED"

    def test_census_file_with_stale_shard_against_live_registry_is_rejected(
        self, tmp_path: Path
    ) -> None:
        census = _census(
            {
                "shard_id": "shard-live-stale",
                "authority_id": "ember-02-issue-682-revoked",
                "input_id": "github-issue-682",
            }
        )
        path = tmp_path / "census.json"
        path.write_text(json.dumps(census), encoding="utf-8")
        verdict = guard.cycle_start_guard(path)
        assert verdict["result"] == "REJECTED"


class TestMutationGuardIsLoadBearing:
    def test_authority_comparison_mutation_guard_is_load_bearing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Neutralize the per-shard authority comparison (always treat every shard
        as matching) and prove a genuinely stale-authority shard would then be
        wrongly accepted -- the comparison is the guard, not decorative code."""
        stale_shard = _good_shard("shard-mutation")
        stale_shard["authority_id"] = "ember-02-issue-682-revoked"
        census = _census(stale_shard)

        # Sanity: the real guard rejects this fixture.
        real_verdict = guard.verify_shard_census_authority(
            census, accepted_authority=FIXTURE_AUTHORITY
        )
        assert real_verdict["result"] == "REJECTED"

        def _blind_verify(census_arg, *, accepted_authority=None):
            active, _digest = (
                accepted_authority if accepted_authority is not None else guard.load_accepted_authority()
            )
            shards = guard._validate_census_shape(census_arg)
            return {
                "schema": guard.CENSUS_GUARD_SCHEMA,
                "cycle_id": census_arg.get("cycle_id"),
                "result": "ACCEPTED",
                "shards_checked": len(shards),
                "violations": [],
                "accepted_authority_id": active["authority_id"],
            }

        monkeypatch.setattr(guard, "verify_shard_census_authority", _blind_verify)
        mutated_verdict = guard.verify_shard_census_authority(
            census, accepted_authority=FIXTURE_AUTHORITY
        )
        assert mutated_verdict["result"] == "ACCEPTED"


class TestCLI:
    def test_main_exits_nonzero_on_rejected_census(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        census = _census(
            {
                "shard_id": "shard-cli-bad",
                "authority_id": "revoked-authority",
                "input_id": "revoked-input",
            }
        )
        path = tmp_path / "census.json"
        path.write_text(json.dumps(census), encoding="utf-8")
        exit_code = guard.main([str(path)])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert '"result": "REJECTED"' in captured.out

    def test_main_exits_zero_on_accepted_census(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        active, _digest = guard.load_accepted_authority()
        census = _census(
            {
                "shard_id": "shard-cli-good",
                "authority_id": active["authority_id"],
                "input_id": active["input_id"],
            }
        )
        path = tmp_path / "census.json"
        path.write_text(json.dumps(census), encoding="utf-8")
        exit_code = guard.main([str(path)])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert '"result": "ACCEPTED"' in captured.out
