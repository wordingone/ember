# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""R1-E8 per-step energy derivation -- issue #1464's named residual.

`a1_e8_evidence.derive_liveness_series` requires each `train_step` telemetry
row to carry `proxy_joules` before it counts as liveness-complete.
`a1_execution._train_step_envelope` wires `tokens` and `wall_seconds`
honestly but deliberately leaves `proxy_joules` absent, because
`energy_proxy_logger.py` only integrates GPU/CPU draw over a run's whole
lifetime, out-of-process at 1 Hz -- there was no per-step energy source to
attribute from.

As of this module, the sidecar (`energy_proxy_logger.py::run_watch`) also
persists its raw measured-window GPU readings, one `{"ts": <unix seconds>,
"watts": <non-negative float>}` object per line, to the sibling file
`energy_proxy_logger.samples_path_for(receipt_path)`. This module reopens
that raw record and a run's raw `train_step` telemetry, and derives each
step's `proxy_joules` as the trapezoidal integral of REAL measured draw over
the step's whole-boundary wall interval `[ts - wall_seconds, ts]` (the same
`ts`/`wall_seconds` pair `_train_step_envelope` already writes).

This is measured apportionment, never fabrication: a step's `proxy_joules`
is minted only when both interval boundaries interpolate inside the sample
record's own timestamp coverage, so the trapezoid interpolates only between
real observations and never extrapolates past one -- exactly what
`energy_proxy_logger.trapezoidal_joules` already does for the whole-run
integral, restricted here to one step's sub-interval. Any raw sample
timestamps that fall strictly inside the interval are folded into the same
trapezoid as extra interior points (unchanged from before this amendment,
and producing identical values whenever such points exist); a step whose
interval contains none is no longer refused for that reason alone, because
the boundary interpolation itself already bounds the estimate to real
observations on both sides. A boundary that would require bridging a wide
gap between raw samples -- a sampler outage, not ordinary 1 Hz jitter -- is
refused via `MAX_BRACKET_GAP_S` below, the same way a boundary outside the
record's coverage is refused. A step that fails either guard keeps no
`proxy_joules` field at all; the caller must never substitute zero, an
average, or any other placeholder for it. `a1_e8_evidence.derive_liveness_series`
continues to correctly treat that step as liveness-incomplete.

Architectural decision (post-pass, not in-loop): the energy sidecar and the
A1 training loop are two independent OS processes, communicating only
through a pidfile (`certified_train_launch.py::_start_energy_sidecar`) --
deliberately, so an evidence sampler can never block or crash the certified
training child (the #1489 lesson). The training loop therefore has no live
channel to the sidecar's in-flight samples while a step is executing, and
adding one would reopen exactly the coupling that isolation was built to
remove. This module runs instead as a post-pass over two already-closed
artifacts -- the sidecar's measured window has ended and the training
process has exited -- reopening both and joining them, the same
"reopen, never construct forward" discipline `a1_e8_evidence.py` already
documents for run receipts and the charged-budget contract. It is wired at
that point in `certified_train_launch.py::execute_validated_launch`, after
`_finish_energy_sidecar` and strictly before `_finalize_a1_packet_a` -- no
receipt has pinned the A1 telemetry file's bytes yet at that point, so an
in-place enrichment rewrite is safe.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
from pathlib import Path
from typing import Any


Q = Decimal("0.000000000001")
"""12 decimal places, round-half-even -- the same serialization convention
`a1_e8_evidence._serial` uses, restated independently rather than imported
(the same "two independent transcriptions" discipline that module documents
for its own reopened evidence)."""

MAX_BRACKET_GAP_S = 3.0
"""A boundary that interpolates between two raw samples separated by more
than this many seconds is refused, never interpolated across. 3x the pinned
measurement cadence (fixed-prior-manifest-v1 `energy_method.sample_hz` =
1.0 Hz, frozen_form manifest_pinned, IMMUTABLE -- this module never raises
or reads around that pin). At the pinned cadence, consecutive real samples
are normally ~1 s apart; a bracket this wide means the sidecar's measured
window actually stopped for a real interval (a stall, a gap between runs,
the sidecar not yet warmed up), not ordinary sampling jitter, and
interpolating across it would integrate over draw nobody measured."""


class EnergyApportionmentError(ValueError):
    """A structural or arithmetic defect in the reopened raw sample record
    itself, or in a telemetry row it is being joined against (malformed
    JSON, a non-finite or negative reading, an unparseable timestamp).
    Never raised merely because one step's interval lacks overlapping or
    bracketing sample coverage -- that is a normal, honest, partial-coverage
    outcome (see `apportion_step_energy`), not a defect in either record.
    """


def samples_path_for(receipt_path: str | Path) -> Path:
    """Restates `energy_proxy_logger.samples_path_for` independently: the
    raw per-sample sidecar path is the receipt path's stem with
    `.gpu-samples.jsonl`, in the same directory."""
    receipt_path = Path(receipt_path)
    return receipt_path.with_name(receipt_path.stem + ".gpu-samples.jsonl")


def _serial(value: Decimal) -> str:
    with localcontext() as ctx:
        ctx.prec = 50
        return format(value.quantize(Q, rounding=ROUND_HALF_EVEN), "f")


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == value and abs(value) != float("inf")


def _load_samples(samples_path: Path) -> list[tuple[float, float]]:
    """Reopen the raw measured-window GPU samples, sorted by timestamp.

    Every line is either well-formed and non-negative, or the WHOLE file is
    refused: a corrupted or negative-power sample stream cannot be trusted
    to bound any step's interval honestly, including steps far from the bad
    line -- a bracketing trapezoid built across an unverified gap would
    silently misattribute energy. Raises `FileNotFoundError` verbatim when
    the sidecar never ran; that is the caller's fully graceful case.
    """
    raw_text = samples_path.read_text(encoding="utf-8")
    samples: list[tuple[float, float]] = []
    for line_number, line in enumerate(raw_text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise EnergyApportionmentError(
                f"energy sample record {samples_path} line {line_number} is not valid JSON: {error}"
            ) from error
        if not isinstance(row, dict) or set(row) != {"ts", "watts"}:
            raise EnergyApportionmentError(
                f"energy sample record {samples_path} line {line_number} is not a closed {{ts, watts}} object"
            )
        ts, watts = row["ts"], row["watts"]
        if not _finite(ts):
            raise EnergyApportionmentError(
                f"energy sample record {samples_path} line {line_number} ts {ts!r} is not a finite number"
            )
        if not _finite(watts):
            raise EnergyApportionmentError(
                f"energy sample record {samples_path} line {line_number} watts {watts!r} is not a finite number"
            )
        if watts < 0:
            raise EnergyApportionmentError(
                f"energy sample record {samples_path} line {line_number} watts is negative "
                f"({watts!r}) -- measured GPU draw cannot be below zero"
            )
        samples.append((float(ts), float(watts)))
    samples.sort(key=lambda row: row[0])
    return samples


def _parse_envelope_ts(value: Any, *, step: int) -> float:
    """Epoch seconds for a `train_step` envelope's `ts` field (the
    `datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")` form
    `_train_step_envelope` writes)."""
    if not isinstance(value, str):
        raise EnergyApportionmentError(f"train_step ts at step={step} is not a string: {value!r}")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError as error:
        raise EnergyApportionmentError(f"train_step ts at step={step} ({value!r}) is not ISO-8601: {error}") from error


def _interpolate_watts(samples: list[tuple[float, float]], t: float) -> float | None:
    """Linear interpolation of watts at wall-clock time `t` between real
    bracketing samples. `None` when `t` falls outside the sample record's
    own coverage `[samples[0][0], samples[-1][0]]` -- extrapolation, which
    this module never performs -- or when the two samples bracketing `t`
    are separated by more than `MAX_BRACKET_GAP_S` (a sampler outage, not
    ordinary cadence jitter; see that constant's docstring). `t` landing
    exactly on a real sample timestamp always returns that sample's own
    reading, with no bracket-gap check: no interpolation is happening."""
    if not samples or t < samples[0][0] or t > samples[-1][0]:
        return None
    if t == samples[0][0]:
        return samples[0][1]
    if t == samples[-1][0]:
        return samples[-1][1]
    for (t0, w0), (t1, w1) in zip(samples, samples[1:]):
        if t0 <= t <= t1:
            if t1 == t0:
                return w0
            if t1 - t0 > MAX_BRACKET_GAP_S:
                return None
            return w0 + (t - t0) / (t1 - t0) * (w1 - w0)
    return None  # unreachable: the coverage check above already bounds t


def _integrate_step(samples: list[tuple[float, float]], start: float, end: float) -> Decimal | None:
    """Trapezoidal joules over `[start, end]`, or `None` when the step
    cannot be honestly derived: either boundary falls outside the sample
    record's own coverage (extrapolation), or either boundary would require
    interpolating across a bracket wider than `MAX_BRACKET_GAP_S` (a
    sampler outage). Both boundaries interpolating inside real coverage is
    now sufficient on its own -- the trapezoid between the two interpolated
    boundary points is derived even when no raw sample timestamp falls
    strictly inside `[start, end]`, because each boundary is already bounded
    to real, nearby observations by the two guards above. Any raw sample
    timestamps that DO fall inside the interval are folded in as additional
    interior points of the same trapezoid, unchanged from before this
    amendment and producing byte-identical values whenever they exist.
    """
    if end <= start:
        return None
    start_watts = _interpolate_watts(samples, start)
    end_watts = _interpolate_watts(samples, end)
    if start_watts is None or end_watts is None:
        return None
    points: dict[float, float] = {start: start_watts, end: end_watts}
    for t, w in samples:
        if start <= t <= end:
            points.setdefault(t, w)
    ordered = sorted(points.items())
    total = Decimal(0)
    for (t0, w0), (t1, w1) in zip(ordered, ordered[1:]):
        total += (Decimal(str(w0)) + Decimal(str(w1))) / 2 * Decimal(str(t1 - t0))
    return total


def apportion_step_energy(
    telemetry_path: Path, samples_path: Path, *, run_id: str
) -> dict[int, Decimal]:
    """Derive `{step: proxy_joules}` for every `train_step` row belonging to
    `run_id` in `telemetry_path` whose interval `_integrate_step` can
    honestly derive from `samples_path`. A step absent from the returned
    mapping has no derivable energy for this run -- callers must leave its
    `proxy_joules` field unset, never substitute a placeholder.

    `samples_path` absent is the fully graceful "no sampler ran" case: an
    empty mapping, so every step stays liveness-incomplete -- exactly the
    state `a1_e8_evidence.derive_liveness_series` already refuses correctly
    today. A PRESENT but malformed or negative-power samples record is a
    structural defect and raises `EnergyApportionmentError` (`_load_samples`).
    """
    try:
        samples = _load_samples(Path(samples_path))
    except FileNotFoundError:
        return {}
    if not samples:
        return {}
    result: dict[int, Decimal] = {}
    with Path(telemetry_path).open("rb") as handle:
        for raw_line in handle:
            if len(raw_line) > 4096:
                continue
            try:
                event = json.loads(raw_line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(event, dict) or event.get("kind") != "train_step" or event.get("source") != "ember-restart-3b":
                continue
            payload = event.get("payload")
            if not isinstance(payload, dict) or payload.get("run_id") != run_id:
                continue
            step = payload.get("step")
            if type(step) is not int or step <= 0:
                continue
            wall_raw = payload.get("wall_seconds")
            if isinstance(wall_raw, bool) or not isinstance(wall_raw, (str, int, float)):
                continue
            try:
                wall = float(wall_raw)
            except (TypeError, ValueError):
                continue
            if not _finite(wall) or wall <= 0:
                continue
            end = _parse_envelope_ts(event.get("ts"), step=step)
            start = end - wall
            joules = _integrate_step(samples, start, end)
            if joules is not None:
                result[step] = joules
    return result


def enrich_telemetry_with_energy(
    telemetry_path: Path, samples_path: Path, *, run_id: str
) -> int:
    """Rewrite `telemetry_path` in place, adding `payload.proxy_joules` to
    every `run_id` `train_step` row `apportion_step_energy` could honestly
    derive. Every other line -- other runs, other event kinds, and any row
    this pass could not derive -- is left byte-identical. A row that
    already carries `proxy_joules` is left untouched (idempotent re-run,
    never overwriting an existing value). Returns the count of rows
    enriched.

    Rewritten atomically (same-directory temp file, fsync, `os.replace`) so
    a crash mid-rewrite never leaves a truncated telemetry file -- the file
    this pass reopens is the SAME evidence `a1_e8_evidence.py` later reopens
    by raw bytes, and a truncated write would be indistinguishable from a
    genuinely short run.
    """
    telemetry_path = Path(telemetry_path)
    joules_by_step = apportion_step_energy(telemetry_path, Path(samples_path), run_id=run_id)
    if not joules_by_step:
        return 0
    enriched_lines: list[bytes] = []
    enriched_count = 0
    with telemetry_path.open("rb") as handle:
        for raw_line in handle:
            stripped = raw_line.rstrip(b"\n")
            if not stripped:
                enriched_lines.append(raw_line)
                continue
            try:
                event = json.loads(stripped.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                enriched_lines.append(raw_line)
                continue
            payload = event.get("payload") if isinstance(event, dict) else None
            step = payload.get("step") if isinstance(payload, dict) else None
            if (
                isinstance(event, dict)
                and event.get("kind") == "train_step"
                and event.get("source") == "ember-restart-3b"
                and isinstance(payload, dict)
                and payload.get("run_id") == run_id
                and "proxy_joules" not in payload
                and type(step) is int
                and step in joules_by_step
            ):
                payload["proxy_joules"] = _serial(joules_by_step[step])
                enriched_lines.append(json.dumps(event, sort_keys=True).encode("utf-8") + b"\n")
                enriched_count += 1
            else:
                enriched_lines.append(raw_line)
    if enriched_count == 0:
        return 0
    temporary = telemetry_path.parent / f".{telemetry_path.name}.{os.getpid()}.energy-enrich.tmp"
    with temporary.open("wb") as handle:
        handle.writelines(enriched_lines)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, telemetry_path)
    return enriched_count
