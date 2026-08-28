# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = REPO_ROOT / "scripts" / "gen_readme_status.py"


def load_generator():
    spec = importlib.util.spec_from_file_location("gen_readme_status_freshness", GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stale_board_receipt_is_rejected_before_render(tmp_path: Path, monkeypatch) -> None:
    module = load_generator()
    receipt = tmp_path / "ember-totality-20260711T102112Z.json"
    receipt.write_text(
        json.dumps({"ts": "20260711T102112Z", "summary": {"green": 1, "total": 1}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        module.tree_provenance,
        "validate_receipt_for_render",
        lambda *args, **kwargs: None,
    )

    with pytest.raises(ValueError, match="board receipt is 20 days old"):
        module.render_block(
            receipt,
            receipt_max_age_days=1,
            now=datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc),
        )


def test_state_as_of_is_bound_to_selected_receipt_date() -> None:
    module = load_generator()
    continuity = "<!-- state-as-of: 2026-07-28 -->\n\n# Continuity\n"

    updated = module.bind_state_as_of(continuity, "20260731T235959Z")

    assert updated == "<!-- state-as-of: 2026-07-31 -->\n\n# Continuity\n"


def test_state_as_of_requires_exactly_one_continuity_marker() -> None:
    module = load_generator()

    with pytest.raises(ValueError, match="CONTINUITY.md must contain exactly one"):
        module.bind_state_as_of("# Continuity\n", "20260731T235959Z")


def test_malformed_or_future_receipt_timestamp_fails_closed() -> None:
    module = load_generator()
    now = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="UTC timestamp"):
        module.validate_receipt_freshness("2026-07-31", max_age_days=1, now=now)
    with pytest.raises(ValueError, match="future"):
        module.validate_receipt_freshness("20260801T120001Z", max_age_days=1, now=now)


def test_generation_writes_continuity_and_leaves_readme_byte_identical(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = load_generator()
    readme = tmp_path / "README.md"
    continuity = tmp_path / "CONTINUITY.md"
    receipt = tmp_path / "ember-totality-20260731T235959Z.json"
    subject = tmp_path / "subject.json"
    inventory = tmp_path / "inventory.json"
    readme.write_bytes(b"# evergreen front door\n")
    original_readme = readme.read_bytes()
    continuity.write_text(
        "<!-- state-as-of: 2026-07-28 -->\n"
        f"{module.BEGIN_MARKER}\nold board\n{module.END_MARKER}\n"
        f"{module.SUBJECT_BEGIN_MARKER}\nold subject\n{module.SUBJECT_END_MARKER}\n",
        encoding="utf-8",
    )
    receipt.write_text("{}\n", encoding="utf-8")
    subject.write_text("{}\n", encoding="utf-8")
    inventory.write_text("{}\n", encoding="utf-8")
    board = f"{module.BEGIN_MARKER}\nnew board\n{module.END_MARKER}"
    subject_block = (
        f"{module.SUBJECT_BEGIN_MARKER}\nnew subject\n{module.SUBJECT_END_MARKER}"
    )
    monkeypatch.setattr(module, "check_inventory", lambda **_kwargs: None)
    monkeypatch.setattr(module, "newest_receipt_path", lambda _root: str(receipt))
    monkeypatch.setattr(module, "render_block", lambda *_args, **_kwargs: board)
    monkeypatch.setattr(module, "load_current_subject", lambda _path: {})
    monkeypatch.setattr(module, "validate_current_subject_evidence", lambda *_args: None)
    monkeypatch.setattr(module, "render_current_subject_block", lambda _payload: subject_block)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "gen_readme_status.py",
            "--readme", str(readme),
            "--continuity", str(continuity),
            "--data-root", str(tmp_path),
            "--subject-manifest", str(subject),
            "--branch-inventory", str(inventory),
        ],
    )

    assert module.main() == 0
    assert readme.read_bytes() == original_readme
    assert "new board" in continuity.read_text(encoding="utf-8")
    assert "new subject" in continuity.read_text(encoding="utf-8")
    assert "<!-- state-as-of: 2026-07-31 -->" in continuity.read_text(encoding="utf-8")
