# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "manifests" / "architecture" / "root-terminal-exceptions-v1.json"

MOVES = {
    "Ember.cmd": (
        "tools/launchers/Ember.cmd",
        "85a5270c922953d7e7f6491140df6e20f7d81faa10d5ad30e96e96186f1298a6",
        "5589fab9cade0133b25488b1be0759f35433d7667260fbd7a4176c67a8cffb94",
    ),
    "autonomy-ladder-state.json": (
        "docs/domains/governance/authority/autonomy-ladder-state.json",
        "ce544e0b0cb28fed957caddb4773e1005003a7f1ab4d77f2d7e6a61d17ff7b8e",
        "ce544e0b0cb28fed957caddb4773e1005003a7f1ab4d77f2d7e6a61d17ff7b8e",
    ),
    "kernel-v1.0.manifest": (
        "manifests/governance/kernel-v1.0.manifest",
        "5adb13837aee2454212b0cdbbb1162b253f91f207fc4957d2fa1596a310fa998",
        "5adb13837aee2454212b0cdbbb1162b253f91f207fc4957d2fa1596a310fa998",
    ),
}
ROOT_EXCEPTIONS = {
    ".gitattributes": "Git worktree attribute discovery requires the control file at repository root.",
    ".gitignore": "Repository-wide Git ignore discovery requires the control file at repository root.",
    "pyproject.toml": "PEP 517 builds and repository-wide pytest discovery require the project declaration at repository root.",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_root_terminal_receipt_is_closed_and_exact() -> None:
    payload = json.loads(RECEIPT.read_text(encoding="utf-8"))
    assert set(payload) == {
        "schema_version",
        "goal_id",
        "workstream_id",
        "issue",
        "source_overlay",
        "retained_root_files",
        "named_root_exceptions",
        "moves",
        "live_consumer_rewrites",
        "historical_reference_adjudications",
    }
    assert payload["schema_version"] == "ember-issue2003-root-terminal-v1"
    assert payload["goal_id"] == "EMBER-02"
    assert payload["workstream_id"] == "EMBER-02A"
    assert payload["issue"] == 2003
    assert payload["source_overlay"] == {
        "path": "state/reports/issue1949-a-map-amendment-v2-root-priority-20260829.json",
        "raw_sha256": "03d02aaf43992eb14ba845e72d8669f1cd72623243a2be833caca3bd144afd15",
        "self_sha256": "714b95bcadac1c1137e8cedaaf485aff94c1aec1336e1919a1376fad28c0ccbb",
        "rewrite_consumer_count": 46,
        "rewrite_consumers_sha256": "23b37a31b236d4a14dc783ac5f9ff13698b8e45a0139c8bb359a7a6cf5fa143b",
    }
    assert payload["retained_root_files"] == ["AGENTS.md", "LICENSE", "README.md"]
    assert payload["named_root_exceptions"] == [
        {"path": path, "constraint": constraint}
        for path, constraint in sorted(ROOT_EXCEPTIONS.items())
    ]
    assert payload["moves"] == [
        {
            "source": source,
            "destination": destination,
            "source_raw_sha256": source_digest,
            "destination_raw_sha256": destination_digest,
        }
        for source, (destination, source_digest, destination_digest) in sorted(
            MOVES.items()
        )
    ]
    rows = payload["historical_reference_adjudications"]
    assert isinstance(rows, list) and rows
    assert rows == sorted(rows, key=lambda row: (row["document"], row["literal"]))
    assert all(set(row) == {"document", "literal", "disposition"} for row in rows)
    assert all(row["disposition"] == "IMMUTABLE_HISTORICAL_REFERENCE" for row in rows)
    live = payload["live_consumer_rewrites"]
    assert live == sorted(live)
    assert len(live) == 25
    assert all((ROOT / path).is_file() for path in live)
    assert len(rows) + len(live) == payload["source_overlay"]["rewrite_consumer_count"]
    assert not ({row["document"] for row in rows} & set(live))


def test_root_file_law_and_moved_bytes() -> None:
    ordinary = sorted(
        path.name
        for path in ROOT.iterdir()
        if path.is_file() and path.name not in ROOT_EXCEPTIONS
    )
    assert ordinary == ["AGENTS.md", "LICENSE", "README.md"]
    for source, (destination, _source_digest, destination_digest) in MOVES.items():
        assert not (ROOT / source).exists()
        target = ROOT / destination
        assert target.is_file()
        assert sha256(target) == destination_digest


def test_architecture_policy_names_every_root_disposition() -> None:
    policy = json.loads(
        (ROOT / "manifests" / "architecture" / "domain-authority-v1.json").read_text(
            encoding="utf-8"
        )
    )
    root_rules = {
        row["id"]: row
        for row in policy["path_rules"]
        if row["id"].startswith("root-")
    }
    assert root_rules["root-control-exceptions"]["include"] == sorted(ROOT_EXCEPTIONS)
    assert root_rules["root-control-exceptions"]["disposition"] == "RETAIN_STABLE"
    assert root_rules["root-control-exceptions"]["named_constraints"] == ROOT_EXCEPTIONS
    assert root_rules["root-retained-documents"]["include"] == [
        "AGENTS.md",
        "LICENSE",
        "README.md",
    ]
    classified_root_paths = {
        path for row in root_rules.values() for path in row["include"]
    }
    assert classified_root_paths == set(ROOT_EXCEPTIONS) | {
        "AGENTS.md",
        "LICENSE",
        "README.md",
    }


def test_canonical_launcher_has_exact_authority_sidecar() -> None:
    launcher = ROOT / "tools" / "launchers" / "Ember.cmd"
    sidecar = json.loads(
        (ROOT / "tools" / "launchers" / "Ember.authority.json").read_text(
            encoding="utf-8"
        )
    )
    assert sidecar["schema_version"] == "ember-content-addressed-authority-binding/v1"
    assert sidecar["artifact_path"] == "tools/launchers/Ember.cmd"
    assert sidecar["artifact_sha256"] == hashlib.sha256(launcher.read_bytes()).hexdigest()
    assert sidecar["goal_id"] == "EMBER-02"
    assert sidecar["workstream_id"] == "EMBER-02A"
