# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Production-shaped positive C-AUTO v2 control fixture."""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_rows(repo_root: Path) -> list[tuple[str, str]]:
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "log",
            "-5",
            "--format=%H%x09%cI",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    rows = [tuple(line.split("\t", 1)) for line in completed.stdout.splitlines()]
    if len(rows) != 5 or any(len(row) != 2 for row in rows):
        raise RuntimeError("C-AUTO positive control requires five Git commits")
    rows.reverse()
    return [(commit, timestamp) for commit, timestamp in rows]


def build_fresh_reversion_climb(
    *,
    fixtures_dir: str,
    repo_root: str,
    isolation_note: str,
    fresh_dir: Callable[[str], str],
    write_readme: Callable[[str, str], None],
    write_json_no_marker: Callable[[str, object], None],
) -> str:
    root = Path(fresh_dir(str(Path(fixtures_dir) / "c_auto_fresh_reversion_climb")))
    write_readme(str(root), isolation_note)
    receipts_dir = root / "receipts" / "autonomy-ladder"
    receipts_dir.mkdir(parents=True, exist_ok=True)

    rows = _git_rows(Path(repo_root))
    window_refs: list[str] = []
    claim_windows: list[dict[str, str]] = []
    for index, (commit_sha, commit_ts) in enumerate(rows, start=1):
        timestamp = (
            datetime.fromisoformat(commit_ts.replace("Z", "+00:00"))
            .astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
        payload = {
            "schema": "ember-autonomy-window-v2",
            "rung": "R1",
            "window_id": f"R1-{index}",
            "ts": timestamp,
            "verdict": "PASS",
            "independent_evidence": {
                "kind": "git_commit",
                "commit_sha": commit_sha,
                "commit_ts": timestamp,
            },
        }
        payload_sha = _canonical_sha256(payload)
        provenance_core = {
            "producer": "ember",
            "window_payload_sha256": payload_sha,
        }
        receipt = {
            **payload,
            "provenance": {
                **provenance_core,
                "token_sha256": _canonical_sha256(provenance_core),
            },
        }
        name = f"R1-window-{index}.json"
        path = receipts_dir / name
        write_json_no_marker(str(path), receipt)
        window_refs.append(name)
        claim_windows.append({"path": name, "sha256": _file_sha256(path)})

    latest_ts = datetime.fromisoformat(rows[-1][1].replace("Z", "+00:00")).astimezone(
        timezone.utc
    )
    reversion_ts = (latest_ts - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    claim_ts = (latest_ts + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    write_json_no_marker(
        str(receipts_dir / "R1-claim-v2.json"),
        {
            "schema": "ember-autonomy-claim-v2",
            "rung": "R1",
            "claim": True,
            "ts": claim_ts,
            "source_commit": rows[-1][0],
            "windows": claim_windows,
        },
    )
    write_json_no_marker(
        str(receipts_dir / "reversion-v2.json"),
        {"ts": reversion_ts, "target_rung": "R0", "incident": "fixture"},
    )

    state = {
        "schema": "autonomy-ladder-state/v1",
        "contract": "docs/spec/autonomy-relinquishment-ladder-v1.md",
        "current_rung": "R1",
        "rungs": {
            "R0": {"status": "IN_BUILD", "claimed": False, "windows": []},
            "R1": {"status": "CLAIMED", "claimed": True, "windows": window_refs},
            "R2": {"status": "NOT_STARTED", "claimed": False, "windows": []},
            "R3": {"status": "BLOCKED_ON_C_E2B", "claimed": False, "windows": []},
            "R4": {"status": "NOT_STARTED", "claimed": False, "windows": []},
            "R5": {"status": "BLOCKED_ON_ISSUE_91", "claimed": False, "windows": []},
        },
        "reversion_log": [
            {
                "ts": reversion_ts,
                "target_rung": "R0",
                "incident_receipt": "receipts/autonomy-ladder/reversion-v2.json",
                "reason": "fixture reversion followed by a fresh v2 re-climb",
            }
        ],
        "promotion_rule": (
            "K=5 consecutive clean receipted windows per rung; "
            "claim itself is a receipt under receipts/autonomy-ladder/"
        ),
        "safety_floor": (
            "operator escalation set + governor caps + kill-discipline NEVER transfer"
        ),
    }
    write_json_no_marker(str(root / "autonomy-ladder-state.json"), state)
    contract = root / "docs" / "spec" / "autonomy-relinquishment-ladder-v1.md"
    contract.parent.mkdir(parents=True, exist_ok=True)
    contract.write_text(
        "# Autonomy-relinquishment ladder v1 (fixture)\n\nFixture contract.\n",
        encoding="utf-8",
        newline="\n",
    )
    return str(root)
