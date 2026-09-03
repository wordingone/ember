# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Issue #1464 R1-E8 residual: `a1_execution.py`'s per-step telemetry write
must satisfy `a1_e8_evidence._iter_train_step_payloads` /
`derive_liveness_series` -- the exact contract the E8 liveness producer
reopens -- without fabricating the still-unwired `proxy_joules` field.

Proven against the REAL consumer functions in `a1_e8_evidence.py`, never a
mock of them: `test_wired_fields_are_consumer_compatible` and
`test_missing_proxy_joules_is_the_only_refusal_reason` feed a telemetry file
built from the real, unmocked `a1_execution._train_step_envelope` through
the real, unmocked `a1_e8_evidence._iter_train_step_payloads` and
`derive_liveness_series`. `run_dense_a1` itself is not exercised here: it
requires a certified dense >=3B CUDA allocation, full-state CPU-offloaded
AdamW, and a real token-shard corpus, none of which this wiring-only change
touches -- `_train_step_envelope` is the exact, unmocked expression it calls
per step, factored out so the envelope contract can be proven directly.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[3]
TOOLS = ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load(name: str):
    inserted = str(TOOLS) not in sys.path
    if inserted:
        sys.path.insert(0, str(TOOLS))
    try:
        return _load_module(TOOLS / f"{name}.py", f"{name}_under_test_1464")
    finally:
        if inserted:
            sys.path.remove(str(TOOLS))


A1_EXECUTION = _load("a1_execution")
EVIDENCE = _load("a1_e8_evidence")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def test_train_step_envelope_matches_frozen_shape() -> None:
    event = A1_EXECUTION._train_step_envelope(
        run_id="a1run", step=3, tokens=1024, loss=0.5, grad_norm=13.0,
        wall_seconds=0.125,
    )
    assert event["kind"] == "train_step"
    assert event["source"] == "ember-restart-3b"
    assert event["ts"].endswith("Z")
    payload = event["payload"]
    assert payload["run_id"] == "a1run"
    assert payload["step"] == 3
    assert payload["tokens"] == 1024
    # loss/wall_seconds are decimal strings (matching the existing "loss"
    # convention), never floats -- floats are not valid JSON-decimal input
    # for a1_e8_evidence's Decimal(str(value)) reopen path in every case
    # (e.g. NaN/inf), so the producer's own numeric floor stays authoritative.
    assert isinstance(payload["loss"], str)
    assert payload["grad_norm"] == "13.000000000000"
    assert isinstance(payload["wall_seconds"], str)
    assert float(payload["wall_seconds"]) == pytest.approx(0.125)
    # The deliberate residual: no fabricated energy field.
    assert "proxy_joules" not in payload


def test_wired_fields_are_consumer_compatible(tmp_path: Path) -> None:
    """Real, unmocked `_iter_train_step_payloads` + `derive_liveness_series`
    over a file built from the real, unmocked envelope helper -- with
    `proxy_joules` supplied externally (simulating a future real sampler) to
    prove tokens/wall_seconds wiring is otherwise complete and correct."""
    telemetry = tmp_path / "a1-telemetry.jsonl"
    rows = []
    for step, (tokens, wall) in enumerate([(170, 0.10), (170, 0.11), (170, 0.09)], start=1):
        event = A1_EXECUTION._train_step_envelope(
            run_id="a1run", step=step, tokens=tokens, loss=1.0 / step,
            grad_norm=1.0 + step, wall_seconds=wall,
        )
        event["payload"]["proxy_joules"] = "1.0"  # external sampler, not this producer
        rows.append(event)
    # A different run_id in the same file must be filtered out by the real consumer.
    other_run_event = A1_EXECUTION._train_step_envelope(
        run_id="other-run", step=1, tokens=999, loss=1.0, grad_norm=2.0,
        wall_seconds=1.0,
    )
    other_run_event["payload"]["proxy_joules"] = "1.0"
    rows.append(other_run_event)
    _write_jsonl(telemetry, rows)

    payloads = list(EVIDENCE._iter_train_step_payloads(telemetry, run_id="a1run"))
    assert [p["step"] for p in payloads] == [1, 2, 3]
    assert all(p["run_id"] == "a1run" for p in payloads)

    series = EVIDENCE.derive_liveness_series(
        telemetry, run_id="a1run", run_receipt_sha256="a" * 64,
    )
    assert series["schema_version"] == EVIDENCE.LIVENESS_SERIES_SCHEMA
    assert [s["step"] for s in series["samples"]] == [1, 2, 3]
    assert series["samples"][1]["wall_seconds"] == "0.110000000000"
    assert series["samples"][0]["tokens"] == "170"


def test_missing_proxy_joules_is_the_only_refusal_reason(tmp_path: Path) -> None:
    """The named residual, proven precisely: a telemetry file produced
    exactly as `run_dense_a1` would emit it today (tokens + wall_seconds
    wired, proxy_joules honestly absent) is refused by the real,
    unmocked `derive_liveness_series` -- not with a schema/shape defect,
    but specifically because no liveness-complete row exists."""
    telemetry = tmp_path / "a1-telemetry.jsonl"
    rows = [
        A1_EXECUTION._train_step_envelope(
            run_id="a1run", step=step, tokens=170, loss=1.0,
            grad_norm=2.0, wall_seconds=0.1,
        )
        for step in (1, 2, 3)
    ]
    _write_jsonl(telemetry, rows)

    # The real consumer still parses every row (envelope shape is correct) --
    # it is derive_liveness_series's completeness filter that refuses.
    payloads = list(EVIDENCE._iter_train_step_payloads(telemetry, run_id="a1run"))
    assert len(payloads) == 3
    assert all("proxy_joules" not in p for p in payloads)

    with pytest.raises(EVIDENCE.E8EvidenceProducerError, match="no liveness-complete train_step rows"):
        EVIDENCE.derive_liveness_series(telemetry, run_id="a1run", run_receipt_sha256="a" * 64)
