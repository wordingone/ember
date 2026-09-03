# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Issue #1464 residual: `a1_energy_apportionment.py` derives each
`train_step`'s `proxy_joules` from the energy sidecar's REAL raw
measured-window GPU samples (`energy_proxy_logger.py::run_watch`'s
`{"ts", "watts"}` sidecar record), never a placeholder.

`test_real_enriched_row_is_accepted_by_the_liveness_producer` is the module's
first real downstream consumer leg: it runs a telemetry file this module
actually enriched (real, unmocked `a1_execution._train_step_envelope` rows +
a real raw samples file, real `enrich_telemetry_with_energy` rewrite)
through the REAL, unmocked `a1_e8_evidence._iter_train_step_payloads` and
`derive_liveness_series` -- not a mock of either.
"""
from __future__ import annotations

import importlib.util
import json
from decimal import Decimal
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
        return _load_module(TOOLS / f"{name}.py", f"{name}_under_test_1464_energy")
    finally:
        if inserted:
            sys.path.remove(str(TOOLS))


A1_EXECUTION = _load("a1_execution")
EVIDENCE = _load("a1_e8_evidence")
APPORTIONMENT = _load("a1_energy_apportionment")


def _write_samples(path: Path, rows: list[tuple[float, float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for ts, watts in rows:
            handle.write(json.dumps({"ts": ts, "watts": watts}, sort_keys=True) + "\n")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _envelope_at(*, run_id: str, step: int, ts_epoch: float, wall_seconds: float, tokens: int = 170) -> dict:
    """A real `_train_step_envelope` row, with its `ts` overridden to a
    caller-chosen epoch second so the interval it implies
    (`[ts_epoch - wall_seconds, ts_epoch]`) can be pinned exactly against a
    hand-built sample fixture."""
    event = A1_EXECUTION._train_step_envelope(
        run_id=run_id, step=step, tokens=tokens, loss=1.0,
        grad_norm=1.0, wall_seconds=wall_seconds,
    )
    stamp = f"{ts_epoch:.6f}"
    from datetime import datetime, timezone
    event["ts"] = datetime.fromtimestamp(ts_epoch, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    assert stamp  # ts_epoch is round-tripped through isoformat below; stamp unused beyond the assert
    return event


def test_correct_apportionment_across_step_boundaries(tmp_path: Path) -> None:
    """A dense, contiguous sample series must apportion each step's joules
    as the exact trapezoidal integral of the REAL samples touching its
    interval -- summed numerator/denominator arithmetic, never an average
    borrowed from a neighboring step."""
    samples_path = tmp_path / "energy-proxy-receipt.gpu-samples.jsonl"
    _write_samples(samples_path, [(0.0, 100.0), (1.0, 150.0), (2.0, 200.0), (3.0, 250.0)])

    telemetry_path = tmp_path / "a1-telemetry.jsonl"
    _write_jsonl(telemetry_path, [
        _envelope_at(run_id="a1run", step=1, ts_epoch=1.0, wall_seconds=1.0),
        _envelope_at(run_id="a1run", step=2, ts_epoch=2.0, wall_seconds=1.0),
        _envelope_at(run_id="a1run", step=3, ts_epoch=3.0, wall_seconds=1.0),
    ])

    joules = APPORTIONMENT.apportion_step_energy(telemetry_path, samples_path, run_id="a1run")

    assert joules[1] == Decimal("125")  # (100+150)/2 * 1s
    assert joules[2] == Decimal("175")  # (150+200)/2 * 1s
    assert joules[3] == Decimal("225")  # (200+250)/2 * 1s


def test_missing_samples_file_yields_no_derivation(tmp_path: Path) -> None:
    """The energy sidecar never ran (or ran under a build predating this
    module) -- the fully graceful case: every step stays undecided, never a
    zero or an error."""
    samples_path = tmp_path / "energy-proxy-receipt.gpu-samples.jsonl"  # never written
    telemetry_path = tmp_path / "a1-telemetry.jsonl"
    _write_jsonl(telemetry_path, [
        _envelope_at(run_id="a1run", step=1, ts_epoch=1.0, wall_seconds=1.0),
    ])

    joules = APPORTIONMENT.apportion_step_energy(telemetry_path, samples_path, run_id="a1run")
    assert joules == {}

    enriched = APPORTIONMENT.enrich_telemetry_with_energy(telemetry_path, samples_path, run_id="a1run")
    assert enriched == 0
    payloads = list(EVIDENCE._iter_train_step_payloads(telemetry_path, run_id="a1run"))
    assert all("proxy_joules" not in p for p in payloads)


def test_step_with_no_overlapping_sample_stays_unapportioned(tmp_path: Path) -> None:
    """A real, well-formed sample record with a coverage gap: a step whose
    interval falls entirely between two samples (sparse 1 Hz cadence versus
    a fast step) gets no proxy_joules, while a step that IS touched by a
    real sample in the same file still derives correctly."""
    samples_path = tmp_path / "energy-proxy-receipt.gpu-samples.jsonl"
    _write_samples(samples_path, [(0.0, 100.0), (1.0, 150.0), (10.0, 500.0)])

    telemetry_path = tmp_path / "a1-telemetry.jsonl"
    _write_jsonl(telemetry_path, [
        _envelope_at(run_id="a1run", step=1, ts_epoch=1.0, wall_seconds=1.0),  # [0,1]: derivable
        _envelope_at(run_id="a1run", step=2, ts_epoch=4.5, wall_seconds=0.5),  # [4.0,4.5]: gap, sparse
    ])

    joules = APPORTIONMENT.apportion_step_energy(telemetry_path, samples_path, run_id="a1run")
    assert joules == {1: Decimal("125")}
    assert 2 not in joules


def test_step_outside_sample_coverage_stays_unapportioned(tmp_path: Path) -> None:
    """A step interval that would require extrapolating past the sample
    record's own first/last timestamp is refused for that step -- the
    trapezoid only ever interpolates between two real observations."""
    samples_path = tmp_path / "energy-proxy-receipt.gpu-samples.jsonl"
    _write_samples(samples_path, [(0.0, 100.0), (1.0, 150.0)])

    telemetry_path = tmp_path / "a1-telemetry.jsonl"
    _write_jsonl(telemetry_path, [
        _envelope_at(run_id="a1run", step=1, ts_epoch=1.0, wall_seconds=1.0),   # [0,1]: derivable
        _envelope_at(run_id="a1run", step=2, ts_epoch=5.0, wall_seconds=1.0),   # [4,5]: past last sample
    ])

    joules = APPORTIONMENT.apportion_step_energy(telemetry_path, samples_path, run_id="a1run")
    assert joules == {1: Decimal("125")}
    assert 2 not in joules


def test_malformed_sample_line_refuses_the_whole_record(tmp_path: Path) -> None:
    samples_path = tmp_path / "energy-proxy-receipt.gpu-samples.jsonl"
    samples_path.parent.mkdir(parents=True, exist_ok=True)
    samples_path.write_text(
        json.dumps({"ts": 0.0, "watts": 100.0}) + "\n"
        + "{not valid json\n",
        encoding="utf-8",
    )
    telemetry_path = tmp_path / "a1-telemetry.jsonl"
    _write_jsonl(telemetry_path, [
        _envelope_at(run_id="a1run", step=1, ts_epoch=1.0, wall_seconds=1.0),
    ])

    with pytest.raises(APPORTIONMENT.EnergyApportionmentError, match="not valid JSON"):
        APPORTIONMENT.apportion_step_energy(telemetry_path, samples_path, run_id="a1run")


def test_negative_watts_refuses_the_whole_record(tmp_path: Path) -> None:
    samples_path = tmp_path / "energy-proxy-receipt.gpu-samples.jsonl"
    _write_samples(samples_path, [(0.0, 100.0), (1.0, -5.0)])
    telemetry_path = tmp_path / "a1-telemetry.jsonl"
    _write_jsonl(telemetry_path, [
        _envelope_at(run_id="a1run", step=1, ts_epoch=1.0, wall_seconds=1.0),
    ])

    with pytest.raises(APPORTIONMENT.EnergyApportionmentError, match="negative"):
        APPORTIONMENT.apportion_step_energy(telemetry_path, samples_path, run_id="a1run")


def test_enrich_telemetry_preserves_other_rows_and_is_idempotent(tmp_path: Path) -> None:
    samples_path = tmp_path / "energy-proxy-receipt.gpu-samples.jsonl"
    _write_samples(samples_path, [(0.0, 100.0), (1.0, 150.0), (2.0, 200.0)])

    telemetry_path = tmp_path / "a1-telemetry.jsonl"
    other_run_row = _envelope_at(run_id="other-run", step=1, ts_epoch=1.0, wall_seconds=1.0)
    _write_jsonl(telemetry_path, [
        _envelope_at(run_id="a1run", step=1, ts_epoch=1.0, wall_seconds=1.0),
        _envelope_at(run_id="a1run", step=2, ts_epoch=2.0, wall_seconds=1.0),
        other_run_row,
    ])
    before_other_row_bytes = json.dumps(other_run_row, sort_keys=True)

    enriched = APPORTIONMENT.enrich_telemetry_with_energy(telemetry_path, samples_path, run_id="a1run")
    assert enriched == 2

    lines = telemetry_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    row1 = json.loads(lines[0])
    row2 = json.loads(lines[1])
    row_other = json.loads(lines[2])
    assert row1["payload"]["proxy_joules"] == "125.000000000000"
    assert row2["payload"]["proxy_joules"] == "175.000000000000"
    assert json.dumps(row_other, sort_keys=True) == before_other_row_bytes  # byte-identical, untouched

    # Idempotent: a second pass finds nothing left to enrich (proxy_joules
    # already present on both a1run rows) and touches nothing further.
    again = APPORTIONMENT.enrich_telemetry_with_energy(telemetry_path, samples_path, run_id="a1run")
    assert again == 0
    assert telemetry_path.read_text(encoding="utf-8").splitlines() == lines


def test_boundary_interpolation_derives_a_step_with_zero_interior_samples(tmp_path: Path) -> None:
    """Issue #1464's named residual: a step whose wall duration (130 ms) is
    far shorter than the pinned 1.0 Hz sampling interval touches no raw
    sample directly, but both its boundaries interpolate between the same
    close-by pair of real samples -- derivable under the amended rule on
    that basis alone."""
    samples_path = tmp_path / "energy-proxy-receipt.gpu-samples.jsonl"
    _write_samples(samples_path, [(0.0, 100.0), (1.0, 150.0), (2.0, 200.0)])

    telemetry_path = tmp_path / "a1-telemetry.jsonl"
    _write_jsonl(telemetry_path, [
        # [1.20, 1.33]: both boundaries interpolate inside the [1.0, 2.0]
        # bracket (1.0 s wide, within MAX_BRACKET_GAP_S); no sample ts
        # (1.0 or 2.0) falls strictly inside [1.20, 1.33].
        _envelope_at(run_id="a3run", step=1, ts_epoch=1.33, wall_seconds=0.13),
    ])

    joules = APPORTIONMENT.apportion_step_energy(telemetry_path, samples_path, run_id="a3run")

    assert 1 in joules
    # Linear watts(t) = 150 + 50*(t-1.0) on [1.0, 2.0]; trapezoid of that
    # exact line over [1.20, 1.33] equals its analytic integral (matched to
    # within the module's own float-interpolation precision, since the
    # implementation interpolates in float before converting to Decimal).
    start_w = Decimal("150") + Decimal("50") * Decimal("0.20")
    end_w = Decimal("150") + Decimal("50") * Decimal("0.33")
    expected = (start_w + end_w) / 2 * Decimal("0.13")
    assert abs(joules[1] - expected) < Decimal("0.000000001")


def test_boundary_bracket_wider_than_max_gap_refuses(tmp_path: Path) -> None:
    """A step whose interpolated boundaries fall inside overall sample
    coverage but whose bracketing real samples are separated by more than
    `MAX_BRACKET_GAP_S` is refused -- the amendment never bridges a real
    sampler outage, only ordinary cadence jitter."""
    gap = APPORTIONMENT.MAX_BRACKET_GAP_S + 1.0
    samples_path = tmp_path / "energy-proxy-receipt.gpu-samples.jsonl"
    _write_samples(samples_path, [(0.0, 100.0), (gap, 200.0), (gap + 1.0, 210.0)])

    telemetry_path = tmp_path / "a1-telemetry.jsonl"
    midpoint = gap / 2
    _write_jsonl(telemetry_path, [
        # Interval sits entirely inside the wide [0.0, gap] bracket -- both
        # boundaries would interpolate, but the bracket itself is an outage.
        _envelope_at(run_id="a3run", step=1, ts_epoch=midpoint + 0.05, wall_seconds=0.10),
    ])

    joules = APPORTIONMENT.apportion_step_energy(telemetry_path, samples_path, run_id="a3run")
    assert joules == {}


def test_interior_sample_step_byte_identical_before_and_after_amendment(tmp_path: Path) -> None:
    """Pinned regression: a step interval that DOES contain a real sample
    must derive the exact same Decimal under the amended rule as it did
    before -- the amendment only widens which zero-interior-sample steps
    derive, it never changes an already-derivable value."""
    samples_path = tmp_path / "energy-proxy-receipt.gpu-samples.jsonl"
    _write_samples(samples_path, [(0.0, 100.0), (1.0, 150.0), (2.0, 200.0), (3.0, 250.0)])

    telemetry_path = tmp_path / "a1-telemetry.jsonl"
    _write_jsonl(telemetry_path, [
        _envelope_at(run_id="a1run", step=1, ts_epoch=1.0, wall_seconds=1.0),
        _envelope_at(run_id="a1run", step=2, ts_epoch=2.0, wall_seconds=1.0),
        _envelope_at(run_id="a1run", step=3, ts_epoch=3.0, wall_seconds=1.0),
    ])

    joules = APPORTIONMENT.apportion_step_energy(telemetry_path, samples_path, run_id="a1run")

    # Pinned to the pre-amendment values asserted by
    # test_correct_apportionment_across_step_boundaries.
    assert joules[1] == Decimal("125")
    assert joules[2] == Decimal("175")
    assert joules[3] == Decimal("225")


def test_a3_shaped_run_derives_all_one_hundred_fast_steps(tmp_path: Path) -> None:
    """Synthesizes the A3 semantic arm's real shape (1.0 Hz samples spanning
    the run, 100 sub-second step intervals) without committing the real
    multi-MB run artifacts. Under the pre-amendment rule only steps whose
    interval happens to straddle an integer second derive (~14/100,
    noncontiguous, matching the real A3 run's receipted
    {2,9,16,23,30,38,47,53,61,66,72,80,87,95}); under the amended rule every
    step's interval sits inside a single 1.0 s bracket with both boundaries
    interpolating, so all 100 derive."""
    samples_path = tmp_path / "energy-proxy-receipt.gpu-samples.jsonl"
    _write_samples(samples_path, [(float(t), 100.0 + t) for t in range(0, 101)])

    telemetry_path = tmp_path / "a1-telemetry.jsonl"
    rows = []
    for step in range(1, 101):
        # Step i's ~130 ms interval sits at a fixed offset inside second
        # (step - 1), i.e. entirely inside one real [t, t+1] bracket.
        end = (step - 1) + 0.63
        rows.append(_envelope_at(run_id="a3run", step=step, ts_epoch=end, wall_seconds=0.13))
    _write_jsonl(telemetry_path, rows)

    joules = APPORTIONMENT.apportion_step_energy(telemetry_path, samples_path, run_id="a3run")

    assert len(joules) == 100
    assert set(joules) == set(range(1, 101))
    assert all(j > 0 for j in joules.values())


def test_real_enriched_row_is_accepted_by_the_liveness_producer(tmp_path: Path) -> None:
    """The first real downstream consumer leg: a telemetry file this module
    ACTUALLY enriched (real envelope rows, a real raw samples file, a real
    in-place rewrite) is fed through the real, unmocked
    `a1_e8_evidence._iter_train_step_payloads` and `derive_liveness_series`
    -- proving the enriched shape this module produces is exactly what the
    E8 liveness producer already reopens, with no adapter in between."""
    samples_path = tmp_path / "energy-proxy-receipt.gpu-samples.jsonl"
    _write_samples(samples_path, [(0.0, 100.0), (1.0, 150.0), (2.0, 200.0), (3.0, 250.0)])

    telemetry_path = tmp_path / "a1-telemetry.jsonl"
    _write_jsonl(telemetry_path, [
        _envelope_at(run_id="a1run", step=1, ts_epoch=1.0, wall_seconds=1.0),
        _envelope_at(run_id="a1run", step=2, ts_epoch=2.0, wall_seconds=1.0),
        _envelope_at(run_id="a1run", step=3, ts_epoch=3.0, wall_seconds=1.0),
    ])

    enriched = APPORTIONMENT.enrich_telemetry_with_energy(telemetry_path, samples_path, run_id="a1run")
    assert enriched == 3

    payloads = list(EVIDENCE._iter_train_step_payloads(telemetry_path, run_id="a1run"))
    assert len(payloads) == 3
    assert all("proxy_joules" in p for p in payloads)

    series = EVIDENCE.derive_liveness_series(telemetry_path, run_id="a1run", run_receipt_sha256="a" * 64)
    assert series["schema_version"] == EVIDENCE.LIVENESS_SERIES_SCHEMA
    assert [s["step"] for s in series["samples"]] == [1, 2, 3]
    assert series["samples"][0]["proxy_joules"] == "125.000000000000"
    assert series["samples"][1]["proxy_joules"] == "175.000000000000"
    assert series["samples"][2]["proxy_joules"] == "225.000000000000"
