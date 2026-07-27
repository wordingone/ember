# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Production-shaped coverage for the existing restart/seat consumer."""

from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PRODUCER_ROOT = REPO_ROOT / "scripts" / "ember_admission"
sys.path.insert(0, str(PRODUCER_ROOT))

from consumers import run_restart_consumer  # noqa: E402


def test_real_restart_consumer_refuses_invalid_published_bytes(tmp_path: Path) -> None:
    manifest = tmp_path / "restart-run-manifest.json"
    registry = tmp_path / "restart-trusted-verifiers.json"
    manifest.write_text(json.dumps({}), encoding="utf-8")
    registry.write_text(json.dumps({}), encoding="utf-8")

    result = run_restart_consumer(
        {
            "restart_run_manifest": manifest,
            "restart_trusted_verifier_registry": registry,
        }
    )

    assert result.returncode != 0
    assert '"valid": false' in result.stdout
