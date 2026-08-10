# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


HERE = Path(__file__).resolve()
MODULE_PATH = HERE.parents[1] / "scripts" / "verify_issue35_terminal_conservation.py"
SPEC = importlib.util.spec_from_file_location("issue35_terminal", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
REPO = Path(__file__).resolve().parents[1]
PACKET = REPO / MODULE.PACKET_PATH
RECEIPT = REPO / "receipts" / "issue35" / "issue-35-terminal-conservation-v1.json"


def resign(packet: dict) -> dict:
    packet["packet_sha256"] = MODULE._packet_hash(packet)
    return packet


def test_canonical_packet_is_exact_and_zero_credit():
    packet = MODULE.json.loads(PACKET.read_text(encoding="utf-8"))
    result = MODULE.validate_packet(REPO, packet)
    assert result["status"] == "PASS_FOR_TERMINAL_ZERO_CREDIT"
    assert result["source_row_count"] == 251
    assert result["operator_disposition_rows"] == 126
    assert result["recoverable_or_transferred_rows"] == 125
    assert result["completion_credit"] is False
    assert result["no_new_parallel_authority"] is True
    assert packet == MODULE.build_packet(REPO)


@pytest.mark.parametrize("mutation,match", [
    (lambda p: p["rows"].pop(), "count"),
    (lambda p: p["rows"].append(copy.deepcopy(p["rows"][0])), "count"),
    (lambda p: p["rows"][0].update({"completion_credit": True}), "not exact"),
    (lambda p: p["rows"][0].update({"target": "EMBER-01"}), "not exact"),
    (lambda p: p["rows"][0].update({"source_id": "FOREIGN"}), "foreign"),
    (lambda p: p["denominators"].update({"issue35_mandates": 101}), "denominator"),
])
def test_packet_refuses_loss_credit_foreign_rows_and_denominator_drift(mutation, match):
    packet = MODULE.build_packet(REPO)
    mutation(packet)
    resign(packet)
    with pytest.raises(MODULE.TerminalConservationError, match=match):
        MODULE.validate_packet(REPO, packet)


def test_packet_refuses_tampered_source_binding_and_self_hash():
    packet = MODULE.build_packet(REPO)
    packet["source_crosswalk"]["sha256"] = "0" * 64
    resign(packet)
    with pytest.raises(MODULE.TerminalConservationError, match="source crosswalk"):
        MODULE.validate_packet(REPO, packet)
    packet = MODULE.build_packet(REPO)
    packet["packet_sha256"] = "0" * 64
    with pytest.raises(MODULE.TerminalConservationError, match="self-hash"):
        MODULE.validate_packet(REPO, packet)


def test_conservation_receipt_is_self_hashing_zero_credit_and_path_free():
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    recorded = receipt.pop("receipt_sha256")
    actual = hashlib.sha256(
        json.dumps(receipt, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    assert recorded == actual
    assert receipt["verdict"] == "PASS_FOR_TERMINAL_ZERO_CREDIT"
    assert receipt["goal_id"] == "EMBER-02"
    assert receipt["workstream_id"] == "EMBER-02A"
    assert receipt["next_executed_outcome"] == (
        "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
    )
    assert receipt["invariant_sha256"] == (
        "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"
    )
    assert receipt["sha_convention"]
    assert not any(receipt["credits"].values())
    assert receipt["no_new_parallel_authority"] is True
    encoded = json.dumps(receipt, sort_keys=True)
    assert ":\\" not in encoded and "B:/" not in encoded
