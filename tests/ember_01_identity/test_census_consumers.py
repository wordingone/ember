from __future__ import annotations

# goal_id: EMBER-01
# workstream_id: EMBER-01C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / "scripts" / "ember_01_identity"
sys.path.insert(0, str(SCRIPT_DIR))

from census_consumers import build_census  # noqa: E402


def test_census_is_deterministic_and_evidence_linked(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "train.py").write_text(
        "torch.save({'state_dict': model.state_dict()}, checkpoint_path)\n",
        encoding="utf-8",
    )
    (tmp_path / "server.ts").write_text(
        "const endpoint = process.env['EMBER_MODEL_URL'];\n",
        encoding="utf-8",
    )
    tracked = ["server.ts", "scripts/train.py"]

    first = build_census(tmp_path, tracked_files=tracked)
    second = build_census(tmp_path, tracked_files=list(reversed(tracked)))
    assert first == second
    assert first["schema"] == "ember-identity-consumer-census-v1"
    assert first["goal_id"] == "EMBER-01"
    assert first["workstream_id"] == "EMBER-01C"
    assert first["next_executed_outcome"] == "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
    assert first["coverage"]["files_scanned"] == 2
    assert first["coverage"]["files_with_identity_evidence"] == 2
    assert all(
        row["path"]
        and row["line"] > 0
        and len(row["line_sha256"]) == 64
        and "excerpt" not in row
        for row in first["evidence"]
    )
    assert {row["category"] for row in first["evidence"]} >= {
        "checkpoint_save_load",
        "serving_runtime",
    }


def test_census_excludes_generated_receipts_and_test_fixtures(tmp_path: Path) -> None:
    (tmp_path / "receipts").mkdir()
    (tmp_path / "receipts" / "run.json").write_text(
        json.dumps({"checkpoint": "model.pt"}), encoding="utf-8"
    )
    (tmp_path / "tests" / "fixtures").mkdir(parents=True)
    (tmp_path / "tests" / "fixtures" / "fake.py").write_text(
        "MODEL_ID = 'fake'\n", encoding="utf-8"
    )
    (tmp_path / "scripts" / "ember_01_identity").mkdir(parents=True)
    (tmp_path / "scripts" / "ember_01_identity" / "self.py").write_text(
        "MODEL_ID = 'self-reference'\n", encoding="utf-8"
    )
    census = build_census(
        tmp_path,
        tracked_files=[
            "receipts/run.json",
            "tests/fixtures/fake.py",
            "scripts/ember_01_identity/self.py",
        ],
    )
    assert census["evidence"] == []
    assert census["coverage"]["files_excluded"] == 3


def test_same_line_can_expose_multiple_identity_roles(tmp_path: Path) -> None:
    (tmp_path / "cli.ts").write_text(
        "const LOCAL_MODEL_ID = 'qwen-3.6'; // borrowed reference provider\n",
        encoding="utf-8",
    )
    census = build_census(tmp_path, tracked_files=["cli.ts"])
    rows = census["evidence"]
    assert {row["category"] for row in rows} >= {
        "cli_operator_surface",
        "borrowed_reference",
    }


def test_evidence_is_bounded_per_file_and_category(tmp_path: Path) -> None:
    (tmp_path / "many.py").write_text(
        "\n".join(f"checkpoint_path_{index} = 'model.pt'" for index in range(10)) + "\n",
        encoding="utf-8",
    )
    census = build_census(tmp_path, tracked_files=["many.py"])
    checkpoint_rows = [
        row for row in census["evidence"] if row["category"] == "checkpoint_save_load"
    ]
    assert len(checkpoint_rows) == 3
    assert census["categories"]["checkpoint_save_load"]["raw_match_count"] == 10


def test_generic_claim_and_receipt_prose_is_not_publication_identity(tmp_path: Path) -> None:
    (tmp_path / "notes.md").write_text(
        "This claim cites a receipt but defines no publication identity surface.\n",
        encoding="utf-8",
    )
    census = build_census(tmp_path, tracked_files=["notes.md"])
    assert not any(row["category"] == "publication_report" for row in census["evidence"])


def test_census_does_not_republish_local_paths(tmp_path: Path) -> None:
    (tmp_path / "runtime.py").write_text(
        "checkpoint_path = r'C:\\private\\model.pt'\n",
        encoding="utf-8",
    )
    census = build_census(tmp_path, tracked_files=["runtime.py"])
    rendered = json.dumps(census)
    assert "C:\\\\private" not in rendered
    assert all("excerpt" not in row for row in census["evidence"])
