# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
PRODUCER = REPO_ROOT / "scripts" / "ember_admission" / "produce_candidate.py"


def test_unknown_descriptor_field_refuses_before_candidate_publication(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    output_root = tmp_path / "candidates"
    workspace.mkdir()
    descriptor = workspace / "admission.json"
    descriptor.write_text(
        json.dumps(
            {
                "schema_version": "ember-owned-admission-input-v1",
                "candidate_id": "candidate-one",
                "roles": [],
                "unexpected": True,
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(PRODUCER),
            "--workspace",
            str(workspace),
            "--descriptor",
            str(descriptor),
            "--output-root",
            str(output_root),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert json.loads(result.stdout) == {
        "code": "descriptor.schema",
        "ok": False,
    }
    assert not output_root.exists()
