# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import importlib.util
import json
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
    readme = "<!-- state-as-of: 2026-07-28 -->\n\n# Ember\n"

    updated = module.bind_state_as_of(readme, "20260731T235959Z")

    assert updated == "<!-- state-as-of: 2026-07-31 -->\n\n# Ember\n"


def test_malformed_or_future_receipt_timestamp_fails_closed() -> None:
    module = load_generator()
    now = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="UTC timestamp"):
        module.validate_receipt_freshness("2026-07-31", max_age_days=1, now=now)
    with pytest.raises(ValueError, match="future"):
        module.validate_receipt_freshness("20260801T120001Z", max_age_days=1, now=now)
