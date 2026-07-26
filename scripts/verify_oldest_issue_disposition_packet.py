#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Replay a task-015 packet from every raw issue and comment source byte."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

if __package__ in {None, ""}:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.build_oldest_issue_decisions import build_decisions
from scripts.oldest_issue_disposition import (
    PacketError,
    _AUTHORITY,
    _load_mapping,
    build_capture,
    build_packet,
    canonical_bytes,
    canonical_sha256,
    validate_packet,
)


def _expected_raw_names(capture: Mapping[str, Any]) -> set[str]:
    names = {"issues_pre.json", "issues_post.json"}
    for issue in capture["issues"]:
        number = issue["number"]
        names.add(f"comments-{number}-pre.json")
        names.add(f"comments-{number}-post.json")
    return names


def _closed_raw_files(raw_root: Path, expected_names: set[str]) -> None:
    entries = list(raw_root.iterdir())
    non_files = sorted(path.name for path in entries if not path.is_file())
    actual_names = {path.name for path in entries if path.is_file()}
    if non_files or actual_names != expected_names:
        raise PacketError(
            "raw evidence file set mismatch; "
            f"missing={sorted(expected_names - actual_names)}, "
            f"extra={sorted(actual_names - expected_names)}, "
            f"non_files={non_files}"
        )


def _bundle_projection(bundle: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: bundle[key]
        for key in sorted(set(bundle) - {"bundle_sha256"})
    }


def write_raw_bundle(raw_root: Path, output: Path) -> str:
    entries = list(raw_root.iterdir())
    if not entries or any(not path.is_file() for path in entries):
        raise PacketError("raw bundle input must be a nonempty flat file set")
    if any(path.suffix != ".json" for path in entries):
        raise PacketError("raw bundle input must contain JSON files only")
    rows = []
    for path in sorted(entries, key=lambda item: item.name):
        body = path.read_bytes()
        rows.append(
            {
                "name": path.name,
                "byte_count": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "body_base64": base64.b64encode(body).decode("ascii"),
            }
        )
    bundle: dict[str, Any] = {
        "authority": dict(_AUTHORITY),
        "schema_version": "ember-oldest-issue-raw-source-bundle-v1",
        "encoding": "base64",
        "entries": rows,
    }
    bundle["bundle_sha256"] = canonical_sha256(
        _bundle_projection(bundle)
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(bundle, ensure_ascii=True, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return bundle["bundle_sha256"]


def _materialize_raw_bundle(
    raw_bundle: Path,
    *,
    expected_names: set[str],
    target: Path,
) -> None:
    try:
        bundle = json.loads(
            raw_bundle.read_text(encoding="utf-8", errors="strict")
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PacketError(f"raw evidence bundle is unreadable: {exc}") from exc
    if not isinstance(bundle, dict) or set(bundle) != {
        "authority",
        "schema_version",
        "encoding",
        "entries",
        "bundle_sha256",
    }:
        raise PacketError("raw evidence bundle shape is invalid")
    if (
        bundle["authority"] != _AUTHORITY
        or bundle["schema_version"]
        != "ember-oldest-issue-raw-source-bundle-v1"
        or bundle["encoding"] != "base64"
    ):
        raise PacketError("raw evidence bundle identity is invalid")
    if bundle["bundle_sha256"] != canonical_sha256(
        _bundle_projection(bundle)
    ):
        raise PacketError("raw evidence bundle hash mismatch")
    entries = bundle["entries"]
    if not isinstance(entries, list):
        raise PacketError("raw evidence bundle entries are invalid")
    decoded: list[tuple[str, bytes]] = []
    names: list[str] = []
    for index, value in enumerate(entries):
        field = f"raw evidence bundle entries[{index}]"
        if not isinstance(value, dict) or set(value) != {
            "name",
            "byte_count",
            "sha256",
            "body_base64",
        }:
            raise PacketError(f"{field} shape is invalid")
        name = value["name"]
        if (
            not isinstance(name, str)
            or not name
            or Path(name).name != name
            or "/" in name
            or "\\" in name
        ):
            raise PacketError(f"{field}.name is invalid")
        byte_count = value["byte_count"]
        if (
            isinstance(byte_count, bool)
            or not isinstance(byte_count, int)
            or byte_count < 1
        ):
            raise PacketError(f"{field}.byte_count is invalid")
        digest = value["sha256"]
        body_base64 = value["body_base64"]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(ch not in "0123456789abcdef" for ch in digest)
            or not isinstance(body_base64, str)
        ):
            raise PacketError(f"{field} digest or body is invalid")
        try:
            body = base64.b64decode(
                body_base64.encode("ascii"),
                validate=True,
            )
        except (UnicodeEncodeError, ValueError) as exc:
            raise PacketError(f"{field}.body_base64 is invalid") from exc
        if (
            len(body) != byte_count
            or hashlib.sha256(body).hexdigest() != digest
        ):
            raise PacketError(f"{field} byte binding mismatch")
        names.append(name)
        decoded.append((name, body))
    if len(names) != len(set(names)) or set(names) != expected_names:
        raise PacketError(
            "raw evidence bundle entry set mismatch; "
            f"expected={sorted(expected_names)}, actual={sorted(names)}"
        )
    for name, body in decoded:
        (target / name).write_bytes(body)


def _verify_from_raw_root(
    packet: Mapping[str, Any],
    *,
    raw_root: Path,
    classifications_value: Mapping[str, Any],
    expected_master: str,
) -> dict[str, Any]:
    capture = packet["capture"]
    _closed_raw_files(raw_root, _expected_raw_names(capture))
    # The API does not encode a capture timestamp in the raw rows. The timestamp
    # is therefore subject metadata; every API-derived byte is independently
    # rebuilt and the complete capture/packet comparison still binds that value.
    rebuilt_capture = build_capture(
        raw_root,
        master_sha=expected_master,
        captured_at=capture["captured_at"],
    )
    if canonical_bytes(rebuilt_capture) != canonical_bytes(capture):
        raise PacketError("raw evidence does not reproduce embedded capture")
    rebuilt_decisions = build_decisions(
        rebuilt_capture,
        classifications_value,
    )
    rebuilt_packet = build_packet(rebuilt_capture, rebuilt_decisions)
    if canonical_bytes(rebuilt_packet) != canonical_bytes(packet):
        raise PacketError(
            "raw evidence and classifications do not reproduce packet"
        )
    return dict(packet)


def verify_replay(
    packet_value: Mapping[str, Any],
    *,
    raw_root: Path | None = None,
    raw_bundle: Path | None = None,
    classifications_value: Mapping[str, Any],
    expected_master: str,
) -> dict[str, Any]:
    if (raw_root is None) == (raw_bundle is None):
        raise PacketError(
            "exactly one raw evidence root or bundle is required"
        )
    packet = validate_packet(
        packet_value,
        expected_master=expected_master,
    )
    if raw_root is not None:
        return _verify_from_raw_root(
            packet,
            raw_root=raw_root,
            classifications_value=classifications_value,
            expected_master=expected_master,
        )
    assert raw_bundle is not None
    with tempfile.TemporaryDirectory() as directory:
        materialized = Path(directory)
        _materialize_raw_bundle(
            raw_bundle,
            expected_names=_expected_raw_names(packet["capture"]),
            target=materialized,
        )
        return _verify_from_raw_root(
            packet,
            raw_root=materialized,
            classifications_value=classifications_value,
            expected_master=expected_master,
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--raw-root", type=Path)
    source.add_argument("--raw-bundle", type=Path)
    parser.add_argument("--classifications", type=Path, required=True)
    parser.add_argument("--expected-master-sha", required=True)
    args = parser.parse_args(argv)
    try:
        packet = verify_replay(
            _load_mapping(args.packet, field="packet"),
            raw_root=(
                args.raw_root.resolve(strict=True)
                if args.raw_root is not None
                else None
            ),
            raw_bundle=(
                args.raw_bundle.resolve(strict=True)
                if args.raw_bundle is not None
                else None
            ),
            classifications_value=_load_mapping(
                args.classifications,
                field="classifications",
            ),
            expected_master=args.expected_master_sha,
        )
    except (OSError, PacketError) as exc:
        parser.error(str(exc))
    print(
        f"PACKET_REPLAY_VALID_NON_AUTHORIZING "
        f"{packet['packet_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
